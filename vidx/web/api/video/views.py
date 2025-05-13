import shutil
import tempfile
from pathlib import Path
from typing import List

from celery import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette import status

from vidx.services.celery.tasks import merge_videos
from vidx.services.celery.worker import CeleryWorker
from vidx.web.api.video.schema import (
    Transition,
    VideoMergeInputDto,
    VideoMergeOutputDto,
    VideoStatus,
    get_mime_type,
)


def save_upload_file_to_temp(upload_file: UploadFile, suffix: str = "") -> str:
    """Save UploadFile to a real file and return the path."""
    filename = upload_file.filename or str(uuid.uuid4())
    file_path = Path(filename)
    extension = file_path.suffix or suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        shutil.copyfileobj(upload_file.file, tmp)
        return tmp.name


router = APIRouter()


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
        # check if file exists
        if not task.result or not Path(task.result).exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Merged video file not found.",
            )
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
    videos: List[UploadFile] = File(..., description="List of video files to merge"),
    audio: UploadFile = File(
        default=None,
        description="Audio file to add to the merged video",
    ),
    transition: str = File(..., description="Transition to use between videos"),
) -> VideoMergeOutputDto:
    """
    Merges video files with audio using the specified transition.

    :param videos: A list of video files to merge.
    :param audio: An audio file to add to the merged video.
    :param transition: The transition to use between videos
                    (must be one of available_transitions).
    :returns: The merged video file.
    """
    saved_audio_path = None
    saved_video_paths = []
    try:
        # Save all uploaded files to disk first
        saved_video_paths = [save_upload_file_to_temp(video) for video in videos]
        saved_audio_path = save_upload_file_to_temp(audio) if audio else None
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
            formatted_errors.append(f"Field '{err['loc'][0]}' error: {err['msg']}")
        error_message = " | ".join(formatted_errors)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        ) from e

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {e!s}",
        ) from e
