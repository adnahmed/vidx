"""Tests for the FFmpeg render service (skipped when FFmpeg is unavailable)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidx.services.render.ffmpeg_render import (
    RenderService,
    has_audio_stream,
)
from vidx.settings import settings

ffmpeg_available = shutil.which(settings.ffmpeg) is not None or Path(settings.ffmpeg).exists()
pytestmark = pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg is not available")


def _run(args: list[str]) -> None:
    result = subprocess.run(
        [settings.ffmpeg, "-y", *args], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr[-500:]


def _make_video(path: Path, color: str = "blue", duration: str = "2") -> None:
    _run(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
    )


def test_render_scene_with_logo_and_subtitles(tmp_path) -> None:
    video = tmp_path / "scene.mp4"
    audio = tmp_path / "voice.mp3"
    logo = tmp_path / "logo.png"
    subtitles = tmp_path / "captions.srt"
    output = tmp_path / "final.mp4"

    _make_video(video)
    _run(["-f", "lavfi", "-i", "sine=frequency=660:duration=2", "-c:a", "libmp3lame", str(audio)])
    _run(["-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(logo)])
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nHello render\n\n"
        "2\n00:00:01,500 --> 00:00:02,000\nSecond cue\n",
        encoding="utf-8",
    )

    service = RenderService()
    service._render_scene_sync(
        video_path=str(video),
        output_path=str(output),
        audio_path=str(audio),
        subtitle_path=str(subtitles),
        logo_path=str(logo),
        resolution=(320, 240),
    )
    assert output.exists() and output.stat().st_size > 0
    assert has_audio_stream(str(output))


def test_render_scene_without_optional_inputs_adds_silence(tmp_path) -> None:
    video = tmp_path / "plain.mp4"
    output = tmp_path / "plain_out.mp4"
    _make_video(video)
    service = RenderService()
    service._render_scene_sync(
        video_path=str(video), output_path=str(output), resolution=(320, 240),
    )
    assert output.exists()
    assert has_audio_stream(str(output))


def test_assemble_final_concatenates_scenes(tmp_path) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    output = tmp_path / "assembled.mp4"
    _make_video(first, "green", "1")
    _make_video(second, "orange", "1")

    service = RenderService()
    service._assemble_sync(
        scene_paths=[str(first), str(second)],
        output_path=str(output),
        resolution=(320, 240),
    )
    assert output.exists() and output.stat().st_size > 0
    probe = subprocess.run(
        [
            settings.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    duration = float(probe.stdout.strip())
    assert duration > 1.5
