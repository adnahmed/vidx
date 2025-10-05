
from __future__ import annotations

from typing import List

from beanie import PydanticObjectId

from vidx.db.models.merge_history import MergeHistory


class MergeHistoryDAO:
    """Data access helpers for ``MergeHistory`` documents."""

    async def create_history(
        self,
        *,
        user_id: PydanticObjectId,
        task_id: str,
        videos: List[str],
        audio: str | None,
        transition: str,
    ) -> MergeHistory:
        history = MergeHistory(
            user_id=user_id,
            task_id=task_id,
            videos=videos,
            audio=audio,
            transition=transition,
        )
        await history.insert()
        return history

    async def list_for_user(
        self,
        *,
        user_id: PydanticObjectId,
        limit: int = 20,
        offset: int = 0,
    ) -> List[MergeHistory]:
        cursor = (
            MergeHistory.find(MergeHistory.user_id == user_id)
            .sort('-created_at')
            .skip(offset)
            .limit(limit)
        )
        return await cursor.to_list()

