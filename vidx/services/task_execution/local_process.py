"""
Local Process Execution Strategy

Implements video processing directly in the Celery worker process.
Best for development and LocalStack environments.
"""

import logging
from typing import Dict, Optional

from vidx.services.task_execution.base import TaskExecutionStrategy, VideoProcessingContext

logger = logging.getLogger(__name__)


class LocalProcessExecutor(TaskExecutionStrategy):
    """
    Executes video processing directly in the Celery worker.

    Use cases:
    - Local development
    - Testing
    - Small workloads in LocalStack

    Limitations:
    - No auto-scaling
    - Blocked by single task
    - Memory limited to container
    """

    def __init__(self, ffmpeg_binary: Optional[str] = None, state_manager=None):
        """
        Initialize local executor.

        Args:
            ffmpeg_binary: Path to ffmpeg binary (uses env var if not provided)
            state_manager: Optional TaskStateManager for persistent state
        """
        self.ffmpeg_binary = ffmpeg_binary
        self.state_manager = state_manager
        self.task_status_cache: Dict[str, Dict] = {}  # Fallback if no state manager

    async def submit_merge_task(self, context: VideoProcessingContext) -> str:
        """
        Submit a merge task for immediate execution in the local process.

        Returns:
            Task ID for status tracking
        """
        logger.info(f"Executing merge task {context.job_id} locally")

        task_id = context.job_id

        # Store initial state
        if self.state_manager:
            await self.state_manager.store_task_state(
                task_id=task_id,
                status="RUNNING",
                job_id=task_id,
                metadata={"user_tier": context.user_tier}
            )
        else:
            self.task_status_cache[task_id] = {"status": "running", "output_path": None, "error": None}

        try:
            # Import here to avoid circular imports
            from vidx.services.celery.tasks import _merge_videos_sync

            # Execute synchronously
            output_path = _merge_videos_sync(
                videos=context.videos,
                audio=context.audio,
                video_mime=context.video_mime,
                video_resolution=context.video_resolution,
                audio_duration=context.audio_duration,
                transition=context.transition,
            )

            # Store completed state
            if self.state_manager:
                await self.state_manager.store_task_state(
                    task_id=task_id,
                    status="SUCCEEDED",
                    job_id=task_id,
                    output_path=output_path
                )
            else:
                self.task_status_cache[task_id] = {
                    "status": "completed",
                    "output_path": output_path,
                    "error": None,
                }

            logger.info(f"Task {task_id} completed locally: {output_path}")
            return task_id

        except Exception as e:
            logger.error(f"Task {task_id} failed locally: {e}")
            
            # Store failed state
            if self.state_manager:
                await self.state_manager.store_task_state(
                    task_id=task_id,
                    status="FAILED",
                    job_id=task_id,
                    error=str(e)
                )
            else:
                self.task_status_cache[task_id] = {
                    "status": "failed",
                    "output_path": None,
                    "error": str(e),
                }
            raise

    async def get_task_status(self, task_id: str) -> Dict:
        """Get status from persistent state or cache."""
        # Try persistent state first
        if self.state_manager:
            state = await self.state_manager.get_task_state(task_id)
            if state:
                return {
                    "status": state["status"].lower(),
                    "output_path": state.get("output_path"),
                    "error": state.get("error"),
                }
        
        # Fallback to cache
        return self.task_status_cache.get(
            task_id,
            {
                "status": "unknown",
                "progress": 0,
                "output_path": None,
                "error": f"Task {task_id} not found",
            },
        )

    async def cancel_task(self, task_id: str) -> bool:
        """Cannot cancel running tasks in local process."""
        logger.warning(f"Cannot cancel task {task_id} in local process")
        return False

    def is_available(self) -> bool:
        """Local execution is always available."""
        return True

    def get_name(self) -> str:
        return "Local Process"
