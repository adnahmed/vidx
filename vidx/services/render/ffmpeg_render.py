"""FFmpeg-backed rendering: scene post-processing and final video assembly.

This module reuses the existing FFmpeg binary configured for the application
(``settings.ffmpeg`` / ``settings.ffprobe``). It does not replace or modify the
gl-transition merge engine; it adds the post-processing pipeline required by
Video Production: logo overlay, subtitle burn-in, audio muxing, scene rendering
and final concatenation.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

from vidx.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_RESOLUTION = (1280, 720)
DEFAULT_FPS = 30


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    logger.debug("Running render command: %s", " ".join(command))
    return subprocess.run(
        list(command), capture_output=True, text=True, check=False,
    )


def _filter_path(path: str) -> str:
    """Escape a filesystem path for use inside an FFmpeg filter argument."""
    resolved = str(Path(path).resolve()).replace("\\", "/")
    return resolved.replace(":", "\\:")


def has_audio_stream(path: str) -> bool:
    """Probe a media file for an audio stream."""
    result = _run(
        [
            settings.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            path,
        ],
    )
    return result.returncode == 0 and "audio" in result.stdout


def _overlay_coordinates(position: str, margin: int = 20) -> str:
    return {
        "top-left": f"{margin}:{margin}",
        "top-right": f"W-w-{margin}:{margin}",
        "bottom-left": f"{margin}:H-h-{margin}",
        "bottom-right": f"W-w-{margin}:H-h-{margin}",
        "center": "(W-w)/2:(H-h)/2",
    }.get(position, f"W-w-{margin}:H-h-{margin}")


class RenderService:
    """Scene render and final assembly operations (synchronous internals)."""

    # ── scene render ─────────────────────────────────────────────────────────
    def _render_scene_sync(
        self,
        *,
        video_path: str,
        output_path: str,
        audio_path: Optional[str] = None,
        subtitle_path: Optional[str] = None,
        logo_path: Optional[str] = None,
        resolution: tuple[int, int] = DEFAULT_RESOLUTION,
        logo_position: str = "bottom-right",
        fps: int = DEFAULT_FPS,
    ) -> str:
        width, height = resolution
        ffmpeg = settings.ffmpeg

        command: list[str] = [ffmpeg, "-y", "-i", video_path]
        next_index = 1
        audio_index: Optional[int] = None
        logo_index: Optional[int] = None

        if audio_path:
            command += ["-i", audio_path]
            audio_index = next_index
            next_index += 1
        if logo_path:
            command += ["-i", logo_path]
            logo_index = next_index
            next_index += 1

        if audio_index is None:
            # Always produce an audio track so final assembly can concatenate
            # scenes without per-input special cases.
            command += [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
            ]
            audio_index = next_index
            next_index += 1

        parts = [
            (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"fps={fps}[v0]"
            ),
        ]
        video_label = "v0"
        stage = 1

        if logo_index is not None:
            logo_height = max(24, height // 8)
            parts.append(
                f"[{logo_index}:v]scale=-1:{logo_height},format=rgba,"
                f"colorchannelmixer=aa=0.9[logo]",
            )
            parts.append(
                f"[{video_label}][logo]overlay={_overlay_coordinates(logo_position)}"
                f"[v{stage}]",
            )
            video_label = f"v{stage}"
            stage += 1

        if subtitle_path:
            parts.append(
                f"[{video_label}]subtitles=filename='{_filter_path(subtitle_path)}'"
                f"[v{stage}]",
            )
            video_label = f"v{stage}"
            stage += 1

        filter_complex = ";".join(parts)
        command += [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{video_label}]",
            "-map",
            f"{audio_index}:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            output_path,
        ]

        result = _run(command)
        if result.returncode != 0:
            raise RuntimeError(
                f"Scene render failed ({result.returncode}): {result.stderr[-800:]}",
            )
        return output_path

    async def render_scene(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._render_scene_sync, **kwargs)

    def new_output_path(self, suffix: str = ".mp4") -> str:
        handle = tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix=f"vidx_render_{uuid.uuid4().hex[:8]}_",
        )
        handle.close()
        return handle.name

    # ── final assembly ───────────────────────────────────────────────────────
    def _assemble_sync(
        self,
        *,
        scene_paths: Sequence[str],
        output_path: str,
        resolution: tuple[int, int] = DEFAULT_RESOLUTION,
        fps: int = DEFAULT_FPS,
    ) -> str:
        if not scene_paths:
            raise ValueError("No scene videos to assemble")

        width, height = resolution
        ffmpeg = settings.ffmpeg
        command: list[str] = [ffmpeg, "-y"]
        for path in scene_paths:
            command += ["-i", path]

        parts: list[str] = []
        video_labels: list[str] = []
        audio_labels: list[str] = []
        audio_less_indices: list[int] = []

        for index, path in enumerate(scene_paths):
            parts.append(
                (
                    f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                    f"fps={fps}[v{index}]"
                ),
            )
            video_labels.append(f"[v{index}]")
            if has_audio_stream(path):
                audio_labels.append(f"[{index}:a]")
            else:
                audio_less_indices.append(index)
                audio_labels.append(None)  # type: ignore[arg-type]

        # Add silent audio inputs for any scene without an audio track.
        base_count = len(scene_paths)
        silence_map: dict[int, int] = {}
        for offset, scene_index in enumerate(audio_less_indices):
            audio_input_index = base_count + offset
            command += [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
            ]
            silence_map[scene_index] = audio_input_index

        for index in range(len(scene_paths)):
            if audio_labels[index] is None:  # type: ignore[comparison-overlap]
                audio_labels[index] = f"[{silence_map[index]}:a]"

        parts.append(
            "".join(video_labels) + f"concat=n={len(video_labels)}:v=1:a=0[vout]",
        )
        parts.append(
            "".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[aout]",
        )
        filter_complex = ";".join(parts)

        command += [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            output_path,
        ]
        result = _run(command)
        if result.returncode != 0:
            raise RuntimeError(
                f"Final assembly failed ({result.returncode}): {result.stderr[-800:]}",
            )
        return output_path

    async def assemble_final(self, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._assemble_sync, **kwargs)


render_service = RenderService()
