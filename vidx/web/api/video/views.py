
import mimetypes
import shutil
import tempfile
import uuid as std_uuid
from pathlib import Path
from typing import IO, List, Union

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError
from starlette import status

from vidx.db.dao.merge_history_dao import MergeHistoryDAO
from vidx.services.celery.tasks import merge_videos
from vidx.services.celery.worker import CeleryWorker
from vidx.services.storage.base import StorageProvider
from vidx.services.storage.local import LocalStorageStrategy
from vidx.services.storage.s3 import AWSS3Strategy
from vidx.settings import settings
from vidx.web.api.video.schema import (
    MergeHistoryItem,
    Transition,
    VideoMergeInputDto,
    VideoMergeOutputDto,
    VideoStatus,
    get_mime_type,
)


def _resolve_submitted_name(upload: Union[UploadFile, str]) -> str:
    if isinstance(upload, UploadFile):
        return upload.filename or "uploaded-file"
    try:
        parsed = httpx.URL(upload)
    except httpx.InvalidURL:
        return upload
    name = Path(parsed.path).name
    return name or upload


def _get_storage_provider() -> StorageProvider:
    if settings.storage_type.lower() == "s3":
        return AWSS3Strategy()
    return LocalStorageStrategy()


async def save_upload_file_to_temp(upload_file: Union[UploadFile, str], suffix: str = "") -> str:
    """
    Save UploadFile or URL to storage and return a location string.

    For local storage, a temp file path is returned.
    For S3 storage, a pre-signed URL is returned to be consumed by ffmpeg directly.
    """
    provider = _get_storage_provider()
    return await provider.save_upload(upload_file)


router = APIRouter()


def get_merge_history_dao() -> MergeHistoryDAO:
    return MergeHistoryDAO()


@router.get("/merge", response_class=FileResponse)
async def get_merged_video(
    task_id: str,
    worker: CeleryWorker = Depends(CeleryWorker),
) -> FileResponse:
    """

    Get the merged video file.
    :param task_id: The ID of the task processing the video merge.
    :param worker: The Celery worker instance.
    :return: The merged video file.

    """
    try:
        task = worker.get_task_result(task_id)
        if not task.result or not Path(task.result).exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Merged video file not found.",
            )
        # If using S3 storage, upload the merged file to S3 and redirect to a pre-signed URL
        if settings.storage_type.lower() == "s3":
            provider = _get_storage_provider()
            # When given a local path, upload to S3 and get a pre-signed URL
            # Reuse the S3 strategy's upload by reading the file
            # (Simple implementation: read and put_object)
            from vidx.services.storage.s3 import AWSS3Strategy  # type: ignore

            s3 = AWSS3Strategy()
            # Upload and get URL
            key = f"outputs/{Path(task.result).name}"
            with open(task.result, "rb") as fh:
                s3._s3.put_object(Bucket=s3._bucket, Key=key, Body=fh.read())
            url = s3.generate_download_url_sync(key)
            return RedirectResponse(url)

        media_type = get_mime_type(task.result)
        return FileResponse(task.result, media_type=media_type)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {e!s}",
        ) from e


@router.get(
    "/merge/status",
    response_model=VideoStatus,
    status_code=status.HTTP_200_OK,
)
async def get_merge_status(
    task_id: str,
    worker: CeleryWorker = Depends(CeleryWorker),
) -> VideoStatus:
    """

    Get the status of a video merge task.
    :param task_id: The ID of the task processing the video merge.
    :return: The status of the video merge task.

    """
    try:
        return VideoStatus(worker.get_task_status(task_id))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {e!s}",
        ) from e


@router.post(
    "/merge",
    response_model=VideoMergeOutputDto,
    status_code=status.HTTP_202_ACCEPTED,
)
async def merge_video(
    request: Request,
    videos: List[Union[UploadFile, str]] = File(
        ...,
        description="List of video files (UploadFile or URL string) to merge",
    ),
    audio: Union[UploadFile, str] = File(
        default=None,
        description="Audio file (UploadFile or URL string) to add to the merged video",
    ),
    transition: str = File(..., description="Transition to use between videos"),
    history_dao: MergeHistoryDAO = Depends(get_merge_history_dao),
) -> VideoMergeOutputDto:
    """
    Merges video files with audio using the specified transition.

    :param videos: A list of video files (or URLs) to merge.
    :param audio: An audio file (or URL) to add to the merged video.
    :param transition: The transition to use between videos
                    (must be one of available_transitions).
    :returns: The merged video file.
    """
    saved_audio_path = None
    saved_video_paths: List[str] = []
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    submitted_video_names = [_resolve_submitted_name(video) for video in videos]
    submitted_audio_name = _resolve_submitted_name(audio) if audio else None

    try:
        saved_video_paths = [await save_upload_file_to_temp(video) for video in videos]
        saved_audio_path = await save_upload_file_to_temp(audio) if audio else None
        dto = VideoMergeInputDto(
            videos=saved_video_paths,
            audio=saved_audio_path,
            transition=transition,
        )
        await dto.model_async_validate()

        task = merge_videos.delay(
            dto.video_durations,
            dto.audio,
            dto.video_type,
            dto.video_resolution,
            dto.audio_duration,
            Transition[dto.transition].value,
        )

        await history_dao.create_history(
            user_id=user.id,
            task_id=task.id,
            videos=submitted_video_names,
            audio=submitted_audio_name,
            transition=dto.transition,
        )

        return VideoMergeOutputDto(
            task_id=task.id,
            status=task.status,
        )

    except ValidationError as e:

        if saved_audio_path and Path(saved_audio_path).exists():
            Path(saved_audio_path).unlink()
        for video_path in saved_video_paths:
            if Path(video_path).exists():
                Path(video_path).unlink()
        error_details = e.errors()
        formatted_errors = []
        for err in error_details:
            field_name = err["loc"][0] if err["loc"] else "unknown_field"
            formatted_errors.append(f"Field '{field_name}' error: {err['msg']}")
        error_message = " | ".join(formatted_errors)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        ) from e

    except Exception as e:
        if saved_audio_path and Path(saved_audio_path).exists():
            Path(saved_audio_path).unlink()
        for video_path in saved_video_paths:
            if Path(video_path).exists():
                Path(video_path).unlink()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {e!s}",
        ) from e


@router.get(
    "/history",
    response_model=List[MergeHistoryItem],
    status_code=status.HTTP_200_OK,
)
async def get_merge_history(
    request: Request,
    history_dao: MergeHistoryDAO = Depends(get_merge_history_dao),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> List[MergeHistoryItem]:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    entries = await history_dao.list_for_user(
        user_id=user.id,
        limit=limit,
        offset=offset,
    )
    return [
        MergeHistoryItem(
            task_id=entry.task_id,
            created_at=entry.created_at,
            videos=entry.videos,
            audio=entry.audio,
            transition=entry.transition,
        )
        for entry in entries
    ]
