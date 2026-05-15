"""
Alibaba audio-semantic fallback detection chain.

Legacy module path is kept as ``openai_detector`` to avoid wider refactors, but this
secondary chain now runs fully on Alibaba Cloud Model Studio using:
- Qwen3-ASR-Flash for audio transcription
- qwen-plus for structured football event extraction
"""
from __future__ import annotations
import inspect
import json
import logging
import os
import subprocess
import tempfile
from typing import Optional

import httpx
from openai import OpenAI

from apps.api.schemas.detection_schemas import DetectionResult, DetectionEvent, EventType
from apps.api.config import get_settings
from apps.api.utils.media_binaries import require_binary
from apps.worker.detectors.dashscope_detector import _strip_markdown_fences

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
identify all key football events with precise timestamps and return JSON only.
Extract events of types: GOAL, SHOT_ON_TARGET, SHOT_BLOCKED, SAVE, CORNER_KICK, FREE_KICK, OFFSIDE, FOUL, SUBSTITUTION, YELLOW_CARD, RED_CARD, PENALTY, VAR, HIGHLIGHT.
Also detect SHOT_BLOCKED when a defender clearly blocks a shot attempt.
Use context clues from commentary (e.g. "GOAAAL!", "Yellow card", "Penalty") to determine event types.
Do NOT classify as GOAL if commentary indicates saved, blocked, off target, hits post/crossbar, or offside/disallowed.
Estimate timestamp_seconds based on commentary timing.
Output JSON with this exact top-level shape:
{
  "events": [
    {
      "event_type": "GOAL",
      "timestamp_seconds": 12.3,
      "confidence": 0.91,
      "description": "Goal scored from close range"
    }
  ],
  "video_duration": 0
}
"""


async def detect_with_openai(
    source_path: str,
    progress_callback=None,
) -> DetectionResult:
    """Legacy entry point for the Alibaba audio-semantic fallback chain."""
    api_key = settings.dashscope_api_key
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY not configured")

    client = OpenAI(
        api_key=api_key,
        base_url=settings.dashscope_compatible_base_url,
    )

    # Step 1: Extract audio (use tempfile for parallel safety)
    await _emit_progress(progress_callback, 0.05)

    tmp_fd, audio_path = tempfile.mkstemp(suffix=".mp3", prefix="qwen_audio_")
    os.close(tmp_fd)
    _extract_audio(source_path, audio_path)

    await _emit_progress(progress_callback, 0.1)

    # Step 2: Transcribe with Qwen ASR
    transcript_text, segments, asr_raw = await _transcribe_audio(audio_path)

    await _emit_progress(progress_callback, 0.2)

    # Step 3: Build timed transcript
    timed_text = _build_timed_transcript(transcript_text, segments)

    # Step 4: Extract events with qwen-plus structured JSON output
    await _emit_progress(progress_callback, 0.25)

    response = client.chat.completions.create(
        model=settings.dashscope_audio_text_model,
        response_format={
            "type": "json_object",
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
    result.chain_used = "qwen-audio"
    if asr_raw:
        result.raw_response = f"[ASR]\n{asr_raw}\n\n[EVENTS]\n{raw_text}"

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


async def _transcribe_audio(audio_path: str) -> tuple[str, list[dict], str]:
    """
    Transcribe audio with DashScope synchronous ASR.

    Alibaba's DashScope synchronous ASR supports absolute local file paths for
    Qwen3-ASR-Flash, which lets this chain keep the existing local tmp-file flow.
    """
    api_key = settings.dashscope_api_key
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY not configured")

    api_url = (
        settings.dashscope_base_http_api_url.rstrip("/")
        + "/services/audio/asr/transcription"
    )
    payload = {
        "model": settings.dashscope_audio_asr_model,
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": [
                        {
                            "text": "Transcribe the audio faithfully and preserve natural sentence boundaries."
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "audio": os.path.abspath(audio_path)
                        }
                    ],
                },
            ]
        },
        "parameters": {
            "asr_options": {
                "enable_itn": False,
            }
        },
    }

    timeout_seconds = max(30, int(settings.dashscope_request_timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    try:
        data = response.json()
    except ValueError as e:
        raise RuntimeError(
            f"DashScope ASR returned non-JSON response: {response.text[:500]}"
        ) from e

    if response.status_code != 200:
        raise RuntimeError(
            "DashScope ASR failed: "
            + str(data.get("message") or data.get("code") or response.text[:500])
        )

    return _parse_dashscope_asr_response(data)


def _build_timed_transcript(transcript_text: str, segments: list[dict]) -> str:
    """Format segments with timestamps for GPT context."""
    if not segments:
        return transcript_text.strip() or "No transcript available"

    lines = []
    for seg in segments:
        start = seg.get("start", 0) if isinstance(seg, dict) else getattr(seg, "start", 0)
        text = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")
        m, s = divmod(int(start), 60)
        lines.append(f"[{m:02d}:{s:02d}] {text.strip()}")
    return "\n".join(lines)


def _parse_structured_response(raw_text: str) -> DetectionResult:
    """Parse GPT structured output into DetectionResult."""
    data = json.loads(_strip_markdown_fences(raw_text))
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
        chain_used="qwen-audio",
        video_duration=data.get("video_duration"),
        raw_response=raw_text,
    )


def _parse_dashscope_asr_response(data: dict) -> tuple[str, list[dict], str]:
    """
    Parse DashScope ASR response.

    The synchronous ASR API may return sentence-level timestamps in transcript
    payloads. If timestamps are unavailable, we still keep the plain transcript
    text so the text model can do best-effort extraction.
    """
    payload = data.get("output") if isinstance(data.get("output"), dict) else data
    transcripts = payload.get("transcripts") if isinstance(payload, dict) else None

    segments: list[dict] = []
    transcript_parts: list[str] = []

    if isinstance(transcripts, list):
        for transcript in transcripts:
            if not isinstance(transcript, dict):
                continue

            transcript_text = str(transcript.get("text") or "").strip()
            sentences = transcript.get("sentences")
            if isinstance(sentences, list) and sentences:
                for sentence in sentences:
                    if not isinstance(sentence, dict):
                        continue
                    text = str(sentence.get("text") or "").strip()
                    if not text:
                        continue
                    begin_ms = sentence.get("begin_time", 0)
                    end_ms = sentence.get("end_time", begin_ms)
                    try:
                        start_seconds = max(0.0, float(begin_ms) / 1000.0)
                    except (TypeError, ValueError):
                        start_seconds = 0.0
                    try:
                        end_seconds = max(start_seconds, float(end_ms) / 1000.0)
                    except (TypeError, ValueError):
                        end_seconds = start_seconds
                    segments.append(
                        {
                            "start": round(start_seconds, 3),
                            "end": round(end_seconds, 3),
                            "text": text,
                        }
                    )
                    transcript_parts.append(text)
            elif transcript_text:
                transcript_parts.append(transcript_text)

    if not transcript_parts:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                transcript_parts.append(content.strip())

    transcript_text = " ".join(part for part in transcript_parts if part).strip()
    return transcript_text, segments, json.dumps(data, ensure_ascii=False)


async def _emit_progress(progress_callback, value: float) -> None:
    if not progress_callback:
        return
    try:
        ret = progress_callback(max(0.0, min(1.0, float(value))))
        if inspect.isawaitable(ret):
            await ret
    except Exception:
        return
