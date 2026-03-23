"""
OpenAI fallback detection chain.
Uses Whisper transcription + GPT-4 structured extraction when DashScope fails.
"""
from __future__ import annotations
import inspect
import json
import logging
import os
import subprocess
import tempfile
from typing import Optional

from openai import OpenAI

from apps.api.schemas.detection_schemas import DetectionResult, DetectionEvent, EventType
from apps.api.config import get_settings
from apps.api.utils.media_binaries import require_binary

logger = logging.getLogger(__name__)
settings = get_settings()

# Strict JSON schema for structured output
FOOTBALL_EVENTS_SCHEMA = {
    "name": "football_events",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_type": {
                            "type": "string",
                            "enum": [
                                "GOAL", "SHOT_ON_TARGET", "SAVE",
                                "SHOT_BLOCKED", "CORNER_KICK", "FREE_KICK", "OFFSIDE", "FOUL", "SUBSTITUTION",
                                "YELLOW_CARD", "RED_CARD", "PENALTY", "VAR", "HIGHLIGHT"
                            ],
                        },
                        "timestamp_seconds": {"type": "number"},
                        "confidence": {"type": "number"},
                        "description": {"type": "string"},
                    },
                    "required": ["event_type", "timestamp_seconds", "confidence", "description"],
                    "additionalProperties": False,
                },
            },
            "video_duration": {"type": "number"},
        },
        "required": ["events", "video_duration"],
        "additionalProperties": False,
    },
}

EXTRACTION_SYSTEM_PROMPT = """
You are a football match analyst. Based on the audio transcription/commentary provided,
identify all key football events with precise timestamps.
Extract events of types: GOAL, SHOT_ON_TARGET, SHOT_BLOCKED, SAVE, CORNER_KICK, FREE_KICK, OFFSIDE, FOUL, SUBSTITUTION, YELLOW_CARD, RED_CARD, PENALTY, VAR, HIGHLIGHT.
Also detect SHOT_BLOCKED when a defender clearly blocks a shot attempt.
Use context clues from commentary (e.g. "GOAAAL!", "Yellow card", "Penalty") to determine event types.
Do NOT classify as GOAL if commentary indicates saved, blocked, off target, hits post/crossbar, or offside/disallowed.
Estimate timestamp_seconds based on commentary timing.
"""


async def detect_with_openai(
    source_path: str,
    progress_callback=None,
) -> DetectionResult:
    """Fallback detection via Whisper transcription + GPT-4 structured extraction."""
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key)

    # Step 1: Extract audio (use tempfile for parallel safety)
    await _emit_progress(progress_callback, 0.05)

    tmp_fd, audio_path = tempfile.mkstemp(suffix=".mp3", prefix="openai_audio_")
    os.close(tmp_fd)
    _extract_audio(source_path, audio_path)

    await _emit_progress(progress_callback, 0.1)

    # Step 2: Transcribe with Whisper
    transcript_text, segments = await _transcribe_audio(client, audio_path)

    await _emit_progress(progress_callback, 0.2)

    # Step 3: Build timed transcript
    timed_text = _build_timed_transcript(segments)

    # Step 4: Extract events with GPT-4 structured output
    await _emit_progress(progress_callback, 0.25)

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={
            "type": "json_schema",
            "json_schema": FOOTBALL_EVENTS_SCHEMA,
        },
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Commentary transcript:\n\n{timed_text}"},
        ],
        max_tokens=4096,
    )

    await _emit_progress(progress_callback, 0.3)

    raw_text = response.choices[0].message.content or "{}"
    result = _parse_structured_response(raw_text)

    # Cleanup
    if os.path.exists(audio_path):
        os.remove(audio_path)

    return result


def _extract_audio(video_path: str, audio_path: str) -> None:
    """Extract audio track from video using ffmpeg."""
    ffmpeg_bin = require_binary("ffmpeg")
    cmd = [
        ffmpeg_bin, "-y", "-i", video_path,
        "-vn", "-acodec", "mp3", "-ab", "128k",
        "-ar", "16000",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-500:]}")


async def _transcribe_audio(client: OpenAI, audio_path: str) -> tuple[str, list]:
    """Transcribe audio with Whisper, return (text, segments_with_timestamps)."""
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    segments = getattr(response, "segments", []) or []
    text = response.text or ""
    return text, segments


def _build_timed_transcript(segments: list) -> str:
    """Format segments with timestamps for GPT context."""
    if not segments:
        return "No transcript available"

    lines = []
    for seg in segments:
        start = seg.get("start", 0) if isinstance(seg, dict) else getattr(seg, "start", 0)
        text = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")
        m, s = divmod(int(start), 60)
        lines.append(f"[{m:02d}:{s:02d}] {text.strip()}")
    return "\n".join(lines)


def _parse_structured_response(raw_text: str) -> DetectionResult:
    """Parse GPT structured output into DetectionResult."""
    data = json.loads(raw_text)
    events = []
    for item in data.get("events", []):
        try:
            events.append(
                DetectionEvent(
                    event_type=EventType(item["event_type"]),
                    timestamp_seconds=float(item["timestamp_seconds"]),
                    confidence=float(item.get("confidence", 0.7)),
                    description=item.get("description", ""),
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping event {item}: {e}")

    return DetectionResult(
        events=events,
        chain_used="openai",
        video_duration=data.get("video_duration"),
        raw_response=raw_text,
    )


async def _emit_progress(progress_callback, value: float) -> None:
    if not progress_callback:
        return
    try:
        ret = progress_callback(max(0.0, min(1.0, float(value))))
        if inspect.isawaitable(ret):
            await ret
    except Exception:
        return
