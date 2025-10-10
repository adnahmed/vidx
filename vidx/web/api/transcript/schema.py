"""Schemas for transcript API."""

from typing import List, Optional
from pydantic import BaseModel, Field


class TranscriptSnippet(BaseModel):
    """A single transcript snippet."""

    text: str = Field(..., description="The text content of the snippet")
    start: float = Field(..., description="Start time in seconds")
    duration: float = Field(..., description="Duration in seconds")


class TranscriptResponse(BaseModel):
    """Response containing transcript data."""

    video_id: str = Field(..., description="YouTube video ID")
    language: str = Field(..., description="Language name")
    language_code: str = Field(..., description="Language code (e.g., 'en', 'de')")
    is_generated: bool = Field(..., description="Whether the transcript was auto-generated")
    snippets: List[TranscriptSnippet] = Field(..., description="List of transcript snippets")


class TranscriptRequest(BaseModel):
    """Request to fetch a transcript."""

    video_id: str = Field(..., description="YouTube video ID (not the full URL)")
    languages: Optional[List[str]] = Field(
        default=["en"],
        description="List of language codes in descending priority (e.g., ['de', 'en'])",
    )
    preserve_formatting: bool = Field(
        default=False,
        description="Whether to preserve HTML formatting like <i> and <b>",
    )


class TranscriptMetadata(BaseModel):
    """Metadata about a transcript."""

    video_id: str = Field(..., description="YouTube video ID")
    language: str = Field(..., description="Language name")
    language_code: str = Field(..., description="Language code")
    is_generated: bool = Field(..., description="Whether transcript is auto-generated")
    is_translatable: bool = Field(..., description="Whether transcript can be translated")
    translation_languages: List[dict] = Field(
        ..., description="List of languages the transcript can be translated to"
    )


class TranscriptListResponse(BaseModel):
    """Response containing available transcripts for a video."""

    video_id: str = Field(..., description="YouTube video ID")
    transcripts: List[TranscriptMetadata] = Field(
        ..., description="List of available transcripts"
    )


class TranslateTranscriptRequest(BaseModel):
    """Request to translate a transcript."""

    video_id: str = Field(..., description="YouTube video ID")
    source_language: str = Field(..., description="Source language code (e.g., 'en')")
    target_language: str = Field(..., description="Target language code (e.g., 'de')")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
