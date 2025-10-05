import asyncio
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Tuple

import ffmpeg
import magic
from celery import states
from fastapi import HTTPException
from pydantic import BaseModel, field_validator
from pydantic_async_validation import AsyncValidationModelMixin, async_field_validator

from vidx.settings import settings




class MergeHistoryItem(BaseModel):
    task_id: str
    created_at: datetime
    videos: list[str]
    audio: str | None = None
    transition: str

class Transition(Enum):
    """Enum for video transitions."""

    DISSOLVE = "dissolve.glsl"
    BOOK_FLIP = "BookFlip.glsl"
    BOUNCE = "Bounce.glsl"
    BOW_TIE_HORIZONTAL = "BowTieHorizontal.glsl"
    BOW_TIE_VERTICAL = "BowTieVertical.glsl"
    BOW_TIE_WITH_PARAMETER = "BowTieWithParameter.glsl"
    BUTTERFLY_WAVE_SCRAWLER = "ButterflyWaveScrawler.glsl"
    CIRCLE_CROP = "CircleCrop.glsl"
    COLOUR_DISTANCE = "ColourDistance.glsl"
    CRAZY_PARAMETRIC_FUN = "CrazyParametricFun.glsl"
    CROSS_ZOOM = "CrossZoom.glsl"
    DIRECTIONAL = "Directional.glsl"
    DIRECTIONAL_SCALED = "DirectionalScaled.glsl"
    DOOM_SCREEN_TRANSITION = "DoomScreenTransition.glsl"
    DREAMY = "Dreamy.glsl"
    DREAMY_ZOOM = "DreamyZoom.glsl"
    EDGE_TRANSITION = "EdgeTransition.glsl"
    FILM_BURN = "FilmBurn.glsl"
    GLITCH_DISPLACE = "GlitchDisplace.glsl"
    GLITCH_MEMORIES = "GlitchMemories.glsl"
    GRID_FLIP = "GridFlip.glsl"
    HORIZONTAL_CLOSE = "HorizontalClose.glsl"
    HORIZONTAL_OPEN = "HorizontalOpen.glsl"
    INVERTED_PAGE_CURL = "InvertedPageCurl.glsl"
    LEFT_RIGHT = "LeftRight.glsl"
    LINEAR_BLUR = "LinearBlur.glsl"
    MOSAIC = "Mosaic.glsl"
    OVEREXPOSURE = "Overexposure.glsl"
    POLKA_DOTS_CURTAIN = "PolkaDotsCurtain.glsl"
    RADIAL = "Radial.glsl"
    RECTANGLE = "Rectangle.glsl"
    RECTANGLE_CROP = "RectangleCrop.glsl"
    ROLLS = "Rolls.glsl"
    ROTATE_SCALE_VANISH = "RotateScaleVanish.glsl"
    SIMPLE_ZOOM = "SimpleZoom.glsl"
    SIMPLE_ZOOM_OUT = "SimpleZoomOut.glsl"
    SLIDES = "Slides.glsl"
    STATIC_FADE = "StaticFade.glsl"
    STEREO_VIEWER = "StereoViewer.glsl"
    SWIRL = "Swirl.glsl"
    TV_STATIC = "TVStatic.glsl"
    TOP_BOTTOM = "TopBottom.glsl"
    VERTICAL_CLOSE = "VerticalClose.glsl"
    VERTICAL_OPEN = "VerticalOpen.glsl"
    WATER_DROP = "WaterDrop.glsl"
    ZOOM_IN_CIRCLES = "ZoomInCircles.glsl"
    ZOOM_LEFT_WIPE = "ZoomLeftWipe.glsl"
    ZOOM_RIGHT_WIPE = "ZoomRightWipe.glsl"
    ANGULAR = "angular.glsl"
    BURN = "burn.glsl"
    CANNABIS_LEAF = "cannabisleaf.glsl"
    CIRCLE = "circle.glsl"
    CIRCLE_OPEN = "circleopen.glsl"
    COLOR_PHASE = "colorphase.glsl"
    COORD_FROM_IN = "coord-from-in.glsl"
    CROSSHATCH = "crosshatch.glsl"
    CROSSWARP = "crosswarp.glsl"
    CUBE = "cube.glsl"
    DIRECTIONAL_EASING = "directional-easing.glsl"
    DIRECTIONAL_WARP = "directionalwarp.glsl"
    DIRECTIONAL_WIPE = "directionalwipe.glsl"
    DISPLACEMENT = "displacement.glsl"
    DOORWAY = "doorway.glsl"
    FADE = "fade.glsl"
    FADECOLOR = "fadecolor.glsl"
    FADE_GRAYSCALE = "fadegrayscale.glsl"
    FLYEYE = "flyeye.glsl"
    HEART = "heart.glsl"
    HEXAGONALIZE = "hexagonalize.glsl"
    KALEIDOSCOPE = "kaleidoscope.glsl"
    LUMA = "luma.glsl"
    LUMINANCE_MELT = "luminance_melt.glsl"
    MORPH = "morph.glsl"
    MOSAIC_TRANSITION = "mosaic_transition.glsl"
    MULTIPLY_BLEND = "multiply_blend.glsl"
    PERLIN = "perlin.glsl"
    PINWHEEL = "pinwheel.glsl"
    PIXELIZE = "pixelize.glsl"
    POLAR_FUNCTION = "polar_function.glsl"
    POWER_KALEIDO = "powerKaleido.glsl"
    RANDOM_NOISE_X = "randomNoisex.glsl"
    RANDOM_SQUARES = "randomsquares.glsl"
    RIPPLE = "ripple.glsl"
    ROTATE_TRANSITION = "rotateTransition.glsl"
    ROTATE_SCALE_FADE = "rotate_scale_fade.glsl"
    SCALE_IN = "scale-in.glsl"
    SQUARESWIRE = "squareswire.glsl"
    SQUEEZE = "squeeze.glsl"
    STATIC_WIPE = "static_wipe.glsl"
    SWAP = "swap.glsl"
    TANGENT_MOTION_BLUR = "tangentMotionBlur.glsl"
    UNDULATING_BURN_OUT = "undulatingBurnOut.glsl"
    WIND = "wind.glsl"
    WINDOW_BLINDS = "windowblinds.glsl"
    WINDOWS_LICE = "windowslice.glsl"
    WIPE_DOWN = "wipeDown.glsl"
    WIPE_LEFT = "wipeLeft.glsl"
    WIPE_RIGHT = "wipeRight.glsl"
    WIPE_UP = "wipeUp.glsl"
    X_AXIS_TRANSLATION = "x_axis_translation.glsl"


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
            cmd=settings.ffprobe,
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


async def get_video_info(file_path: str) -> Tuple[str, Tuple[int, int]]:
    """
    Get the MIME type and resolution of a video file using ffprobe.

    Args:
        file_path (str): Path to the video file.

    Raises:
        HTTPException: Failed to probe the video file.

    Returns:
        Tuple[str, Tuple[int, int]]: MIME type and resolution (width, height) of the video.
    """
    try:
        probe = await asyncio.to_thread(
            ffmpeg.probe,
            file_path,
            cmd=settings.ffprobe,
            v="error",
            select_streams="v:0",
            show_entries="stream=width,height",
            of="json",
        )
        width = probe["streams"][0]["width"]
        height = probe["streams"][0]["height"]
        mime = get_mime_type(file_path)
        return mime, (width, height)
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
            cmd=settings.ffprobe,
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
                    .run(cmd=settings.ffmpeg)
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
    magic_instance = magic.Magic(mime=True)
    return magic_instance.from_file(file_path)


class ValidationErrorCodes(str, Enum):
    """Enum for validation error codes."""

    INVALID_VIDEO_MIME_TYPE = "INVALID_VIDEO_MIME_TYPE"
    INVALID_AUDIO_MIME_TYPE = "INVALID_AUDIO_MIME_TYPE"
    AUDIO_TOO_SHORT = "AUDIO_TOO_SHORT"
    TOO_MANY_VIDEO_FILES = "TOO_MANY_VIDEO_FILES"
    TOO_LESS_VIDEO_FILES = "TOO_LESS_VIDEO_FILES"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    DIFFERENT_VIDEO_TYPE = "DIFFERENT_VIDEO_TYPE"
    DIFFERENT_VIDEO_RESOLUTION = "DIFFERENT_VIDEO_RESOLUTION"


class VideoStatus(str, Enum):
    """Enum for video processing status using Celery states."""

    PENDING = states.PENDING
    STARTED = states.STARTED
    SUCCESS = states.SUCCESS
    FAILURE = states.FAILURE
    RETRY = states.RETRY
    REVOKED = states.REVOKED


class VideoMergeOutputDto(BaseModel):
    """Output DTO for video merge operation."""

    task_id: str
    status: VideoStatus


class VideoMergeInputDto(AsyncValidationModelMixin, BaseModel):
    """Input DTO for video merge operation."""

    videos: List[str]
    audio: str | None
    transition: str
    video_durations: Dict[str, float] = {}
    audio_duration: float | None = None
    video_type: str | None = None
    video_resolution: Tuple[int, int] | None = None

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
        try:
            Transition[value.upper()]
        except KeyError as err:
            raise ValueError(
                f"Invalid transition. Must be one of {[e.name for e in Transition]}",
                ValidationErrorCodes.INVALID_TRANSITION,
            ) from err
        return value.upper()

    @async_field_validator("videos")
    async def validate_videos(self) -> List[str]:
        """Validate the list of video file paths.

        Args:
            value (List[str]): List of video file paths.

        Raises:
            ValueError: If the number of video files exceeds the limit or if the
                        MIME type is invalid.

        Returns:
            List[str]: Validated list of video file paths.
        """
        videos = self.videos
        if len(videos) < 2:
            raise ValueError(
                "At least two video files are required",
                ValidationErrorCodes.TOO_LESS_VIDEO_FILES,
            )

        if len(videos) > MAX_VIDEO_FILES:
            raise ValueError(
                f"Too many video files. Max allowed is {MAX_VIDEO_FILES}",
                ValidationErrorCodes.TOO_MANY_VIDEO_FILES,
            )

        first_video_mime = None
        first_video_resolution = None

        for path in videos:
            mime, resolution = await get_video_info(path)

            if first_video_mime is None:
                first_video_mime = mime
                first_video_resolution = resolution
            else:
                if mime != first_video_mime:
                    raise ValueError(
                        f"All videos must have the same MIME type. Expected {first_video_mime}, but got {mime}",
                        ValidationErrorCodes.DIFFERENT_VIDEO_TYPE,
                    )
                if resolution != first_video_resolution:
                    raise ValueError(
                        f"All videos must have the same resolution. Expected {first_video_resolution}, but got {resolution}",
                        ValidationErrorCodes.DIFFERENT_VIDEO_RESOLUTION,
                    )
        self.video_type = first_video_mime
        self.video_resolution = first_video_resolution
        return videos

    @async_field_validator("audio")
    async def validate_audio(self) -> str | None:
        """
        Validate the audio file path.

        Raises:
            ValueError: If the audio file MIME type is invalid or if the audio
                        duration is less than the total video duration.

        Returns:
            str: Validated audio file path.
        """
        video_durations: Dict[str, float] = {}
        total_video_duration = 0.0
        for video_path in self.videos:
            duration = await get_video_duration(video_path)
            video_durations[video_path] = duration
            total_video_duration += duration

        self.video_durations = video_durations  # Store video durations in the DTO
        audio_path = self.audio
        if audio_path is None:
            return None

        mime = get_mime_type(audio_path)
        if mime not in VALID_AUDIO_MIME_TYPES:
            raise ValueError(
                f"Invalid audio MIME type: {mime}",
                ValidationErrorCodes.INVALID_AUDIO_MIME_TYPE,
            )

        # Calculate durations
        audio_duration = await get_audio_duration(audio_path)
        self.audio_duration = audio_duration  # Store audio duration in the DTO

        if audio_duration < total_video_duration:
            raise ValueError(
                f"Audio is too short. Must be at least {total_video_duration} seconds",
                ValidationErrorCodes.AUDIO_TOO_SHORT,
            )

        if audio_duration > total_video_duration:
            await crop_audio_stream(audio_path, total_video_duration)

        return audio_path
