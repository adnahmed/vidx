from bson import ObjectId
from pydantic import BaseModel, ConfigDict, field_validator


class DummyModelDTO(BaseModel):
    """
    DTO for dummy models.

    It returned when accessing dummy models from the API.
    """

    id: str
    name: str

    @field_validator("id", mode="before")
    @classmethod
    def parse_object_id(cls, document_id: ObjectId) -> str:
        """
        Validator that converts `ObjectId` to json serializable `str`.

        :param document_id: Bson Id for this document.
        :return: The converted str.
        """
        return str(document_id)

    model_config = ConfigDict(from_attributes=True)


class DummyModelInputDTO(BaseModel):
    """DTO for creating new dummy model."""

    name: str
