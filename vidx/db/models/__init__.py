"""vidx models."""

from typing import Sequence, Type

from beanie import Document

from vidx.db.models.dummy_model import DummyModel
from vidx.db.models.merge_history import MergeHistory
from vidx.db.models.project import Project
from vidx.db.models.scene import Scene
from vidx.db.models.social_post import SocialPost
from vidx.db.models.user import User


def load_all_models() -> Sequence[Type[Document]]:
    """Load all models from this folder."""
    return [
        DummyModel,
        User,
        MergeHistory,
        Project,
        Scene,
        SocialPost,
    ]
