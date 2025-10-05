"""vidx models."""

from typing import Sequence, Type

from beanie import Document

from vidx.db.models.dummy_model import DummyModel
from vidx.db.models.user import User
from vidx.db.models.merge_history import MergeHistory


def load_all_models() -> Sequence[Type[Document]]:
    """Load all models from this folder."""
    return [
        DummyModel,
        User,
        MergeHistory,
    ]
