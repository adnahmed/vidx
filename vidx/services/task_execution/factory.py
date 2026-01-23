"""
Task Execution Strategy Factory

Creates the appropriate execution strategy based on configuration.
Follows Factory Pattern for flexible instantiation.
"""

import logging
from typing import Optional

from vidx.services.task_execution.base import TaskExecutionStrategy
from vidx.services.task_execution.aws_batch import AWSBatchExecutor
from vidx.services.task_execution.local_process import LocalProcessExecutor

logger = logging.getLogger(__name__)


class ExecutionStrategyFactory:
    """
    Factory for creating task execution strategies.

    Intelligently selects the best strategy based on environment and configuration.
    """

    @staticmethod
    def create_strategy(
        environment: str,
        # AWS/Batch config
        aws_region: Optional[str] = None,
        batch_job_queue: Optional[str] = None,
        batch_job_definition: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        aws_endpoint_url: Optional[str] = None,
        # Local config
        ffmpeg_binary: Optional[str] = None,
    ) -> TaskExecutionStrategy:
        """
        Create the appropriate execution strategy.

        Args:
            environment: "prod", "staging", "dev", "localstack"
            aws_*: AWS/Batch configuration
            ffmpeg_binary: Path to ffmpeg (for local execution)

        Returns:
            TaskExecutionStrategy implementation
        """

        # Production: Prefer AWS Batch
        if environment in ["prod", "staging"] and all(
            [aws_region, batch_job_queue, batch_job_definition, s3_bucket]
        ):
            logger.info("Creating AWS Batch executor")
            executor = AWSBatchExecutor(
                aws_region=aws_region,
                batch_job_queue=batch_job_queue,
                batch_job_definition=batch_job_definition,
                s3_bucket=s3_bucket,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
                endpoint_url=aws_endpoint_url,
            )

            if executor.is_available():
                return executor
            else:
                logger.warning(
                    "AWS Batch not available, falling back to local execution"
                )

        # Development/LocalStack: Use local execution
        logger.info("Creating local process executor")
        return LocalProcessExecutor(ffmpeg_binary=ffmpeg_binary)

    @staticmethod
    def get_available_strategies() -> list[TaskExecutionStrategy]:
        """List all available strategies (for diagnostics)."""
        return [
            LocalProcessExecutor(),
            AWSBatchExecutor(
                aws_region="us-east-1",
                batch_job_queue="dummy",
                batch_job_definition="dummy",
                s3_bucket="dummy",
            ),
        ]
