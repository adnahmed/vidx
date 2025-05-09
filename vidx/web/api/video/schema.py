import asyncio
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import List

import ffmpeg
import magic
from fastapi import HTTPException
from pydantic import BaseModel, field_validator
from pydantic_async_validation import AsyncValidationModelMixin, async_field_validator

available_transitions = ["crossfade"]
VALID_VIDEO_MIME_TYPES = ["video/mp4", "video/webm", "video/ogg"]
VALID_AUDIO_MIME_TYPES = ["audio/mpeg", "audio/wav", "audio/ogg"]
MAX_VIDEO_FILES = 10


async def get_video_duration(file_path: str) -> float:
    """
    Get the duration of a video file using ffprobe.

    Args:
        file_path (str): Path to the video file.

    Raises:
        HTTPException: Failed to probe the video file.

    Returns:
        float: duration of the video in seconds
    """
    try:
        probe = await asyncio.to_thread(
            ffmpeg.probe,
            file_path,
            cmd=os.environ["FFPROBE_BINARY"],
            v="error",
            select_streams="v:0",
            show_entries="stream=duration",
            of="json",
        )
        return float(probe["streams"][0]["duration"])
    except ffmpeg.Error as err:
        raise HTTPException(
            status_code=500,
            detail=f"Error probing video: {file_path}",
        ) from err


async def get_audio_duration(file_path: str) -> float:
    """
    Get the duration of an audio file using ffprobe.

    Args:
        file_path (str): Path to the audio file.

    Raises:
        HTTPException: Failed to probe the audio file.

    Returns:
        float: duration of the audio in seconds
    """

    try:
        probe = await asyncio.to_thread(
            ffmpeg.probe,
            file_path,
            cmd=os.environ["FFPROBE_BINARY"],
            v="error",
            select_streams="a:0",
            show_entries="stream=duration",
            of="json",
        )
        return float(probe["streams"][0]["duration"])
    except ffmpeg.Error as err:
        raise HTTPException(
            status_code=500,
            detail=f"Error probing audio: {file_path}",
        ) from err


async def crop_audio_stream(input_path: str, duration: float) -> None:
    """Crop the audio stream to the specified duration.

    Args:
        input_path (str): Path to the input audio file.
        duration (float): Duration to crop the audio stream to, in seconds.

    Raises:
        HTTPException: Failed to crop the audio stream.

    Returns:
        None
    """
    try:
        file_path = Path(input_path)
        extension = file_path.suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
            tmp_path = Path(tmp.name)
            await asyncio.to_thread(
                lambda: (
                    ffmpeg.input(input_path)
                    .output(str(tmp_path), t=duration)
                    .overwrite_output()
                    .run(cmd=os.environ["FFMPEG_BINARY"])
                ),
            )
            tmp_path.replace(input_path)
    except ffmpeg.Error as err:
        raise HTTPException(status_code=500, detail="Error cropping audio") from err


def get_mime_type(file_path: str) -> str:
    """
    Get the MIME type of a file using python-magic.

    Args:
        file_path (str): Path to the file.

    Returns:
        str: MIME type of the file.
    """
    path = Path(file_path)
    with path.open("rb") as f:
        magic_instance = magic.Magic(mime=True)
        return magic_instance.from_buffer(f.read(1024))


class VideoStatus(str, Enum):
    """Enum for video processing status."""

    PAUSED = "PAUSED"
    STARTED = "STARTED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class ValidationErrorCodes(str, Enum):
    """Enum for validation error codes."""

    INVALID_VIDEO_MIME_TYPE = "INVALID_VIDEO_MIME_TYPE"
    INVALID_AUDIO_MIME_TYPE = "INVALID_AUDIO_MIME_TYPE"
    AUDIO_TOO_SHORT = "AUDIO_TOO_SHORT"
    TOO_MANY_VIDEO_FILES = "TOO_MANY_VIDEO_FILES"
    INVALID_TRANSITION = "INVALID_TRANSITION"


class VideoMergeOutputDto(BaseModel):
    """Output DTO for video merge operation."""

    worker_id: str
    status: VideoStatus


class VideoMergeInputDto(AsyncValidationModelMixin, BaseModel):
    """Input DTO for video merge operation."""

    videos: List[str]  # List of file paths
    audio: str  # File path
    transition: str

    @field_validator("transition", mode="before")
    @classmethod
    def validate_transition(cls, value: str) -> str:
        """Validate the transition type.

        Args:
            value (str): Transition type.

        Raises:
            ValueError: If the transition type is not valid.

        Returns:
            str: Validated transition type.
        """
        if value not in available_transitions:
            raise ValueError(
                f"Invalid transition. Must be one of {available_transitions}",
                ValidationErrorCodes.INVALID_TRANSITION,
            )
        return value

    @field_validator("videos", mode="before")
    @classmethod
    def validate_videos(cls, value: List[str]) -> List[str]:
        """Validate the list of video file paths.

        Args:
            value (List[str]): List of video file paths.

        Raises:
            ValueError: If the number of video files exceeds the limit or if the
                        MIME type is invalid.

        Returns:
            List[str]: Validated list of video file paths.
        """
        if len(value) > MAX_VIDEO_FILES:
            raise ValueError(
                f"Too many video files. Max allowed is {MAX_VIDEO_FILES}",
                ValidationErrorCodes.TOO_MANY_VIDEO_FILES,
            )
        for path in value:
            mime = get_mime_type(path)
            if mime not in VALID_VIDEO_MIME_TYPES:
                raise ValueError(
                    f"Invalid video MIME type for file {path}: {mime}",
                    ValidationErrorCodes.INVALID_VIDEO_MIME_TYPE,
                )
        return value

    @async_field_validator("audio")
    async def validate_audio(self) -> str:
        """
        Validate the audio file path.

        Raises:
            ValueError: If the audio file MIME type is invalid or if the audio
                        duration is less than the total video duration.

        Returns:
            str: Validated audio file path.
        """
        audio_path = self.audio
        mime = get_mime_type(audio_path)
        if mime not in VALID_AUDIO_MIME_TYPES:
            raise ValueError(
                f"Invalid audio MIME type: {mime}",
                ValidationErrorCodes.INVALID_AUDIO_MIME_TYPE,
            )

        # Calculate durations
        audio_duration = await get_audio_duration(audio_path)
        total_video_duration = sum(
            await asyncio.gather(*(get_video_duration(p) for p in self.videos)),
        )

        if audio_duration < total_video_duration:
            raise ValueError(
                f"Audio is too short. Must be at least {total_video_duration} seconds",
                ValidationErrorCodes.AUDIO_TOO_SHORT,
            )

        if audio_duration > total_video_duration:
            await crop_audio_stream(audio_path, total_video_duration)

        return audio_path
