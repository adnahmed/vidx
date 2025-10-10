"""Transcript API views."""

from typing import List
from fastapi import APIRouter, HTTPException, status
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    NotTranslatable,
    TranslationLanguageNotAvailable,
    YouTubeRequestFailed,
)

from vidx.web.api.transcript.schema import (
    TranscriptRequest,
    TranscriptResponse,
    TranscriptSnippet,
    TranscriptListResponse,
    TranscriptMetadata,
    TranslateTranscriptRequest,
    ErrorResponse,
)

router = APIRouter(prefix="/transcript", tags=["transcript"])


@router.post(
    "/fetch",
    response_model=TranscriptResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Transcript not found"},
        403: {"model": ErrorResponse, "description": "Transcripts disabled for video"},
        503: {"model": ErrorResponse, "description": "YouTube service unavailable or rate limited"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Fetch transcript for a video",
    description="Fetch the transcript for a YouTube video by providing the video ID. "
    "Returns transcript snippets with text, start time, and duration.",
)
async def fetch_transcript(request: TranscriptRequest) -> TranscriptResponse:
    """
    Fetch a transcript for a YouTube video.

    **Parameters:**
    - **video_id**: YouTube video ID (e.g., '12345' from https://www.youtube.com/watch?v=12345)
    - **languages**: List of language codes in descending priority (default: ['en'])
    - **preserve_formatting**: Keep HTML formatting like <i> and <b> (default: False)

    **Example Request:**
    ```json
    {
        "video_id": "dQw4w9WgXcQ",
        "languages": ["en"],
        "preserve_formatting": false
    }
    ```

    **Example Response:**
    ```json
    {
        "video_id": "dQw4w9WgXcQ",
        "language": "English",
        "language_code": "en",
        "is_generated": false,
        "snippets": [
            {
                "text": "Hey there",
                "start": 0.0,
                "duration": 1.54
            },
            {
                "text": "how are you",
                "start": 1.54,
                "duration": 4.16
            }
        ]
    }
    ```
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(
            request.video_id,
            languages=request.languages,
            preserve_formatting=request.preserve_formatting,
        )

        snippets = [
            TranscriptSnippet(
                text=snippet.text,
                start=snippet.start,
                duration=snippet.duration,
            )
            for snippet in fetched
        ]

        return TranscriptResponse(
            video_id=fetched.video_id,
            language=fetched.language,
            language_code=fetched.language_code,
            is_generated=fetched.is_generated,
            snippets=snippets,
        )

    except NoTranscriptFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transcript found for video {request.video_id} in languages {request.languages}",
        )
    except TranscriptsDisabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Transcripts are disabled for video {request.video_id}",
        )
    except VideoUnavailable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {request.video_id} is unavailable",
        )
    except YouTubeRequestFailed as e:
        # This can include rate limiting and other request failures
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"YouTube request failed: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )


@router.get(
    "/list/{video_id}",
    response_model=TranscriptListResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Video not found"},
        403: {"model": ErrorResponse, "description": "Transcripts disabled for video"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="List available transcripts",
    description="List all available transcripts for a YouTube video, including metadata "
    "about each transcript such as language, whether it's auto-generated, and translation options.",
)
async def list_transcripts(video_id: str) -> TranscriptListResponse:
    """
    List all available transcripts for a YouTube video.

    **Parameters:**
    - **video_id**: YouTube video ID (e.g., '12345' from https://www.youtube.com/watch?v=12345)

    **Example Response:**
    ```json
    {
        "video_id": "dQw4w9WgXcQ",
        "transcripts": [
            {
                "video_id": "dQw4w9WgXcQ",
                "language": "English",
                "language_code": "en",
                "is_generated": false,
                "is_translatable": true,
                "translation_languages": [
                    {"language": "German", "language_code": "de"},
                    {"language": "French", "language_code": "fr"}
                ]
            }
        ]
    }
    ```
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        transcripts = []
        for transcript in transcript_list:
            transcripts.append(
                TranscriptMetadata(
                    video_id=transcript.video_id,
                    language=transcript.language,
                    language_code=transcript.language_code,
                    is_generated=transcript.is_generated,
                    is_translatable=transcript.is_translatable,
                    translation_languages=[
                        {
                            "language": lang["language"],
                            "language_code": lang["language_code"],
                        }
                        for lang in transcript.translation_languages
                    ],
                )
            )

        return TranscriptListResponse(video_id=video_id, transcripts=transcripts)

    except NoTranscriptFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transcripts available for video {video_id}",
        )
    except TranscriptsDisabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Transcripts are disabled for video {video_id}",
        )
    except VideoUnavailable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} is unavailable",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )


@router.post(
    "/translate",
    response_model=TranscriptResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Transcript not found"},
        400: {"model": ErrorResponse, "description": "Translation not available"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Translate a transcript",
    description="Fetch a transcript and translate it to another language using YouTube's "
    "automatic translation feature.",
)
async def translate_transcript(request: TranslateTranscriptRequest) -> TranscriptResponse:
    """
    Translate a transcript to another language.

    **Parameters:**
    - **video_id**: YouTube video ID
    - **source_language**: Source language code (e.g., 'en')
    - **target_language**: Target language code (e.g., 'de')

    **Example Request:**
    ```json
    {
        "video_id": "dQw4w9WgXcQ",
        "source_language": "en",
        "target_language": "de"
    }
    ```

    **Example Response:**
    ```json
    {
        "video_id": "dQw4w9WgXcQ",
        "language": "German",
        "language_code": "de",
        "is_generated": true,
        "snippets": [
            {
                "text": "Hallo zusammen",
                "start": 0.0,
                "duration": 1.54
            }
        ]
    }
    ```
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(request.video_id)

        # Find the source transcript
        transcript = transcript_list.find_transcript([request.source_language])

        # Translate it
        translated = transcript.translate(request.target_language)

        # Fetch the translated transcript
        fetched = translated.fetch()

        snippets = [
            TranscriptSnippet(
                text=snippet.text,
                start=snippet.start,
                duration=snippet.duration,
            )
            for snippet in fetched
        ]

        return TranscriptResponse(
            video_id=fetched.video_id,
            language=fetched.language,
            language_code=fetched.language_code,
            is_generated=fetched.is_generated,
            snippets=snippets,
        )

    except NoTranscriptFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transcript found in language {request.source_language}",
        )
    except NotTranslatable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This transcript cannot be translated",
        )
    except TranslationLanguageNotAvailable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Translation to {request.target_language} is not available",
        )
    except VideoUnavailable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {request.video_id} is unavailable",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )


@router.get(
    "/manually-created/{video_id}",
    response_model=TranscriptResponse,
    responses={
        404: {"model": ErrorResponse, "description": "No manually created transcript found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Fetch manually created transcript",
    description="Fetch only manually created (not auto-generated) transcripts for a video.",
)
async def fetch_manually_created_transcript(
    video_id: str,
    languages: List[str] = None,
) -> TranscriptResponse:
    """
    Fetch a manually created transcript (excludes auto-generated ones).

    **Parameters:**
    - **video_id**: YouTube video ID
    - **languages**: List of language codes (query parameter, can be repeated)

    **Example:**
    GET /transcript/manually-created/dQw4w9WgXcQ?languages=en&languages=de
    """
    if languages is None:
        languages = ["en"]
    
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Find manually created transcript
        transcript = transcript_list.find_manually_created_transcript(languages)
        fetched = transcript.fetch()

        snippets = [
            TranscriptSnippet(
                text=snippet.text,
                start=snippet.start,
                duration=snippet.duration,
            )
            for snippet in fetched
        ]

        return TranscriptResponse(
            video_id=fetched.video_id,
            language=fetched.language,
            language_code=fetched.language_code,
            is_generated=fetched.is_generated,
            snippets=snippets,
        )

    except NoTranscriptFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No manually created transcript found for video {video_id}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )


@router.get(
    "/auto-generated/{video_id}",
    response_model=TranscriptResponse,
    responses={
        404: {"model": ErrorResponse, "description": "No auto-generated transcript found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Fetch auto-generated transcript",
    description="Fetch only auto-generated transcripts for a video.",
)
async def fetch_generated_transcript(
    video_id: str,
    languages: List[str] = None,
) -> TranscriptResponse:
    """
    Fetch an auto-generated transcript (excludes manually created ones).

    **Parameters:**
    - **video_id**: YouTube video ID
    - **languages**: List of language codes (query parameter, can be repeated)

    **Example:**
    GET /transcript/auto-generated/dQw4w9WgXcQ?languages=en&languages=de
    """
    if languages is None:
        languages = ["en"]
    
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Find generated transcript
        transcript = transcript_list.find_generated_transcript(languages)
        fetched = transcript.fetch()

        snippets = [
            TranscriptSnippet(
                text=snippet.text,
                start=snippet.start,
                duration=snippet.duration,
            )
            for snippet in fetched
        ]

        return TranscriptResponse(
            video_id=fetched.video_id,
            language=fetched.language,
            language_code=fetched.language_code,
            is_generated=fetched.is_generated,
            snippets=snippets,
        )

    except NoTranscriptFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No auto-generated transcript found for video {video_id}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )
