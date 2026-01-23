"""
Persistent State Manager for Task Execution

Handles job state tracking across pod restarts using Redis/ElastiCache.
This replaces the in-memory state management that loses data on crashes.
"""
import json
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TaskStateManager:
    """
    Persistent state manager for task execution tracking.
    
    Uses Redis for state persistence so job status survives pod restarts.
    """
    
    def __init__(self, redis_client):
        """
        Initialize with Redis client.
        
        Args:
            redis_client: Redis client instance (from redis-py or aioboto3)
        """
        self.redis = redis_client
        self.key_prefix = "vidx:task:"
        self.ttl_seconds = 86400 * 7  # 7 days
    
    async def store_task_state(
        self,
        task_id: str,
        status: str,
        job_id: Optional[str] = None,
        error: Optional[str] = None,
        output_path: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Store task state in Redis.
        
        Args:
            task_id: Unique task identifier
            status: Task status (PENDING, RUNNING, SUCCEEDED, FAILED)
            job_id: AWS Batch job ID or local execution ID
            error: Error message if failed
            output_path: S3 path to output file
            metadata: Additional metadata (user_tier, timestamps, etc.)
        """
        key = f"{self.key_prefix}{task_id}"
        
        state = {
            "task_id": task_id,
            "status": status,
            "job_id": job_id,
            "error": error,
            "output_path": output_path,
            "updated_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        try:
            # Store as JSON with TTL
            await self.redis.setex(
                key,
                self.ttl_seconds,
                json.dumps(state)
            )
            logger.debug(f"Stored state for task {task_id}: {status}")
        except Exception as e:
            logger.error(f"Failed to store task state for {task_id}: {e}")
            # Don't raise - state storage failure shouldn't break execution
    
    async def get_task_state(self, task_id: str) -> Optional[Dict]:
        """
        Retrieve task state from Redis.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Dict with task state or None if not found
        """
        key = f"{self.key_prefix}{task_id}"
        
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve task state for {task_id}: {e}")
            return None
    
    async def delete_task_state(self, task_id: str) -> None:
        """
        Delete task state (useful for cleanup).
        
        Args:
            task_id: Task identifier
        """
        key = f"{self.key_prefix}{task_id}"
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.error(f"Failed to delete task state for {task_id}: {e}")
    
    async def list_active_tasks(self, limit: int = 100) -> list[Dict]:
        """
        List active tasks (for monitoring/debugging).
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of task state dicts
        """
        pattern = f"{self.key_prefix}*"
        tasks = []
        
        try:
            # Scan for task keys
            cursor = 0
            while len(tasks) < limit:
                cursor, keys = await self.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                
                for key in keys:
                    data = await self.redis.get(key)
                    if data:
                        tasks.append(json.loads(data))
                
                if cursor == 0:
                    break
            
            return tasks[:limit]
        except Exception as e:
            logger.error(f"Failed to list active tasks: {e}")
            return []
    
    async def update_task_progress(
        self,
        task_id: str,
        progress: float,
        message: Optional[str] = None
    ) -> None:
        """
        Update task progress (for long-running jobs).
        
        Args:
            task_id: Task identifier
            progress: Progress percentage (0.0 to 100.0)
            message: Optional progress message
        """
        state = await self.get_task_state(task_id)
        if state:
            if "metadata" not in state:
                state["metadata"] = {}
            
            state["metadata"]["progress"] = progress
            state["metadata"]["progress_message"] = message
            state["updated_at"] = datetime.utcnow().isoformat()
            
            key = f"{self.key_prefix}{task_id}"
            await self.redis.setex(
                key,
                self.ttl_seconds,
                json.dumps(state)
            )
