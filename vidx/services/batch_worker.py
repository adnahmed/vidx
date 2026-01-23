"""
AWS Batch Worker for Video Processing

This script runs inside an AWS Batch job container.
It reads environment variables, downloads videos from S3, processes them,
and uploads the result back to S3.
"""

import json
import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict

import boto3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class BatchJobExecutor:
    """Execute video merge job in AWS Batch environment."""

    def __init__(self):
        """Initialize batch executor with AWS clients."""
        self.s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"))
        self.job_id = os.environ.get("JOB_ID")
        self.s3_bucket = os.environ.get("S3_BUCKET")
        self.work_dir = Path("/tmp/batch_work")
        self.work_dir.mkdir(exist_ok=True)

        # Parse job parameters from environment
        self.videos_json = os.environ.get("VIDEO_FILES_JSON", "{}")
        self.audio_file = os.environ.get("AUDIO_FILE", "null")
        self.video_mime = os.environ.get("VIDEO_MIME", "video/mp4")
        self.transition = os.environ.get("TRANSITION", "fade")
        self.user_tier = os.environ.get("USER_TIER", "basic")
        resolution_str = os.environ.get("VIDEO_RESOLUTION", "1920x1080")
        self.video_resolution = tuple(map(int, resolution_str.split("x")))

        logger.info(f"Batch job initialized: {self.job_id}")
        logger.info(f"Parameters: tier={self.user_tier}, mime={self.video_mime}")

    def ensure_xvfb(self):
        """Start Xvfb if not already running."""
        try:
            # Clean up any existing lock files
            for lock in ["/tmp/.X1-lock", "/tmp/.X11-unix/X1"]:
                if os.path.exists(lock):
                    os.remove(lock)
                    logger.info(f"Removed existing X lock: {lock}")

            # Start Xvfb
            subprocess.Popen(
                ["Xvfb", ":1", "-screen", "0", "3840x2160x24"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.environ["DISPLAY"] = ":1"
            logger.info("Xvfb started successfully")
        except Exception as e:
            logger.warning(f"Failed to start Xvfb: {e}")
            # Continue anyway, might work without it

    def download_video_from_s3(self, s3_path: str, local_path: Path) -> None:
        """
        Download a video from S3.

        Args:
            s3_path: S3 path (s3://bucket/key or just key)
            local_path: Where to save the file locally
        """
        # Parse S3 path
        if s3_path.startswith("s3://"):
            bucket, key = s3_path.replace("s3://", "").split("/", 1)
        else:
            bucket = self.s3_bucket
            key = s3_path

        logger.info(f"Downloading s3://{bucket}/{key} to {local_path}")

        try:
            self.s3_client.download_file(bucket, key, str(local_path))
            logger.info(f"Downloaded: {local_path}")
        except Exception as e:
            logger.error(f"Failed to download {s3_path}: {e}")
            raise

    def upload_result_to_s3(self, local_path: Path, s3_key: str) -> str:
        """
        Upload result to S3.

        Args:
            local_path: Local file path
            s3_key: S3 key (in configured bucket)

        Returns:
            S3 URI of uploaded file
        """
        logger.info(f"Uploading {local_path} to s3://{self.s3_bucket}/{s3_key}")

        try:
            self.s3_client.upload_file(str(local_path), self.s3_bucket, s3_key)
            s3_uri = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"Uploaded: {s3_uri}")
            return s3_uri
        except Exception as e:
            logger.error(f"Failed to upload result: {e}")
            raise

    def prepare_local_videos(self) -> Dict[str, float]:
        """
        Parse video paths from environment and download them locally.

        Returns:
            Dict of local paths to durations
        """
        try:
            videos_dict = json.loads(self.videos_json)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid VIDEO_FILES_JSON: {e}")
            raise

        local_videos = {}

        for video_path, duration in videos_dict.items():
            # Download from S3 if it's a S3 path
            if video_path.startswith("s3://"):
                local_path = self.work_dir / f"video_{len(local_videos)}.mp4"
                self.download_video_from_s3(video_path, local_path)
            else:
                # Assume it's a local path in S3-like format
                local_path = self.work_dir / f"video_{len(local_videos)}.mp4"
                self.download_video_from_s3(video_path, local_path)

            local_videos[str(local_path)] = duration
            logger.info(f"Prepared video: {local_path} ({duration}s)")

        return local_videos

    def prepare_local_audio(self) -> str | None:
        """
        Prepare audio file if provided.

        Returns:
            Local path to audio file or None
        """
        if self.audio_file == "null" or not self.audio_file:
            return None

        local_path = self.work_dir / "audio.aac"
        self.download_video_from_s3(self.audio_file, local_path)
        logger.info(f"Prepared audio: {local_path}")
        return str(local_path)

    def execute_merge(
        self,
        videos: Dict[str, float],
        audio: str | None,
    ) -> str:
        """
        Execute the video merge using the local executor.

        Args:
            videos: Dict of local video paths to durations
            audio: Path to audio file or None

        Returns:
            Path to merged video file
        """
        logger.info(f"Starting merge: {len(videos)} videos")

        # Import here to avoid issues before settings are configured
        from vidx.services.celery.tasks import _merge_videos_sync

        try:
            output_path = _merge_videos_sync(
                videos=videos,
                audio=audio,
                video_mime=self.video_mime,
                video_resolution=self.video_resolution,
                audio_duration=None,  # Not used by _merge_videos_sync
                transition=self.transition,
            )
            logger.info(f"Merge completed: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Merge failed: {e}", exc_info=True)
            raise

    def run(self) -> int:
        """
        Execute the batch job.

        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            logger.info(f"=== Batch Job Start: {self.job_id} ===")

            # Step 1: Ensure Xvfb is running (FFmpeg needs it)
            self.ensure_xvfb()

            # Step 2: Prepare local videos and audio
            logger.info("Downloading videos from S3...")
            videos = self.prepare_local_videos()

            logger.info("Preparing audio...")
            audio = self.prepare_local_audio()

            # Step 3: Execute merge
            logger.info("Executing merge...")
            merged_path = self.execute_merge(videos, audio)

            # Step 4: Upload result to S3
            logger.info("Uploading result to S3...")
            s3_output_key = f"outputs/{self.job_id}/merged.mp4"
            s3_uri = self.upload_result_to_s3(Path(merged_path), s3_output_key)

            logger.info(f"=== Batch Job Success: {self.job_id} ===")
            logger.info(f"Output: {s3_uri}")

            return 0

        except Exception as e:
            logger.error(f"=== Batch Job Failed: {self.job_id} ===", exc_info=True)
            return 1


def main():
    """Entry point for batch worker."""
    executor = BatchJobExecutor()
    exit_code = executor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
