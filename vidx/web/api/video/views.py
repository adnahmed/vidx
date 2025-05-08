import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import ValidationError

from vidx.web.api.video.schema import (
    VideoMergeInputDto,
    VideoMergeOutputDto,
    VideoStatus,
)


def save_upload_file_to_temp(upload_file: UploadFile, suffix: str = "") -> str:
    """Save UploadFile to a real file and return the path."""
    filename = upload_file.filename or "default_filename"
    file_path = Path(filename)
    extension = file_path.suffix or suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        shutil.copyfileobj(upload_file.file, tmp)
        return tmp.name


router = APIRouter()


@router.post("/merge", response_model=VideoMergeOutputDto)
async def merge_video(
    videos: List[UploadFile] = File(..., description="List of video files to merge"),
    audio: UploadFile = File(..., description="Audio file to add to the merged video"),
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
    try:
        # Save all uploaded files to disk first
        saved_video_paths = [save_upload_file_to_temp(video) for video in videos]
        saved_audio_path = save_upload_file_to_temp(audio)
        dto = VideoMergeInputDto(
            videos=saved_video_paths,
            audio=saved_audio_path,
            transition=transition,
        )
        await dto.model_async_validate()
        return VideoMergeOutputDto(
            worker_id="12345",  # Replace with actual worker ID
            status=VideoStatus.PENDING,  # Replace with actual status
        )
    except ValidationError as e:
        # Catch the Pydantic ValidationError and format it into a user-friendly response
        error_details = e.errors()

        # Create a formatted error message that includes all validation errors
        formatted_errors = []
        for err in error_details:
            # Customize how each error is represented
            formatted_errors.append(f"Field '{err['loc'][0]}' error: {err['msg']}")

        # Join all the formatted errors into a single string for the response
        error_message = " | ".join(formatted_errors)

        # Return the formatted error message in a user-friendly way
        raise HTTPException(status_code=400, detail=error_message) from e

    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e!s}") from e
