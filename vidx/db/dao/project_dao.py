"""Data access helpers for projects, scenes and social posts."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from beanie import PydanticObjectId

from vidx.db.models.project import Project, ProjectType
from vidx.db.models.scene import Scene
from vidx.db.models.social_post import PostStatus, SocialPost


class ProjectDAO:
    """Data access helpers for ``Project`` documents."""

    async def create_project(self, project: Project) -> Project:
        await project.insert()
        return project

    async def get_for_user(
        self, *, project_id: PydanticObjectId, user_id: PydanticObjectId,
    ) -> Optional[Project]:
        return await Project.find_one(
            Project.id == project_id, Project.user_id == user_id,
        )

    async def list_for_user(
        self,
        *,
        user_id: PydanticObjectId,
        project_type: Optional[ProjectType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Project]:
        query = Project.find(Project.user_id == user_id)
        if project_type is not None:
            query = Project.find(
                Project.user_id == user_id, Project.project_type == project_type,
            )
        return await query.sort("-created_at").skip(offset).limit(limit).to_list()

    async def delete(self, project: Project) -> None:
        await project.delete()

    async def update_final_video(
        self, *, project_id: PydanticObjectId, fields: dict,
    ) -> None:
        await Project.get_motor_collection().update_one(
            {"_id": project_id},
            {"$set": {f"final_video.{key}": value for key, value in fields.items()}},
        )

    async def update_fields(
        self, *, project_id: PydanticObjectId, fields: dict,
    ) -> None:
        await Project.get_motor_collection().update_one(
            {"_id": project_id}, {"$set": fields},
        )


class SceneDAO:
    """Data access helpers for ``Scene`` documents."""

    async def create_many(self, scenes: List[Scene]) -> List[Scene]:
        if scenes:
            await Scene.insert_many(scenes)
        return scenes

    async def list_for_project(
        self, *, project_id: PydanticObjectId,
    ) -> List[Scene]:
        return (
            await Scene.find(Scene.project_id == project_id)
            .sort("+scene_number")
            .to_list()
        )

    async def get(self, *, scene_id: PydanticObjectId) -> Optional[Scene]:
        return await Scene.get(scene_id)

    async def update_component(
        self,
        *,
        scene_id: PydanticObjectId,
        component: str,
        fields: dict,
        inc_attempts: bool = False,
    ) -> None:
        """
        Atomically update a single component's fields.

        Component submissions and provider callbacks can arrive concurrently
        (e.g. video, audio and subtitles submitted together). Full-document
        saves would lose updates, so every mutation targets only its own
        component path.
        """
        update: dict = {
            "$set": {f"{component}.{key}": value for key, value in fields.items()},
        }
        if inc_attempts:
            update["$inc"] = {f"{component}.attempts": 1}
        await Scene.get_motor_collection().update_one({"_id": scene_id}, update)

    async def update_fields(
        self, *, scene_id: PydanticObjectId, fields: dict,
    ) -> None:
        await Scene.get_motor_collection().update_one(
            {"_id": scene_id}, {"$set": fields},
        )

    async def next_scene_number(self, *, project_id: PydanticObjectId) -> int:
        last = (
            await Scene.find(Scene.project_id == project_id)
            .sort("-scene_number")
            .limit(1)
            .to_list()
        )
        return (last[0].scene_number + 1) if last else 1

    async def delete_for_project(self, *, project_id: PydanticObjectId) -> int:
        scenes = await self.list_for_project(project_id=project_id)
        for scene in scenes:
            await scene.delete()
        return len(scenes)

    async def find_by_provider_job(
        self, *, provider: str, provider_job_id: str, component: str,
    ) -> Optional[Scene]:
        """Correlate a provider callback to the scene component that submitted it."""
        field = f"{component}.provider_job_id"
        field_provider = f"{component}.provider"
        return await Scene.find_one(
            {field: provider_job_id, field_provider: provider},
        )


class SocialPostDAO:
    """Data access helpers for ``SocialPost`` documents."""

    async def create(self, post: SocialPost) -> SocialPost:
        await post.insert()
        return post

    async def get_for_user(
        self, *, post_id: PydanticObjectId, user_id: PydanticObjectId,
    ) -> Optional[SocialPost]:
        return await SocialPost.find_one(
            SocialPost.id == post_id, SocialPost.user_id == user_id,
        )

    async def list_for_project(
        self,
        *,
        project_id: PydanticObjectId,
        day: Optional[date] = None,
    ) -> List[SocialPost]:
        query = SocialPost.find(SocialPost.project_id == project_id)
        if day is not None:
            query = SocialPost.find(
                SocialPost.project_id == project_id, SocialPost.date == day,
            )
        return await query.sort("+scheduled_at_utc").to_list()

    async def delete_for_project(self, *, project_id: PydanticObjectId) -> int:
        posts = await SocialPost.find(SocialPost.project_id == project_id).to_list()
        for post in posts:
            await post.delete()
        return len(posts)

    async def due_scheduled(self, *, now: datetime, limit: int = 50) -> List[SocialPost]:
        return (
            await SocialPost.find(
                SocialPost.status == PostStatus.SCHEDULED,
                SocialPost.scheduled_at_utc <= now,
            )
            .sort("+scheduled_at_utc")
            .limit(limit)
            .to_list()
        )
