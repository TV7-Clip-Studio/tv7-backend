from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Segment duration constraints (in seconds)
MIN_SEGMENT_DURATION = 15
MAX_SEGMENT_DURATION = 90


class HighlightDetectionError(Exception):
    """Raised when highlight detection fails."""


@dataclass(slots=True)
class ClipSegment:
    """A detected video clip segment."""

    start_sec: int
    end_sec: int
    hook: str


class ClipSegmentSchema(BaseModel):
    """Pydantic schema for LLM response validation."""

    start_sec: int = Field(ge=0, description="Start time in seconds")
    end_sec: int = Field(gt=0, description="End time in seconds, must be > start_sec")
    hook: str = Field(min_length=1, max_length=500, description="Engaging caption/hook text")


class HighlightDetectionResponse(BaseModel):
    """Pydantic schema for complete LLM response."""

    clips: list[ClipSegmentSchema] = Field(
        min_length=3, max_length=5, description="3-5 clip segments"
    )


SYSTEM_PROMPT = """You are an expert at identifying engaging short-form video content for platforms like YouTube Shorts, TikTok, and Instagram Reels.

Given a video transcript, your task is to:
1. Identify 3-5 segments that would make compelling standalone short-form clips (30-60 seconds each)
2. For each segment, provide:
   - start_sec: Starting timestamp in seconds
   - end_sec: Ending timestamp in seconds (segments should be 30-60 seconds long)
   - hook: A short, engaging caption/hook text (1-2 sentences max) that would draw viewers in

Focus on segments that:
- Have a clear, self-contained point or story
- Start with an attention-grabbing moment
- Build curiosity or tension
- Have high energy or emotional impact
- Work well out of context from the full video

Respond ONLY with valid JSON in this exact format:
{
  "clips": [
    {"start_sec": 45, "end_sec": 90, "hook": "The surprising truth about..."},
    {"start_sec": 120, "end_sec": 165, "hook": "What happens next is unbelievable"},
    ...
  ]
}"""


async def detect_highlights(
    transcript: str, duration_seconds: int, video_id: int
) -> list[ClipSegment]:
    """
    Analyze transcript and detect engaging clip segments using OpenAI.

    Args:
        transcript: Full video transcript text
        duration_seconds: Total video duration for validation
        video_id: Video ID for logging context

    Returns:
        List of ClipSegment objects with timing and hook text

    Raises:
        HighlightDetectionError: If LLM call fails or returns invalid data
    """
    if not settings.OPENAI_API_KEY:
        raise HighlightDetectionError("OPENAI_API_KEY not configured")

    if not transcript or not transcript.strip():
        raise HighlightDetectionError("Transcript is empty or missing")

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    user_prompt = f"""Video duration: {duration_seconds} seconds

Transcript:
{transcript}

Please identify 3-5 engaging segments for short-form content. Return your response as JSON only."""

    try:
        logger.info(
            "Calling OpenAI for highlight detection",
            extra={"video_id": video_id, "transcript_length": len(transcript)},
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        raw_content = response.choices[0].message.content
        if not raw_content:
            raise HighlightDetectionError("OpenAI returned empty response")

        logger.debug(
            "OpenAI response received",
            extra={"video_id": video_id, "raw_content": raw_content[:200]},
        )

        # Parse JSON response
        try:
            parsed_data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse OpenAI JSON response",
                extra={"video_id": video_id, "raw_content": raw_content},
            )
            raise HighlightDetectionError(f"Invalid JSON from LLM: {exc}") from exc

        # Validate with Pydantic
        try:
            validated = HighlightDetectionResponse(**parsed_data)
        except ValidationError as exc:
            logger.error(
                "OpenAI response failed validation",
                extra={"video_id": video_id, "errors": exc.errors()},
            )
            raise HighlightDetectionError(f"LLM response validation failed: {exc}") from exc

        # Convert to dataclass and validate timing constraints
        segments: list[ClipSegment] = []
        for clip_data in validated.clips:
            # Validate segment timing
            if clip_data.end_sec <= clip_data.start_sec:
                logger.warning(
                    "Skipping invalid segment (end <= start)",
                    extra={
                        "video_id": video_id,
                        "start": clip_data.start_sec,
                        "end": clip_data.end_sec,
                    },
                )
                continue

            if clip_data.end_sec > duration_seconds:
                logger.warning(
                    "Skipping segment exceeding video duration",
                    extra={
                        "video_id": video_id,
                        "end": clip_data.end_sec,
                        "duration": duration_seconds,
                    },
                )
                continue

            segment_duration = clip_data.end_sec - clip_data.start_sec
            if segment_duration < MIN_SEGMENT_DURATION or segment_duration > MAX_SEGMENT_DURATION:
                logger.warning(
                    f"Skipping segment with invalid duration (should be {MIN_SEGMENT_DURATION}-{MAX_SEGMENT_DURATION}s)",
                    extra={
                        "video_id": video_id,
                        "duration": segment_duration,
                        "start": clip_data.start_sec,
                        "end": clip_data.end_sec,
                    },
                )
                continue

            segments.append(
                ClipSegment(
                    start_sec=clip_data.start_sec,
                    end_sec=clip_data.end_sec,
                    hook=clip_data.hook,
                )
            )

        if not segments:
            raise HighlightDetectionError("No valid segments found after validation and filtering")

        logger.info(
            "Highlight detection successful",
            extra={"video_id": video_id, "segment_count": len(segments)},
        )

        return segments

    except HighlightDetectionError:
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected error during highlight detection",
            extra={"video_id": video_id, "error": str(exc)},
        )
        raise HighlightDetectionError(f"Unexpected error: {exc}") from exc
