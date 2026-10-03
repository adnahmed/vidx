"""Project / post / scene API routes."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from starlette import status
from starlette.responses import Response

from vidx.db.dao.project_dao import ProjectDAO, SceneDAO, SocialPostDAO
from vidx.db.models.project import (
    ComponentState,
    ComponentStatus,
    Project,
    ProjectStatus,
    ProjectType,
)
from vidx.db.models.scene import Scene, SceneSource
from vidx.db.models.social_post import PostStatus, SocialPost
from vidx.db.models.user import User
from vidx.services.celery.tasks import (
    assemble_project_video,
    render_scene_task,
)
from vidx.services.excel.importer import parse_scene_workbook
from vidx.services.generation import GenerationError, generation_orchestrator
from vidx.services.providers import GenerationComponent
from vidx.services.social.registry import platform_registry
from vidx.services.social.service import (
    PostValidationError,
    SocialPublishingService,
    is_valid_timezone,
)
from vidx.services.storage.factory import get_storage_provider
from vidx.settings import settings
from vidx.web.api.projects.schema import (
    CalendarDay,
    CalendarOut,
    ComponentStateOut,
    GenerateAllRequest,
    GenerateRequest,
    ImportScenesResult,
    PlatformOut,
    PostOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    SceneOut,
    SceneUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()
posts_router = APIRouter()
scenes_router = APIRouter()
social_router = APIRouter()

MIME_BY_COMPONENT = {
    "image": "image/png",
    "video": "video/mp4",
    "audio": "audio/mpeg",
    "subtitle": "text/plain",
    "render": "video/mp4",
}


def _current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return user


def _parse_object_id(value: str, label: str) -> PydanticObjectId:
    try:
        return PydanticObjectId(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found.",
        ) from exc


def _component_out(state: ComponentState, asset_url: Optional[str] = None) -> ComponentStateOut:
    return ComponentStateOut(
        status=state.status.value if hasattr(state.status, "value") else str(state.status),
        error=state.error,
        provider=state.provider,
        provider_job_id=state.provider_job_id,
        correlation_id=state.correlation_id,
        asset_url=asset_url if state.storage_ref else None,
        attempts=state.attempts,
        submitted_at=state.submitted_at,
        completed_at=state.completed_at,
        updated_at=state.updated_at,
    )


def _project_out(project: Project) -> ProjectOut:
    final_url = (
        f"/api/projects/{project.id}/final-video" if project.final_video.storage_ref else None
    )
    return ProjectOut(
        id=str(project.id),
        project_type=project.project_type.value,
        name=project.name,
        description=project.description,
        platform=project.platform,
        start_date=project.start_date,
        end_date=project.end_date,
        timezone=project.timezone,
        status=project.status.value if hasattr(project.status, "value") else str(project.status),
        image_url=f"/api/projects/{project.id}/image" if project.image_ref else None,
        options=dict(project.options or {}),
        final_video=_component_out(project.final_video, final_url),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _post_out(post: SocialPost) -> PostOut:
    return PostOut(
        id=str(post.id),
        project_id=str(post.project_id),
        platform=post.platform,
        content=post.content,
        image_url=f"/api/posts/{post.id}/image" if post.image_ref else None,
        link=post.link,
        hashtags=list(post.hashtags),
        date=post.date,
        time=post.time,
        timezone=post.timezone,
        scheduled_at_utc=post.scheduled_at_utc,
        status=post.status.value if hasattr(post.status, "value") else str(post.status),
        error=post.error,
        provider_post_id=post.provider_post_id,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _scene_out(scene: Scene) -> SceneOut:
    return SceneOut(
        id=str(scene.id),
        project_id=str(scene.project_id),
        scene_number=scene.scene_number,
        image_prompt=scene.image_prompt,
        scene_prompt=scene.scene_prompt,
        audio_prompt=scene.audio_prompt,
        image=_component_out(scene.image, f"/api/scenes/{scene.id}/assets/image"),
        video=_component_out(scene.video, f"/api/scenes/{scene.id}/assets/video"),
        audio=_component_out(scene.audio, f"/api/scenes/{scene.id}/assets/audio"),
        subtitle=_component_out(scene.subtitle, f"/api/scenes/{scene.id}/assets/subtitle"),
        render=_component_out(scene.render, f"/api/scenes/{scene.id}/assets/render"),
        overall_status=scene.overall_status,
        source=scene.source.value if hasattr(scene.source, "value") else str(scene.source),
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )


async def _load_project(project_id: str, user_id: PydanticObjectId) -> Project:
    project = await ProjectDAO().get_for_user(
        project_id=_parse_object_id(project_id, "Project"), user_id=user_id,
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


async def _store_upload(upload: UploadFile, filename: str) -> str:
    data = await upload.read()
    return await get_storage_provider().save_bytes(data, filename)


async def _serve_ref(ref: str, media_type: Optional[str] = None, filename: Optional[str] = None) -> Response:
    storage = get_storage_provider()
    url = await storage.generate_download_url(ref)
    if url.startswith(("http://", "https://")):
        return RedirectResponse(url)
    path = Path(url)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    return FileResponse(path, media_type=media_type, filename=filename)


def _parse_hashtags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [part.lstrip("#") for part in raw.replace(",", " ").split() if part.strip()]


# ── projects ─────────────────────────────────────────────────────────────────


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    request: Request,
    project_type: Optional[str] = Query(default=None),
) -> List[ProjectOut]:
    user = _current_user(request)
    parsed_type = None
    if project_type:
        try:
            parsed_type = ProjectType(project_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown project type '{project_type}'.",
            ) from exc
    projects = await ProjectDAO().list_for_user(user_id=user.id, project_type=parsed_type)
    return [_project_out(project) for project in projects]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: Request,
    project_type: str = Form(...),
    name: str = Form(...),
    description: Optional[str] = Form(default=None),
    platform: Optional[str] = Form(default=None),
    start_date: Optional[str] = Form(default=None),
    end_date: Optional[str] = Form(default=None),
    timezone: Optional[str] = Form(default=None),
    image: Optional[UploadFile] = File(default=None),
) -> ProjectOut:
    user = _current_user(request)
    try:
        parsed_type = ProjectType(project_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown project type '{project_type}'.",
        ) from exc

    payload = ProjectCreate(
        project_type=parsed_type.value,
        name=name,
        description=description,
        platform=platform,
        start_date=date.fromisoformat(start_date) if start_date else None,
        end_date=date.fromisoformat(end_date) if end_date else None,
        timezone=timezone,
    )

    errors: List[str] = []
    if len(payload.name.strip()) == 0:
        errors.append("Project name is required.")
    if parsed_type == ProjectType.SOCIAL_CAMPAIGN:
        if not payload.platform:
            errors.append("Platform is required for a Social Media Campaign.")
        elif platform_registry.get(payload.platform) is None:
            errors.append(f"Unsupported platform '{payload.platform}'.")
        if not payload.start_date or not payload.end_date:
            errors.append("Start date and end date are required.")
        elif payload.end_date < payload.start_date:
            errors.append("End date cannot precede the start date.")
        if not payload.timezone:
            errors.append("Timezone is required.")
        elif not is_valid_timezone(payload.timezone):
            errors.append(f"Unknown timezone '{payload.timezone}'.")
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" | ".join(errors))

    project = Project(
        user_id=user.id,
        project_type=parsed_type,
        name=payload.name.strip(),
        description=payload.description,
        platform=payload.platform,
        start_date=payload.start_date,
        end_date=payload.end_date,
        timezone=payload.timezone,
        status=ProjectStatus.ACTIVE,
        options={
            "resolution": [1280, 720],
            "logo_position": "bottom-right",
        },
    )
    if image is not None and image.filename:
        project.image_ref = await _store_upload(image, image.filename)
    await project.insert()
    return _project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, request: Request) -> ProjectOut:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    return _project_out(project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str, payload: ProjectUpdate, request: Request,
) -> ProjectOut:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)

    if payload.name is not None:
        project.name = payload.name.strip()
    if payload.description is not None:
        project.description = payload.description
    if payload.timezone is not None:
        if not is_valid_timezone(payload.timezone):
            raise HTTPException(status_code=400, detail=f"Unknown timezone '{payload.timezone}'.")
        project.timezone = payload.timezone
    if payload.start_date is not None:
        project.start_date = payload.start_date
    if payload.end_date is not None:
        project.end_date = payload.end_date
    if payload.options is not None:
        project.options = payload.options
    if project.start_date and project.end_date and project.end_date < project.start_date:
        raise HTTPException(status_code=400, detail="End date cannot precede the start date.")

    await project.save()
    return _project_out(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_project(project_id: str, request: Request) -> None:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    await SocialPostDAO().delete_for_project(project_id=project.id)
    await SceneDAO().delete_for_project(project_id=project.id)
    await project.delete()


@router.post("/{project_id}/image", response_model=ProjectOut)
async def upload_project_image(
    project_id: str, request: Request, image: UploadFile = File(...),
) -> ProjectOut:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    project.image_ref = await _store_upload(image, image.filename or "project-image")
    await project.save()
    return _project_out(project)


@router.get("/{project_id}/image")
async def get_project_image(project_id: str, request: Request) -> Response:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    if not project.image_ref:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No project image.")
    return await _serve_ref(project.image_ref)


@router.get("/{project_id}/final-video")
async def get_project_final_video(project_id: str, request: Request) -> Response:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    if not project.final_video.storage_ref:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No final video.")
    return await _serve_ref(project.final_video.storage_ref, media_type="video/mp4")


# ── campaign calendar + posts ────────────────────────────────────────────────


@router.get("/{project_id}/calendar", response_model=CalendarOut)
async def get_calendar(
    project_id: str,
    request: Request,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
) -> CalendarOut:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    if project.project_type != ProjectType.SOCIAL_CAMPAIGN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calendar is only available for Social Media Campaign projects.",
        )
    posts = await SocialPostDAO().list_for_project(project_id=project.id)

    counts: dict[date, int] = {}
    for post in posts:
        counts[post.date] = counts.get(post.date, 0) + 1

    range_start = date.fromisoformat(from_date) if from_date else project.start_date
    range_end = date.fromisoformat(to_date) if to_date else project.end_date
    days: List[CalendarDay] = []
    if range_start and range_end:
        current = range_start
        while current <= range_end:
            days.append(CalendarDay(date=current, count=counts.get(current, 0)))
            current = date.fromordinal(current.toordinal() + 1)

    return CalendarOut(
        project=_project_out(project),
        days=days,
        posts=[_post_out(post) for post in posts],
    )


@router.get("/{project_id}/posts", response_model=List[PostOut])
async def list_posts(
    project_id: str,
    request: Request,
    day: Optional[str] = Query(default=None, alias="date"),
) -> List[PostOut]:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    parsed_day = date.fromisoformat(day) if day else None
    posts = await SocialPostDAO().list_for_project(
        project_id=project.id, day=parsed_day,
    )
    return [_post_out(post) for post in posts]


@router.post(
    "/{project_id}/posts", response_model=PostOut, status_code=status.HTTP_201_CREATED,
)
async def create_post(
    project_id: str,
    request: Request,
    content: str = Form(...),
    post_date: str = Form(..., alias="date"),
    post_time: str = Form(..., alias="time"),
    timezone_name: str = Form(..., alias="timezone"),
    link: Optional[str] = Form(default=None),
    hashtags: Optional[str] = Form(default=None),
    post_status: str = Form(default=PostStatus.DRAFT.value, alias="status"),
    use_project_image: bool = Form(default=False),
    image: Optional[UploadFile] = File(default=None),
) -> PostOut:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    if project.project_type != ProjectType.SOCIAL_CAMPAIGN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Posts can only be added to Social Media Campaign projects.",
        )

    try:
        parsed_date = date.fromisoformat(post_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD.") from exc
    try:
        parsed_status = PostStatus(post_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Status must be one of Draft, Scheduled, Published, Failed.",
        ) from exc

    parsed_hashtags = _parse_hashtags(hashtags)
    service = SocialPublishingService()
    try:
        service.validate_fields(
            project=project,
            platform=project.platform or "",
            content=content,
            day=parsed_date,
            time_str=post_time,
            timezone_name=timezone_name,
            link=link,
            hashtags=parsed_hashtags,
            status=parsed_status,
        )
    except PostValidationError as exc:
        raise HTTPException(status_code=400, detail=" | ".join(exc.errors)) from exc

    scheduled_at = service.build_scheduled_at(
        day=parsed_date, time_str=post_time, timezone_name=timezone_name,
    )
    post = SocialPost(
        project_id=project.id,
        user_id=user.id,
        platform=project.platform or "",
        content=content,
        link=link or None,
        hashtags=parsed_hashtags,
        date=parsed_date,
        time=post_time,
        timezone=timezone_name,
        scheduled_at_utc=scheduled_at,
        status=parsed_status,
    )
    if image is not None and image.filename:
        post.image_ref = await _store_upload(image, image.filename)
    elif use_project_image:
        post.image_ref = project.image_ref
    await post.insert()
    return _post_out(post)


# ── posts router ─────────────────────────────────────────────────────────────


async def _load_post(post_id: str, user_id: PydanticObjectId) -> SocialPost:
    post = await SocialPostDAO().get_for_user(
        post_id=_parse_object_id(post_id, "Post"), user_id=user_id,
    )
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return post


@posts_router.put("/{post_id}", response_model=PostOut)
async def update_post(
    post_id: str,
    request: Request,
    content: str = Form(...),
    post_date: str = Form(..., alias="date"),
    post_time: str = Form(..., alias="time"),
    timezone_name: str = Form(..., alias="timezone"),
    link: Optional[str] = Form(default=None),
    hashtags: Optional[str] = Form(default=None),
    post_status: str = Form(default=PostStatus.DRAFT.value, alias="status"),
    use_project_image: bool = Form(default=False),
    image: Optional[UploadFile] = File(default=None),
) -> PostOut:
    user = _current_user(request)
    post = await _load_post(post_id, user.id)
    project = await ProjectDAO().get_for_user(project_id=post.project_id, user_id=user.id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    try:
        parsed_date = date.fromisoformat(post_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD.") from exc
    try:
        parsed_status = PostStatus(post_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Status must be one of Draft, Scheduled, Published, Failed.",
        ) from exc

    parsed_hashtags = _parse_hashtags(hashtags)
    service = SocialPublishingService()
    try:
        service.validate_fields(
            project=project,
            platform=post.platform,
            content=content,
            day=parsed_date,
            time_str=post_time,
            timezone_name=timezone_name,
            link=link,
            hashtags=parsed_hashtags,
            status=parsed_status,
        )
    except PostValidationError as exc:
        raise HTTPException(status_code=400, detail=" | ".join(exc.errors)) from exc

    post.content = content
    post.date = parsed_date
    post.time = post_time
    post.timezone = timezone_name
    post.link = link or None
    post.hashtags = parsed_hashtags
    post.status = parsed_status
    post.error = None if parsed_status != PostStatus.FAILED else post.error
    post.scheduled_at_utc = service.build_scheduled_at(
        day=parsed_date, time_str=post_time, timezone_name=timezone_name,
    )
    post.claimed_at = None
    if image is not None and image.filename:
        post.image_ref = await _store_upload(image, image.filename)
    elif use_project_image:
        post.image_ref = project.image_ref
    await post.save()
    return _post_out(post)


@posts_router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_post(post_id: str, request: Request) -> None:
    user = _current_user(request)
    post = await _load_post(post_id, user.id)
    await post.delete()


@posts_router.get("/{post_id}/image")
async def get_post_image(post_id: str, request: Request) -> Response:
    user = _current_user(request)
    post = await _load_post(post_id, user.id)
    if not post.image_ref:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No post image.")
    return await _serve_ref(post.image_ref)


@posts_router.post("/{post_id}/publish", response_model=PostOut)
async def publish_post(post_id: str, request: Request) -> PostOut:
    user = _current_user(request)
    post = await _load_post(post_id, user.id)
    project = await ProjectDAO().get_for_user(project_id=post.project_id, user_id=user.id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    service = SocialPublishingService()
    await service.publish(post, project)
    return _post_out(post)


# ── video production: scenes ─────────────────────────────────────────────────


@router.post("/{project_id}/import-scenes", response_model=ImportScenesResult)
async def import_scenes(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    mode: str = Query(default="replace", pattern="^(replace|append)$"),
) -> ImportScenesResult:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    if project.project_type != ProjectType.VIDEO_PRODUCTION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Excel import is only available for Video Production projects.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    result = parse_scene_workbook(data)
    if result.errors:
        raise HTTPException(status_code=400, detail=" | ".join(result.errors))
    if not result.rows:
        raise HTTPException(status_code=400, detail="No scene rows found in the workbook.")

    scene_dao = SceneDAO()
    existing = await scene_dao.list_for_project(project_id=project.id)

    if mode == "replace":
        has_generated = any(
            scene.image.storage_ref
            or scene.video.storage_ref
            or scene.audio.storage_ref
            or scene.render.storage_ref
            for scene in existing
        )
        if has_generated:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Existing scenes already have generated assets. Use append mode "
                    "or remove the generated scenes explicitly before replacing."
                ),
            )
        await scene_dao.delete_for_project(project_id=project.id)
        next_number = 1
    else:
        next_number = await scene_dao.next_scene_number(project_id=project.id)

    scenes: List[Scene] = []
    for row in result.rows:
        scenes.append(
            Scene(
                project_id=project.id,
                scene_number=next_number,
                image_prompt=row.image_prompt,
                scene_prompt=row.scene_prompt,
                audio_prompt=row.audio_prompt,
                source=SceneSource.EXCEL_IMPORT,
            ),
        )
        next_number += 1

    await scene_dao.create_many(scenes)
    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.ACTIVE
        await project.save()
    return ImportScenesResult(imported=len(scenes), mode=mode, errors=[])


@router.get("/{project_id}/scenes", response_model=List[SceneOut])
async def list_scenes(project_id: str, request: Request) -> List[SceneOut]:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    scenes = await SceneDAO().list_for_project(project_id=project.id)
    return [_scene_out(scene) for scene in scenes]


@router.post("/{project_id}/generate-all", response_model=List[SceneOut])
async def generate_all(
    project_id: str, payload: GenerateAllRequest, request: Request,
) -> List[SceneOut]:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    scenes = await SceneDAO().list_for_project(project_id=project.id)
    results: List[Scene] = []
    for scene in scenes:
        current = scene
        for component_name in payload.components:
            try:
                component = GenerationComponent(component_name)
            except ValueError:
                continue
            try:
                current = await generation_orchestrator.submit_component(
                    current, project, component, force=payload.force,
                )
            except GenerationError:
                # Skip components whose preconditions are not met yet (e.g.
                # video before image); the UI surfaces per-component status.
                continue
        results.append(current)
    return [_scene_out(scene) for scene in results]


@router.post("/{project_id}/render", response_model=ProjectOut)
async def render_project(project_id: str, request: Request) -> ProjectOut:
    user = _current_user(request)
    project = await _load_project(project_id, user.id)
    scenes = await SceneDAO().list_for_project(project_id=project.id)
    if not scenes:
        raise HTTPException(status_code=400, detail="Project has no scenes to render.")
    incomplete = [
        scene.scene_number
        for scene in scenes
        if scene.render.status != ComponentStatus.COMPLETED or not scene.render.storage_ref
    ]
    if incomplete:
        raise HTTPException(
            status_code=400,
            detail="All scenes must be rendered before assembling the final video: "
            + ", ".join(str(number) for number in incomplete),
        )
    project.final_video.status = ComponentStatus.QUEUED
    project.final_video.error = None
    project.status = ProjectStatus.RENDERING
    await project.save()
    assemble_project_video.delay(str(project.id))
    return _project_out(project)


# ── scenes router ────────────────────────────────────────────────────────────


async def _load_scene(scene_id: str, user_id: PydanticObjectId) -> tuple[Scene, Project]:
    scene = await SceneDAO().get(scene_id=_parse_object_id(scene_id, "Scene"))
    if scene is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found.")
    project = await ProjectDAO().get_for_user(project_id=scene.project_id, user_id=user_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found.")
    return scene, project


@scenes_router.get("/{scene_id}", response_model=SceneOut)
async def get_scene(scene_id: str, request: Request) -> SceneOut:
    user = _current_user(request)
    scene, _ = await _load_scene(scene_id, user.id)
    return _scene_out(scene)


@scenes_router.patch("/{scene_id}", response_model=SceneOut)
async def update_scene(scene_id: str, payload: SceneUpdate, request: Request) -> SceneOut:
    user = _current_user(request)
    scene, _ = await _load_scene(scene_id, user.id)
    fields: dict = {}
    if payload.image_prompt is not None:
        fields["image_prompt"] = payload.image_prompt
    if payload.scene_prompt is not None:
        fields["scene_prompt"] = payload.scene_prompt
    if payload.audio_prompt is not None:
        fields["audio_prompt"] = payload.audio_prompt
    if fields:
        fields["updated_at"] = datetime.utcnow()
        # Atomic prompt-only update so concurrent component callbacks are not
        # clobbered by a full-document save.
        await SceneDAO().update_fields(scene_id=scene.id, fields=fields)
        await scene.sync()
    return _scene_out(scene)


@scenes_router.delete("/{scene_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_scene(scene_id: str, request: Request) -> None:
    user = _current_user(request)
    scene, _ = await _load_scene(scene_id, user.id)
    await scene.delete()


@scenes_router.post("/{scene_id}/generate", response_model=SceneOut)
async def generate_scene_component(
    scene_id: str, payload: GenerateRequest, request: Request,
) -> SceneOut:
    user = _current_user(request)
    scene, project = await _load_scene(scene_id, user.id)
    try:
        component = GenerationComponent(payload.component)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Component must be one of image, video, audio, subtitle.",
        ) from exc
    try:
        scene = await generation_orchestrator.submit_component(
            scene, project, component, force=payload.force,
        )
    except GenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _scene_out(scene)


@scenes_router.post("/{scene_id}/render", response_model=SceneOut)
async def render_scene(scene_id: str, request: Request) -> SceneOut:
    user = _current_user(request)
    scene, _ = await _load_scene(scene_id, user.id)
    if scene.video.status != ComponentStatus.COMPLETED or not scene.video.storage_ref:
        raise HTTPException(
            status_code=400,
            detail="Generated video must be completed before rendering the scene.",
        )
    scene.render.status = ComponentStatus.QUEUED
    scene.render.error = None
    await scene.save()
    render_scene_task.delay(str(scene.id))
    return _scene_out(scene)


@scenes_router.get("/{scene_id}/assets/{component}")
async def get_scene_asset(scene_id: str, component: str, request: Request) -> Response:
    user = _current_user(request)
    scene, _ = await _load_scene(scene_id, user.id)
    if component not in MIME_BY_COMPONENT:
        raise HTTPException(status_code=404, detail="Unknown asset component.")
    state = getattr(scene, component)
    if not state.storage_ref:
        raise HTTPException(status_code=404, detail="Asset is not available.")
    suffix = Path(state.storage_ref).suffix or ""
    filename = f"scene_{scene.scene_number}_{component}{suffix}"
    return await _serve_ref(state.storage_ref, media_type=MIME_BY_COMPONENT[component], filename=filename)


# ── social helpers ───────────────────────────────────────────────────────────


@social_router.get("/platforms", response_model=List[PlatformOut])
async def list_platforms() -> List[PlatformOut]:
    return [
        PlatformOut(
            platform=cap.platform,
            label=cap.label,
            availability=cap.availability.value,
            max_content_length=cap.max_content_length,
            max_hashtags=cap.max_hashtags,
            supports_images=cap.supports_images,
            supports_links=cap.supports_links,
            supports_scheduling=cap.supports_scheduling,
            notes=cap.notes,
        )
        for cap in platform_registry.list_capabilities()
    ]


@social_router.post("/scheduler/run")
async def run_scheduler(request: Request) -> dict:
    """Manually trigger due-post publishing (used by cron/verification)."""
    token = request.headers.get("X-Scheduler-Token")
    if settings.scheduler_token:
        if token != settings.scheduler_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid scheduler token.")
    elif settings.environment.lower() not in {"dev", "pytest", "test"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler token is not configured.",
        )

    now = datetime.utcnow()
    posts = await SocialPostDAO().due_scheduled(now=now)
    service = SocialPublishingService()
    published = 0
    for post in posts:
        project = await Project.get(post.project_id)
        if project is None:
            continue
        await service.publish(post, project)
        published += 1
    return {"due": len(posts), "processed": published}
