"""
AWS Batch Execution Strategy

Implements distributed video processing using AWS Batch.
Suitable for production environments with heavy, unpredictable workloads.
"""

import json
import logging
from typing import Dict, Optional

import boto3

from vidx.services.task_execution.base import TaskExecutionStrategy, VideoProcessingContext
from vidx.services.task_execution.state_manager import TaskStateManager

logger = logging.getLogger(__name__)


class AWSBatchExecutor(TaskExecutionStrategy):
    """
    Executes video processing tasks via AWS Batch.

    Benefits:
    - Automatic scaling based on workload
    - Pay only for resources used
    - Can use Spot instances (75% cheaper)
    - Handles tasks that exceed node memory
    - No need for fixed worker pools
    """

    def __init__(
        self,
        aws_region: str,
        batch_job_queue: str,
        batch_job_definition: str,
        s3_bucket: str,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        state_manager: Optional[TaskStateManager] = None,
    ):
        """
        Initialize AWS Batch executor.

        Args:
            aws_region: AWS region
            batch_job_queue: Name of AWS Batch job queue
            batch_job_definition: Name of AWS Batch job definition
            s3_bucket: S3 bucket for storing videos/outputs
            aws_access_key_id: AWS access key (optional, uses env vars if not provided)
            aws_secret_access_key: AWS secret key (optional)
            aws_session_token: AWS session token (optional)
            endpoint_url: Custom endpoint (for LocalStack)
        """
        self.aws_region = aws_region
        self.batch_job_queue = batch_job_queue
        self.batch_job_definition = batch_job_definition
        self.s3_bucket = s3_bucket
        self.state_manager = state_manager

        # Initialize boto3 clients
        session_kwargs = {}
        if aws_access_key_id:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
        if aws_session_token:
            session_kwargs["aws_session_token"] = aws_session_token

        session = boto3.Session(**session_kwargs)

        client_kwargs = {"region_name": aws_region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        self.batch_client = session.client("batch", **client_kwargs)
        self.s3_client = session.client("s3", **client_kwargs)

    async def submit_merge_task(self, context: VideoProcessingContext) -> str:
        """
        Submit a video merge task to AWS Batch.

        The job will be scheduled to run on an EC2 instance with appropriate resources.
        """
        logger.info(f"Submitting merge task {context.job_id} to AWS Batch")

        # Prepare job parameters
        container_overrides = {
            "environment": [
                {"name": "JOB_ID", "value": context.job_id},
                {"name": "VIDEO_MIME", "value": context.video_mime},
                {"name": "TRANSITION", "value": context.transition},
                {"name": "VIDEO_RESOLUTION", "value": f"{context.video_resolution[0]}x{context.video_resolution[1]}"},
                {"name": "S3_BUCKET", "value": self.s3_bucket},
                {"name": "USER_TIER", "value": context.user_tier},
                {
                    "name": "VIDEO_FILES_JSON",
                    "value": json.dumps(context.videos),
                },
                {
                    "name": "AUDIO_FILE",
                    "value": context.audio or "null",
                },
            ]
        }

        # Determine resource requirements based on user tier
        resources = self._get_resource_requirements(context.user_tier, context.videos)
        if resources.get("vcpus"):
            container_overrides["vcpus"] = resources["vcpus"]
        if resources.get("memory"):
            container_overrides["memory"] = resources["memory"]

        try:
            response = self.batch_client.submit_job(
                jobName=f"vidx-merge-{context.job_id}",
                jobQueue=self.batch_job_queue,
                jobDefinition=self.batch_job_definition,
                containerOverrides=container_overrides,
                timeout={"attemptDurationSeconds": 3600},  # 1 hour timeout
            )

            job_id = response["jobId"]
            logger.info(f"Task {context.job_id} submitted as Batch job {job_id}")
            return job_id

        except Exception as e:
            logger.error(f"Failed to submit task to AWS Batch: {e}")
            raise

    async def get_task_status(self, task_id: str) -> Dict:
        """Get the status of a Batch job."""
        try:
            response = self.batch_client.describe_jobs(jobs=[task_id])

            if not response["jobs"]:
                return {"status": "NOT_FOUND", "error": f"Job {task_id} not found"}

            job = response["jobs"][0]
            status = job["status"]
            
            result = {
                "status": status,
                "progress": 0,
                "output_path": None,
                "error": None,
            }

            # Map Batch status to standard status
            status_map = {
                "SUBMITTED": "pending",
                "PENDING": "pending",
                "RUNNABLE": "pending",
                "STARTING": "running",
                "RUNNING": "running",
                "SUCCEEDED": "completed",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }
            result["status"] = status_map.get(status, "unknown")

            if status == "SUCCEEDED":
                result["output_path"] = f"s3://{self.s3_bucket}/outputs/{task_id}/merged.mp4"

            if status == "FAILED":
                reason = job.get("statusReason", "Unknown error")
                result["error"] = reason

            return result

        except Exception as e:
            logger.error(f"Failed to get task status: {e}")
            return {"status": "error", "error": str(e)}

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running Batch job."""
        try:
            self.batch_client.terminate_job(jobId=task_id, reason="Cancelled by user")
            logger.info(f"Task {task_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel task {task_id}: {e}")
            return False

    def is_available(self) -> bool:
        """Check if AWS Batch is available (credentials configured)."""
        try:
            self.batch_client.describe_job_queues(maxResults=1)
            return True
        except Exception:
            return False

    def get_name(self) -> str:
        return "AWS Batch"

    @staticmethod
    def _get_resource_requirements(user_tier: str, videos: Dict[str, float]) -> Dict:
        """
        Determine CPU and memory requirements based on user tier and video count.

        Uses tiered pricing model:
        - Basic (10 videos): 2 vCPU, 4GB
        - Premium (50 videos): 4 vCPU, 16GB
        - Enterprise (unlimited): 8 vCPU, 32GB
        """
        video_count = len(videos)
        total_duration = sum(videos.values())

        if user_tier == "enterprise":
            return {"vcpus": 8, "memory": 32768}  # 32GB
        elif user_tier == "premium":
            # Scale based on video count
            if video_count > 30:
                return {"vcpus": 8, "memory": 32768}
            else:
                return {"vcpus": 4, "memory": 16384}  # 16GB
        else:  # basic
            return {"vcpus": 2, "memory": 4096}  # 4GB
