"""
Task Execution Manager

High-level interface for submitting and tracking video processing tasks.
Abstracts away the underlying execution strategy.
"""

import logging
from typing import Dict, Optional
import uuid

from vidx.services.task_execution.base import TaskExecutionStrategy, VideoProcessingContext
from vidx.services.task_execution.factory import ExecutionStrategyFactory

logger = logging.getLogger(__name__)


class TaskExecutionManager:
    """
    Manages video processing tasks regardless of execution backend.

    Provides a consistent interface for:
    - Submitting tasks
    - Tracking progress
    - Handling failures
    - Cancelling tasks
    """

    def __init__(self, strategy: TaskExecutionStrategy):
        """
        Initialize with a specific execution strategy.

        Args:
            strategy: Implementation of TaskExecutionStrategy
        """
        self.strategy = strategy
        logger.info(f"Task execution manager initialized with: {strategy.get_name()}")

    async def submit_merge_task(
        self,
        videos: Dict[str, float],
        audio: Optional[str],
        video_mime: str,
        video_resolution: tuple[int, int],
        audio_duration: Optional[float],
        transition: str,
        user_tier: str = "basic",
    ) -> str:
        """
        Submit a video merge task for processing.

        Args:
            videos: Dict of video file paths to durations
            audio: Optional audio file path
            video_mime: MIME type of output (video/mp4, video/webm, video/ogg)
            video_resolution: Output resolution as (width, height)
            audio_duration: Duration of audio track if provided
            transition: Transition effect name
            user_tier: User tier (basic, premium, enterprise)

        Returns:
            Task ID for tracking
        """
        job_id = str(uuid.uuid4())

        context = VideoProcessingContext(
            videos=videos,
            audio=audio,
            video_mime=video_mime,
            video_resolution=video_resolution,
            audio_duration=audio_duration,
            transition=transition,
            job_id=job_id,
            user_tier=user_tier,
        )

        task_id = await self.strategy.submit_merge_task(context)
        logger.info(f"Task {job_id} submitted successfully")

        return task_id

    async def get_task_status(self, task_id: str) -> Dict:
        """
        Get the current status of a task.

        Returns:
            Dict with keys:
            - status: "pending", "running", "completed", "failed", "cancelled"
            - progress: 0-100
            - output_path: Path to result file (if completed)
            - error: Error message (if failed)
        """
        return await self.strategy.get_task_status(task_id)

    async def wait_for_completion(
        self,
        task_id: str,
        timeout_seconds: int = 3600,
        poll_interval: int = 5,
    ) -> Dict:
        """
        Wait for a task to complete.

        Args:
            task_id: ID of task to wait for
            timeout_seconds: Maximum time to wait
            poll_interval: How often to check status (seconds)

        Returns:
            Final task status
        """
        import asyncio
        import time

        start_time = time.time()

        while True:
            status = await self.get_task_status(task_id)

            if status["status"] in ["completed", "failed", "cancelled"]:
                return status

            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                await self.strategy.cancel_task(task_id)
                raise TimeoutError(f"Task {task_id} timed out after {timeout_seconds}s")

            await asyncio.sleep(poll_interval)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        return await self.strategy.cancel_task(task_id)

    def get_backend_name(self) -> str:
        """Get the name of the current execution backend."""
        return self.strategy.get_name()
