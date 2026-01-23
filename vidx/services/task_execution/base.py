"""
Task Execution Strategy Pattern

This module defines the abstract interface for video processing task execution.
Implementations can handle local processing, AWS Batch, or other distributed systems.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class VideoProcessingContext:
    """Context for video processing tasks - strategy-agnostic."""

    videos: Dict[str, float]  # path -> duration
    audio: Optional[str]
    video_mime: str
    video_resolution: tuple[int, int]
    audio_duration: Optional[float]
    transition: str
    job_id: str  # Unique identifier for tracking
    user_tier: str  # "basic", "premium", "enterprise"


class TaskExecutionStrategy(ABC):
    """
    Abstract base class for task execution strategies.

    Implementations handle where and how video processing tasks are executed.
    """

    @abstractmethod
    async def submit_merge_task(self, context: VideoProcessingContext) -> str:
        """
        Submit a video merge task for execution.

        Args:
            context: VideoProcessingContext with all merge parameters

        Returns:
            str: Task ID or execution identifier
        """
        pass

    @abstractmethod
    async def get_task_status(self, task_id: str) -> Dict:
        """
        Get the current status of a submitted task.

        Returns:
            Dict with keys: status, progress, output_path, error
        """
        pass

    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this execution strategy is available in current environment."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Return the name of this execution strategy."""
        pass
