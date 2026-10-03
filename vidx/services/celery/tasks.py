import logging
import os
import uuid
from datetime import datetime
from subprocess import CalledProcessError
from subprocess import run as subprocess_run
from typing import Dict, Optional

from vidx.services.celery.worker import celery
from vidx.services.task_execution import (
    ExecutionStrategyFactory,
    TaskExecutionManager,
)
from vidx.settings import settings

logger = logging.getLogger(__name__)

# Initialize task execution manager on module load
_execution_manager: Optional[TaskExecutionManager] = None


def get_execution_manager() -> TaskExecutionManager:
    """
    Get or create the task execution manager.

    Uses lazy initialization to ensure settings are loaded.
    """
    global _execution_manager

    if _execution_manager is None:
        strategy = ExecutionStrategyFactory.create_strategy(
            environment=settings.environment,
            aws_region=settings.aws_region,
            batch_job_queue=settings.batch_job_queue,
            batch_job_definition=settings.batch_job_definition,
            s3_bucket=settings.s3_bucket,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            aws_endpoint_url=settings.aws_endpoint_url,
            ffmpeg_binary=settings.ffmpeg,
        )
        _execution_manager = TaskExecutionManager(strategy)
        logger.info(f"Task execution manager created with: {strategy.get_name()}")

    return _execution_manager


def _gpu_available(ffmpeg_bin: str) -> bool:
    """Detect if NVENC GPU encoding is available via ffmpeg encoders list."""
    try:
        result = subprocess_run(
            [ffmpeg_bin, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False,
        )
        return "h264_nvenc" in result.stdout or "h264_nvenc" in result.stderr
    except Exception:
        return False


def mime_to_codecs(mime: str) -> tuple[str, str, str]:
    if mime == "video/mp4":
        return "libx264", "aac", "mp4"
    if mime == "video/webm":
        return "libvpx-vp9", "libopus", "webm"
    if mime == "video/ogg":
        return "libtheora", "libvorbis", "ogv"
    raise ValueError(f"Unsupported MIME type: {mime}")


def _merge_videos_sync(
    videos: Dict[str, float],
    audio: str | None,
    video_mime: str,
    video_resolution: tuple[int, int],
    audio_duration: float | None,
    transition: str,
) -> str:
    """
    Synchronous video merge implementation using FFmpeg.

    Called by LocalProcessExecutor for direct execution.
    Original implementation preserved for local development.

    :param videos: List of video paths to merge with their durations.
    :param audio: Path to the audio file.
    :param video_mime: MIME type of the video.
    :param video_resolution: Resolution of the video.
    :param audio_duration: Duration of the audio file.
    :param transition: Transition effect to apply between videos.
    :return: Output path for the merged video.
    """
    ffmpeg_bin = os.environ.get("FFMPEG_BINARY") or "ffmpeg"
    transition_path = f"{os.path.dirname(ffmpeg_bin)}/{transition}"
    transition_duration = 1.0
    inputs = list(videos.keys())
    durations = list(videos.values())

    # Determine output codec and extension based on mime
    vcodec, acodec, ext = mime_to_codecs(video_mime)
    use_gpu = video_mime == "video/mp4" and _gpu_available(ffmpeg_bin)
    gpu_args: list[str] = ["-hwaccel", "cuda"] if use_gpu else []
    # Prefer NVENC when available for MP4
    if use_gpu and vcodec == "libx264":
        vcodec = "h264_nvenc"

    # Check if videos have audio streams
    def has_audio_stream(file_path: str) -> bool:
        cmd = [ffmpeg_bin, "-i", file_path]
        result = subprocess_run(cmd, capture_output=True, text=True, check=False)
        return "Stream #0:1" in result.stderr and "Audio:" in result.stderr

    # Check each input video for audio track
    video_audio_status = {
        input_file: has_audio_stream(input_file) for input_file in inputs
    }
    # Only process audio if there's no external audio and at least one video has audio
    process_audio = audio is None and any(video_audio_status.values())

    width, height = video_resolution
    # Unique merge file name
    merge_file = f"/tmp/{uuid.uuid4().hex}.{ext}"

    # If only one clip, just return it (copy to merge_file)
    if len(inputs) == 1:
        cmd = [
            ffmpeg_bin,
            "-i",
            inputs[0],
            *gpu_args,
            "-c:v",
            vcodec,
            *(["-c:a", acodec] if audio is None else ["-c:a", "copy"]),
            "-y",
            merge_file,
        ]
        result = subprocess_run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise CalledProcessError(
                result.returncode,
                cmd,
                result.stdout,
                result.stderr,
            )
        return merge_file

    # First merge: clip 0 + clip 1 -> merge_file
    d0, d1 = durations[0], durations[1]
    filter_parts = [
        # video trims
        f"[0:v]trim=0:{d0 - transition_duration},setpts=PTS-STARTPTS[v0_main];",
        f"[0:v]trim={d0 - transition_duration}:{d0},setpts=PTS-STARTPTS[v0_tail];",
        f"[1:v]trim=0:{transition_duration},setpts=PTS-STARTPTS[v1_head];",
        f"[1:v]trim={transition_duration}:{d1},setpts=PTS-STARTPTS[v1_rest];",
        # transition
        f"[v0_tail][v1_head]gltransition=duration={transition_duration}:source={transition_path}[v_trans];",
    ]

    # audio trims - only if both videos have audio streams and no external audio
    first_has_audio = video_audio_status[inputs[0]]
    second_has_audio = video_audio_status[inputs[1]]

    if process_audio and first_has_audio and second_has_audio:
        # Both videos have audio - standard processing
        filter_parts += [
            f"[0:a]atrim=0:{d0 - transition_duration},asetpts=PTS-STARTPTS[a0_main];",
            f"[0:a]atrim={d0 - transition_duration}:{d0},asetpts=PTS-STARTPTS[a0_tail];",
            f"[1:a]atrim=0:{transition_duration},asetpts=PTS-STARTPTS[a1_head];",
            f"[1:a]atrim={transition_duration}:{d1},asetpts=PTS-STARTPTS[a1_rest];",
            f"[a0_tail][a1_head]acrossfade=d={transition_duration}[a_trans];",
            "[v0_main][v_trans][v1_rest]concat=n=3:v=1:a=0[vout];",
            "[a0_main][a_trans][a1_rest]concat=n=3:v=0:a=1[aout]",
        ]
    elif process_audio and first_has_audio:
        # Only first video has audio
        filter_parts += [
            f"[0:a]atrim=0:{d0 - transition_duration},asetpts=PTS-STARTPTS[a0_main];",
            f"[0:a]atrim={d0 - transition_duration}:{d0},asetpts=PTS-STARTPTS[a0_tail];",
            "[v0_main][v_trans][v1_rest]concat=n=3:v=1:a=0[vout];",
            "[a0_main][a0_tail]concat=n=2:v=0:a=1[aout]",
        ]
    elif process_audio and second_has_audio:
        # Only second video has audio
        filter_parts += [
            f"[1:a]atrim=0:{transition_duration},asetpts=PTS-STARTPTS[a1_head];",
            f"[1:a]atrim={transition_duration}:{d1},asetpts=PTS-STARTPTS[a1_rest];",
            "[v0_main][v_trans][v1_rest]concat=n=3:v=1:a=0[vout];",
            "[a1_head][a1_rest]concat=n=2:v=0:a=1[aout]",
        ]
    else:
        # No audio or external audio will be added later
        filter_parts.append("[v0_main][v_trans][v1_rest]concat=n=3:v=1:a=0[vout]")

    filter_complex = " ".join(filter_parts)
    cmd = [
        ffmpeg_bin,
        "-i",
        inputs[0],
        "-i",
        inputs[1],
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
    ]

    # Only map audio if we're processing it and at least one video has audio
    if process_audio and (first_has_audio or second_has_audio):
        cmd += ["-map", "[aout]"]
        cmd += ["-c:a", acodec]

    # Add encoder and optional GPU flags
    if gpu_args:
        cmd += gpu_args
    cmd += ["-c:v", vcodec, "-y", merge_file]

    result = subprocess_run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

    # Adjust current duration to result length = d0 + d1 - transition
    current_duration = d0 + d1 - transition_duration

    # Subsequent merges
    for idx in range(2, len(inputs)):
        next_file = inputs[idx]
        next_duration = durations[idx]
        temp = f"/tmp/{uuid.uuid4().hex}.{ext}"
        next_has_audio = video_audio_status[next_file]

        parts = [
            f"[0:v]trim=0:{current_duration - transition_duration},setpts=PTS-STARTPTS[vA_main];",
            f"[0:v]trim={current_duration - transition_duration}:{current_duration},setpts=PTS-STARTPTS[vA_tail];",
            f"[1:v]trim=0:{transition_duration},setpts=PTS-STARTPTS[vB_head];",
            f"[1:v]trim={transition_duration}:{next_duration},setpts=PTS-STARTPTS[vB_rest];",
            f"[vA_tail][vB_head]gltransition=duration={transition_duration}:source={transition_path}[v_trans];",
        ]

        # For subsequent merges, assume merged file has audio if we were processing audio before
        merged_has_audio = process_audio

        # Only include audio processing if both the merged file and next file have audio
        include_audio = process_audio and merged_has_audio and next_has_audio

        if include_audio:
            parts += [
                f"[0:a]atrim=0:{current_duration - transition_duration},asetpts=PTS-STARTPTS[aA_main];",
                f"[0:a]atrim={current_duration - transition_duration}:{current_duration},asetpts=PTS-STARTPTS[aA_tail];",
                f"[1:a]atrim=0:{transition_duration},asetpts=PTS-STARTPTS[aB_head];",
                f"[1:a]atrim={transition_duration}:{next_duration},asetpts=PTS-STARTPTS[aB_rest];",
                f"[aA_tail][aB_head]acrossfade=d={transition_duration}[a_trans];",
                "[vA_main][v_trans][vB_rest]concat=n=3:v=1:a=0[vout];",
                "[aA_main][a_trans][aB_rest]concat=n=3:v=0:a=1[aout]",
            ]
        else:
            parts.append("[vA_main][v_trans][vB_rest]concat=n=3:v=1:a=0[vout]")

        filter_complex = " ".join(parts)
        cmd = [
            ffmpeg_bin,
            "-i",
            merge_file,
            "-i",
            next_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
        ]

        # Only map audio if it was included in the filter complex
        if include_audio:
            cmd += ["-map", "[aout]"]
            cmd += ["-c:a", acodec]

        if gpu_args:
            cmd += gpu_args
        cmd += ["-c:v", vcodec, "-y", temp]

        result = subprocess_run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise CalledProcessError(
                result.returncode,
                cmd,
                result.stdout,
                result.stderr,
            )
        os.replace(temp, merge_file)
        # After merging, account for transition overlap
        current_duration += next_duration - transition_duration

    # Overlay external audio if provided
    if audio is not None:
        temp_audio = f"/tmp/{uuid.uuid4().hex}.{ext}"
        cmd = [
            ffmpeg_bin,
            "-i",
            merge_file,
            "-i",
            audio,
            "-map",
            "0:v",
            "-map",
            "1:a",
            *gpu_args,
            "-c:v",
            vcodec,
            "-c:a",
            acodec,
            "-shortest",
            "-y",
            temp_audio,
        ]
        result = subprocess_run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise CalledProcessError(
                result.returncode,
                cmd,
                result.stdout,
                result.stderr,
            )
        os.replace(temp_audio, merge_file)

    return merge_file


@celery.task(name="vidx.tasks.merge_videos")
def merge_videos(
    videos: Dict[str, float],
    audio: str | None,
    video_mime: str,
    video_resolution: tuple[int, int],
    audio_duration: float | None,
    transition: str,
    user_tier: str = "basic",
) -> str:
    """
    Merge videos using the configured execution strategy.

    This task delegates to either AWS Batch (production) or local FFmpeg (development).

    :param videos: List of video paths to merge with their durations.
    :param audio: Path to the audio file.
    :param video_mime: MIME type of the video.
    :param video_resolution: Resolution of the video.
    :param audio_duration: Duration of the audio file.
    :param transition: Transition effect to apply between videos.
    :param user_tier: User tier (basic, premium, enterprise) for resource allocation.
    :return: Output path for the merged video or task ID for tracking.
    """
    import asyncio

    manager = get_execution_manager()

    logger.info(
        f"Submitting merge task: {len(videos)} videos, tier={user_tier}, backend={manager.get_backend_name()}",
    )

    # Create async context to submit task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        task_id = loop.run_until_complete(
            manager.submit_merge_task(
                videos=videos,
                audio=audio,
                video_mime=video_mime,
                video_resolution=video_resolution,
                audio_duration=audio_duration,
                transition=transition,
                user_tier=user_tier,
            ),
        )
        logger.info(f"Task submitted with ID: {task_id}")
        return task_id

    finally:
        loop.close()


# ── Social media scheduling / publishing ─────────────────────────────────────


@celery.task(name="vidx.tasks.publish_due_social_posts")
def publish_due_social_posts() -> int:
    """Publish every Scheduled post whose time has arrived (beat, every minute)."""
    from datetime import datetime, timedelta

    from vidx.db.dao.project_dao import SocialPostDAO
    from vidx.db.models.project import Project
    from vidx.db.models.social_post import PostStatus, SocialPost
    from vidx.services.celery.db import run_with_db
    from vidx.services.social.service import SocialPublishingService

    async def _run() -> int:
        dao = SocialPostDAO()
        now = datetime.utcnow()
        posts = await dao.due_scheduled(now=now)
        service = SocialPublishingService()
        published = 0
        for post in posts:
            stale_before = now - timedelta(minutes=10)
            claim = await SocialPost.get_motor_collection().find_one_and_update(
                {
                    "_id": post.id,
                    "status": PostStatus.SCHEDULED.value,
                    "scheduled_at_utc": {"$lte": now},
                    "$or": [
                        {"claimed_at": None},
                        {"claimed_at": {"$lte": stale_before}},
                    ],
                },
                {"$set": {"claimed_at": now, "updated_at": now}},
            )
            if claim is None:
                continue
            project = await Project.get(post.project_id)
            if project is None:
                post.status = PostStatus.FAILED
                post.error = "Project no longer exists."
                await post.save()
                continue
            await service.publish(post, project)
            published += 1
        return published

    return run_with_db(_run)


@celery.task(name="vidx.tasks.render_scene")
def render_scene_task(scene_id: str) -> str:
    """Render one scene's final video (post-processing + logo + subtitles)."""
    from pathlib import Path

    from beanie import PydanticObjectId

    from vidx.db.dao.project_dao import SceneDAO
    from vidx.db.models.project import ComponentStatus, Project
    from vidx.db.models.scene import Scene
    from vidx.services.celery.db import run_with_db
    from vidx.services.render.ffmpeg_render import render_service
    from vidx.services.storage.factory import get_storage_provider

    async def _run() -> str:
        scene = await Scene.get(PydanticObjectId(scene_id))
        if scene is None:
            return "missing"
        project = await Project.get(scene.project_id)
        if project is None:
            return "missing"

        scene_dao = SceneDAO()
        await scene_dao.update_component(
            scene_id=scene.id,
            component="render",
            fields={
                "status": ComponentStatus.PROCESSING,
                "error": None,
                "submitted_at": scene.render.submitted_at or datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )

        try:
            storage = get_storage_provider()
            if scene.video.status != ComponentStatus.COMPLETED or not scene.video.storage_ref:
                raise RuntimeError("Generated video is not available for rendering.")
            video_path = await storage.materialize(scene.video.storage_ref)
            audio_path = None
            if scene.audio.status == ComponentStatus.COMPLETED and scene.audio.storage_ref:
                audio_path = await storage.materialize(scene.audio.storage_ref)
            subtitle_path = None
            if scene.subtitle.status == ComponentStatus.COMPLETED and scene.subtitle.storage_ref:
                subtitle_path = await storage.materialize(scene.subtitle.storage_ref)
            logo_path = None
            if project.image_ref:
                logo_path = await storage.materialize(project.image_ref)

            options = project.options or {}
            resolution = tuple(options.get("resolution") or (1280, 720))
            output_path = render_service.new_output_path()
            await render_service.render_scene(
                video_path=video_path,
                output_path=output_path,
                audio_path=audio_path,
                subtitle_path=subtitle_path,
                logo_path=logo_path,
                resolution=(int(resolution[0]), int(resolution[1])),
                logo_position=options.get("logo_position", "bottom-right"),
            )
            data = Path(output_path).read_bytes()
            ref = await storage.save_bytes(data, f"scene_{scene.scene_number}_final.mp4")
            await scene_dao.update_component(
                scene_id=scene.id,
                component="render",
                fields={
                    "storage_ref": ref,
                    "status": ComponentStatus.COMPLETED,
                    "error": None,
                    "completed_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            )
            fresh = await scene_dao.get(scene_id=scene.id)
            if fresh is not None:
                fresh.recompute_overall_status()
                await scene_dao.update_fields(
                    scene_id=scene.id,
                    fields={"overall_status": fresh.overall_status},
                )
            return "completed"
        except Exception as exc:
            logger.exception("Scene render failed for %s", scene_id)
            await scene_dao.update_component(
                scene_id=scene.id,
                component="render",
                fields={
                    "status": ComponentStatus.FAILED,
                    "error": str(exc),
                    "updated_at": datetime.utcnow(),
                },
            )
            fresh = await scene_dao.get(scene_id=scene.id)
            if fresh is not None:
                fresh.recompute_overall_status()
                await scene_dao.update_fields(
                    scene_id=scene.id,
                    fields={"overall_status": fresh.overall_status},
                )
            return f"failed: {exc}"

    return run_with_db(_run)


@celery.task(name="vidx.tasks.assemble_project_video")
def assemble_project_video(project_id: str) -> str:
    """Assemble the project's final video from completed scene renders."""
    from pathlib import Path

    from beanie import PydanticObjectId

    from vidx.db.dao.project_dao import ProjectDAO, SceneDAO
    from vidx.db.models.project import ComponentStatus, Project, ProjectStatus
    from vidx.services.celery.db import run_with_db
    from vidx.services.render.ffmpeg_render import render_service
    from vidx.services.storage.factory import get_storage_provider

    async def _run() -> str:
        project = await Project.get(PydanticObjectId(project_id))
        if project is None:
            return "missing"
        scenes = await SceneDAO().list_for_project(project_id=project.id)

        project_dao = ProjectDAO()
        await project_dao.update_final_video(
            project_id=project.id,
            fields={"status": ComponentStatus.PROCESSING, "error": None},
        )
        await project_dao.update_fields(
            project_id=project.id, fields={"status": ProjectStatus.RENDERING},
        )

        try:
            if not scenes:
                raise RuntimeError("Project has no scenes.")
            incomplete = [
                scene.scene_number
                for scene in scenes
                if scene.render.status != ComponentStatus.COMPLETED or not scene.render.storage_ref
            ]
            if incomplete:
                raise RuntimeError(
                    "All scenes must be rendered before the final video: "
                    + ", ".join(str(number) for number in incomplete),
                )
            storage = get_storage_provider()
            paths = [await storage.materialize(scene.render.storage_ref) for scene in scenes]  # type: ignore[arg-type]
            options = project.options or {}
            resolution = tuple(options.get("resolution") or (1280, 720))
            output_path = render_service.new_output_path()
            await render_service.assemble_final(
                scene_paths=paths,
                output_path=output_path,
                resolution=(int(resolution[0]), int(resolution[1])),
            )
            data = Path(output_path).read_bytes()
            ref = await storage.save_bytes(data, "final_video.mp4")
            await project_dao.update_final_video(
                project_id=project.id,
                fields={
                    "storage_ref": ref,
                    "status": ComponentStatus.COMPLETED,
                    "error": None,
                    "completed_at": datetime.utcnow(),
                },
            )
            await project_dao.update_fields(
                project_id=project.id, fields={"status": ProjectStatus.COMPLETED},
            )
            return "completed"
        except Exception as exc:
            logger.exception("Final assembly failed for %s", project_id)
            await project_dao.update_final_video(
                project_id=project.id,
                fields={"status": ComponentStatus.FAILED, "error": str(exc)},
            )
            await project_dao.update_fields(
                project_id=project.id, fields={"status": ProjectStatus.FAILED},
            )
            return f"failed: {exc}"

    return run_with_db(_run)
