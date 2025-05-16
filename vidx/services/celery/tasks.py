import os
import uuid
from subprocess import CalledProcessError
from subprocess import run as subprocess_run
from typing import Dict

from vidx.services.celery.worker import celery


def mime_to_codecs(mime: str) -> tuple[str, str, str]:
    if mime == "video/mp4":
        return "libx264", "aac", "mp4"
    if mime == "video/webm":
        return "libvpx-vp9", "libopus", "webm"
    if mime == "video/ogg":
        return "libtheora", "libvorbis", "ogv"
    raise ValueError(f"Unsupported MIME type: {mime}")


@celery.task(name="vidx.tasks.merge_videos")
def merge_videos(
    videos: Dict[str, float],
    audio: str | None,
    video_mime: str,
    video_resolution: tuple[int, int],
    audio_duration: float | None,
    transition: str,
) -> str:
    """
    Merge videos using ffmpeg.

    :param videos: List of video paths to merge with their durations.
    :param audio: Path to the audio file.
    :param video_mime: MIME type of the video.
    :param video_resolution: Resolution of the video.
    :param audio_duration: Duration of the audio file.
    :param transition: Transition effect to apply between videos.
    :param output_path: Output path for the merged video.
    :return: Output path for the merged video.
    """
    ffmpeg_bin = os.environ.get("FFMPEG_BINARY") or "ffmpeg"
    transition_path = f"{os.path.dirname(ffmpeg_bin)}/{transition}"
    transition_duration = 1.0
    inputs = list(videos.keys())
    durations = list(videos.values())
    transition_duration = 1.0

    # Determine output codec and extension based on mime
    vcodec, acodec, ext = mime_to_codecs(video_mime)

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
