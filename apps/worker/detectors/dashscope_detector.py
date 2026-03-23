"""
DashScope multimodal video detection (primary chain).
Uses DashScope SDK `MultiModalConversation.call` to analyze football videos.
"""
from __future__ import annotations
import asyncio
import json
import inspect
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from apps.api.schemas.detection_schemas import DetectionResult, DetectionEvent, EventType
from apps.api.config import get_settings
from apps.api.utils.media_binaries import require_binary
from apps.worker.detectors.event_merger import (
    merge_and_filter_events as _merge_and_filter_events,
    _relabel_by_description,
    MIN_CONFIDENCE_BY_TYPE,
    EVENT_KEYWORDS,
    GOAL_NEGATIVE_KEYWORDS,
    GOAL_STRONG_POSITIVE_KEYWORDS,
    GOAL_WEAK_POSITIVE_KEYWORDS,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Error codes/messages that indicate account-level issues (no point retrying).
_FATAL_ERROR_KEYWORDS = (
    "arrearage", "access denied", "overdue", "account", "suspended",
    "quota exceeded", "billing", "payment",
)


def _is_fatal_api_error(response) -> bool:
    """Check if a DashScope response indicates an unrecoverable account error."""
    code = str(getattr(response, "code", "") or "").lower()
    message = str(getattr(response, "message", "") or "").lower()
    combined = f"{code} {message}"
    return any(kw in combined for kw in _FATAL_ERROR_KEYWORDS)

DETECTION_PROMPT = """
You are a professional football match analyst.
Analyze this football match and detect key events with high recall and high precision.

Event taxonomy:
- GOAL
- SHOT_ON_TARGET
- SHOT_BLOCKED
- SAVE
- CORNER_KICK
- FREE_KICK
- OFFSIDE
- FOUL
- SUBSTITUTION
- YELLOW_CARD
- RED_CARD
- PENALTY
- VAR
- HIGHLIGHT

Goal judgement (two-stage):
1) Physics-first: ball clearly crosses goal line, or strong indirect evidence.
2) Rule validity: no clear whistle/foul/offside/handball invalidation.
If physical evidence is strong and no invalidation evidence appears, keep GOAL.
Do NOT label an event as GOAL only because a scoreboard is visible.
Do NOT output duplicate GOAL events for the same attack sequence.
Any shot that is saved / blocked / off target / hits post-crossbar / ruled out by offside is NOT GOAL.

Return ONLY valid JSON:
{
  "events": [
    {
      "event_type": "GOAL",
      "timestamp_seconds": 234.5,
      "confidence": 0.95,
      "description": "Header goal from corner kick"
    }
  ],
  "video_duration": 5400.0
}
"""


WINDOW_PROMPT_SUFFIX = """
You are receiving sparse keyframes from one video time window.
Each frame is labeled with absolute timestamp_seconds.
Detect ONLY events that are supported by these frames.
If uncertain, lower confidence instead of inventing events.
Important precision rules:
- Only emit GOAL when visual evidence strongly supports scoring (ball in net / clear score change around play).
- If evidence is "shot but possibly saved/blocked", prefer SHOT_ON_TARGET / SHOT_BLOCKED / SAVE over GOAL.
- If shot is wide/hits post/crossbar/offside/disallowed, do not emit GOAL.
- Emit CORNER_KICK/FREE_KICK/OFFSIDE/FOUL/SUBSTITUTION only when clear visual or referee/context evidence exists.
- Avoid duplicate events for near-identical moments.
Return ONLY valid JSON with schema:
{
  "events": [
    {
      "event_type": "GOAL",
      "timestamp_seconds": 234.5,
      "confidence": 0.95,
      "description": "Header goal from corner kick"
    }
  ],
  "video_duration": 5400.0
}
"""


EVENT_TYPE_ALIASES: dict[str, EventType] = {
    "GOAL": EventType.GOAL,
    "进球": EventType.GOAL,
    "SHOT_ON_TARGET": EventType.SHOT_ON_TARGET,
    "SHOT_ON_GOAL": EventType.SHOT_ON_TARGET,
    "SHOT": EventType.SHOT_ON_TARGET,
    "射正": EventType.SHOT_ON_TARGET,
    "SHOT_BLOCKED": EventType.SHOT_BLOCKED,
    "BLOCKED_SHOT": EventType.SHOT_BLOCKED,
    "SHOT_BLOCK": EventType.SHOT_BLOCKED,
    "封堵射门": EventType.SHOT_BLOCKED,
    "SAVE": EventType.SAVE,
    "扑救": EventType.SAVE,
    "CORNER_KICK": EventType.CORNER_KICK,
    "CORNER KICK": EventType.CORNER_KICK,
    "CORNER": EventType.CORNER_KICK,
    "角球": EventType.CORNER_KICK,
    "FREE_KICK": EventType.FREE_KICK,
    "FREE KICK": EventType.FREE_KICK,
    "任意球": EventType.FREE_KICK,
    "OFFSIDE": EventType.OFFSIDE,
    "OFF SIDE": EventType.OFFSIDE,
    "越位": EventType.OFFSIDE,
    "FOUL": EventType.FOUL,
    "犯规": EventType.FOUL,
    "SUBSTITUTION": EventType.SUBSTITUTION,
    "SUB": EventType.SUBSTITUTION,
    "换人": EventType.SUBSTITUTION,
    "YELLOW_CARD": EventType.YELLOW_CARD,
    "黄牌": EventType.YELLOW_CARD,
    "RED_CARD": EventType.RED_CARD,
    "红牌": EventType.RED_CARD,
    "PENALTY": EventType.PENALTY,
    "点球": EventType.PENALTY,
    "VAR": EventType.VAR,
    "HIGHLIGHT": EventType.HIGHLIGHT,
    "精彩镜头": EventType.HIGHLIGHT,
}


async def detect_with_dashscope(
    source_path: str,
    progress_callback=None,
) -> DetectionResult:
    """
    Primary detection chain using DashScope SDK.
    Raises on failure so caller can fall back to OpenAI chain.
    """
    api_key = settings.dashscope_api_key
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY not configured")

    try:
        import dashscope
        from dashscope import MultiModalConversation

        dashscope.base_http_api_url = settings.dashscope_base_http_api_url
        model = settings.dashscope_model

        ffprobe_bin = require_binary("ffprobe")
        duration = _probe_duration(ffprobe_bin, source_path)
        file_url = f"file://{os.path.abspath(source_path)}"
        raw_chunks: list[str] = []
        direct_events: list[DetectionEvent] = []

        await _emit_progress(progress_callback, 0.05)

        messages = [
            {
                "role": "user",
                "content": [
                    {"video": file_url, "fps": 2},
                    {"text": DETECTION_PROMPT},
                ],
            }
        ]

        try:
            response = await _dashscope_call(
                multimodal_conversation_cls=MultiModalConversation,
                api_key=api_key,
                model=model,
                messages=messages,
                timeout_seconds=max(10, settings.dashscope_request_timeout_seconds),
            )
            if response.status_code == 200:
                raw_text = _extract_response_text(response)
                if raw_text:
                    raw_chunks.append(raw_text)
                    parsed_direct = _parse_detection_response(
                        raw_text,
                        chain="dashscope",
                        default_duration=duration if duration > 0 else None,
                    )
                    direct_events = parsed_direct.events
            else:
                if _is_fatal_api_error(response):
                    raise RuntimeError(
                        f"DashScope account error (aborting): "
                        f"{getattr(response, 'code', '')} - {getattr(response, 'message', '')}"
                    )
                logger.warning(
                    "DashScope direct video call failed (%s - %s), retrying with sampled keyframes.",
                    getattr(response, "code", ""),
                    getattr(response, "message", ""),
                )
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning(
                "DashScope direct video call error (%s), retrying with sampled keyframes.",
                e,
            )

        await _emit_progress(progress_callback, 0.15)

        # Windowed keyframe fallback/augmentation: improves long-video coverage.
        window_events, window_raws = await _detect_with_keyframe_windows(
            source_path=source_path,
            api_key=api_key,
            model=model,
            multimodal_conversation_cls=MultiModalConversation,
            duration=duration,
            progress_callback=progress_callback,
            progress_start=0.2,
            progress_end=0.9,
        )
        raw_chunks.extend(window_raws)

        merged_events = _merge_and_filter_events([*direct_events, *window_events], duration)
        await _emit_progress(progress_callback, 1.0)
        return DetectionResult(
            events=merged_events,
            chain_used="dashscope",
            video_duration=duration if duration > 0 else None,
            raw_response="\n\n".join(raw_chunks)[:20000] if raw_chunks else None,
        )

    except ImportError:
        raise RuntimeError("dashscope package not installed")
    except Exception as e:
        logger.warning(f"DashScope detection failed: {e}")
        raise


def _parse_detection_response(
    raw_text: str,
    chain: str,
    default_duration: Optional[float] = None,
) -> DetectionResult:
    """Parse JSON from model response, handle markdown code blocks."""
    text = _strip_markdown_fences(raw_text or "")
    events = _parse_events_from_text(text)
    data_duration = _extract_duration_from_text(text)

    return DetectionResult(
        events=events,
        chain_used=chain,
        video_duration=data_duration if data_duration is not None else default_duration,
        raw_response=raw_text,
    )


def _parse_events_from_text(text: str) -> list[DetectionEvent]:
    payloads = _extract_json_payloads(text)
    events: list[DetectionEvent] = []
    for payload in payloads:
        events.extend(_events_from_payload(payload))
    return events


def _extract_json_payloads(text: str) -> list[object]:
    payloads: list[object] = []
    stripped = text.strip()
    if not stripped:
        return payloads

    # Whole text as one JSON block.
    try:
        payloads.append(json.loads(stripped))
    except json.JSONDecodeError:
        pass

    # Line-by-line JSON objects (e.g. {"goal": true, "moment": ...})
    if not payloads:
        for line in stripped.splitlines():
            s = line.strip().rstrip(",")
            if not s:
                continue
            try:
                payloads.append(json.loads(s))
            except json.JSONDecodeError:
                continue

    # Extract first {...} block if mixed prose.
    if not payloads:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                payloads.append(json.loads(stripped[start:end + 1]))
            except json.JSONDecodeError:
                pass

    return payloads


def _events_from_payload(payload: object) -> list[DetectionEvent]:
    if isinstance(payload, list):
        out: list[DetectionEvent] = []
        for item in payload:
            out.extend(_events_from_payload(item))
        return out

    if not isinstance(payload, dict):
        return []

    # code.txt style: {"goal": true, "moment": 123.4}
    if "goal" in payload and "moment" in payload:
        if bool(payload.get("goal")):
            ts = _coerce_timestamp(payload.get("moment"))
            if ts is not None:
                return [DetectionEvent(
                    event_type=EventType.GOAL,
                    timestamp_seconds=ts,
                    confidence=0.76,
                    description="Potential goal from rule-style output",
                )]
        return []

    # Standard schema: {"events":[...]}
    raw_events = payload.get("events")
    if isinstance(raw_events, list):
        out: list[DetectionEvent] = []
        for item in raw_events:
            ev = _coerce_event(item)
            if ev is not None:
                out.append(ev)
        return out

    # Single event object.
    ev = _coerce_event(payload)
    return [ev] if ev is not None else []


def _coerce_event(item: object) -> Optional[DetectionEvent]:
    if not isinstance(item, dict):
        return None

    desc = item.get("description")
    description = str(desc).strip() if desc is not None else None
    event_type = _coerce_event_type(item.get("event_type"))
    if event_type is None and description:
        event_type = _infer_event_type_from_text(description)
    ts = _coerce_timestamp(item.get("timestamp_seconds"))
    if event_type is None or ts is None:
        return None

    try:
        confidence = float(item.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))
    return DetectionEvent(
        event_type=event_type,
        timestamp_seconds=ts,
        confidence=confidence,
        description=description or None,
    )


def _infer_event_type_from_text(text: str) -> Optional[EventType]:
    desc = (text or "").lower()
    if not desc:
        return None

    def has_any(words: tuple[str, ...]) -> bool:
        return any(w in desc for w in words)

    if has_any(EVENT_KEYWORDS[EventType.RED_CARD]):
        return EventType.RED_CARD
    if has_any(EVENT_KEYWORDS[EventType.YELLOW_CARD]):
        return EventType.YELLOW_CARD
    if has_any(EVENT_KEYWORDS[EventType.PENALTY]):
        return EventType.PENALTY
    if has_any(EVENT_KEYWORDS[EventType.VAR]):
        return EventType.VAR
    if has_any(EVENT_KEYWORDS[EventType.OFFSIDE]):
        return EventType.OFFSIDE
    if has_any(EVENT_KEYWORDS[EventType.CORNER_KICK]):
        return EventType.CORNER_KICK
    if has_any(EVENT_KEYWORDS[EventType.FREE_KICK]):
        return EventType.FREE_KICK
    if has_any(EVENT_KEYWORDS[EventType.SUBSTITUTION]):
        return EventType.SUBSTITUTION
    if has_any(EVENT_KEYWORDS[EventType.FOUL]):
        return EventType.FOUL

    has_goal_strong = has_any(GOAL_STRONG_POSITIVE_KEYWORDS)
    has_goal_weak = has_any(GOAL_WEAK_POSITIVE_KEYWORDS)
    has_goal_negative = has_any(GOAL_NEGATIVE_KEYWORDS)
    if has_goal_strong or (has_goal_weak and not has_goal_negative):
        return EventType.GOAL
    if has_any(EVENT_KEYWORDS[EventType.SAVE]):
        return EventType.SAVE
    if has_any(EVENT_KEYWORDS[EventType.SHOT_BLOCKED]):
        return EventType.SHOT_BLOCKED
    if has_any(EVENT_KEYWORDS[EventType.SHOT_ON_TARGET]):
        return EventType.SHOT_ON_TARGET
    if "highlight" in desc or "精彩" in desc:
        return EventType.HIGHLIGHT
    return None


def _coerce_event_type(raw: object) -> Optional[EventType]:
    if raw is None:
        return None
    key = str(raw).strip().upper()
    return EVENT_TYPE_ALIASES.get(key)


def _coerce_timestamp(raw: object) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", s)
    if not m:
        return None
    parts = [int(x) if x is not None else 0 for x in m.groups()]
    if m.group(3) is not None:
        hh, mm, ss = parts
        return float(hh * 3600 + mm * 60 + ss)
    mm, ss, _ = parts
    return float(mm * 60 + ss)


def _extract_duration_from_text(text: str) -> Optional[float]:
    payloads = _extract_json_payloads(text)
    for payload in payloads:
        if isinstance(payload, dict):
            dur = payload.get("video_duration")
            if isinstance(dur, (int, float)):
                return float(dur)
            if isinstance(dur, str):
                try:
                    return float(dur)
                except ValueError:
                    continue
    return None


def _extract_response_text(response) -> str:
    output = getattr(response, "output", None)
    choices = getattr(output, "choices", None) if output is not None else None
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text_val = item.get("text")
                if isinstance(text_val, str) and text_val.strip():
                    text_parts.append(text_val)
            elif isinstance(item, str) and item.strip():
                text_parts.append(item)
        return "\n".join(text_parts)
    return ""


def _strip_markdown_fences(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2:
            if lines[-1].strip() == "```":
                return "\n".join(lines[1:-1]).strip()
            return "\n".join(lines[1:]).strip()
    return s


async def _detect_with_keyframe_windows(
    source_path: str,
    api_key: str,
    model: str,
    multimodal_conversation_cls,
    duration: float,
    progress_callback=None,
    progress_start: float = 0.2,
    progress_end: float = 0.9,
) -> tuple[list[DetectionEvent], list[str]]:
    ffmpeg_bin = require_binary("ffmpeg")
    temp_root = tempfile.mkdtemp(prefix="dashscope_windows_")

    try:
        windows = _build_windows(
            duration=duration,
            window_seconds=max(30, settings.dashscope_window_seconds),
            max_windows=max(1, settings.dashscope_max_windows),
            overlap_ratio=max(0.0, min(0.8, settings.dashscope_window_overlap_ratio)),
        )
        total = len(windows)
        if total == 0:
            return [], []

        max_parallel = max(1, int(settings.dashscope_window_concurrency))
        semaphore = asyncio.Semaphore(max_parallel)

        async def process_window(idx: int, start: float, end: float) -> tuple[int, list[DetectionEvent], Optional[str]]:
            async with semaphore:
                try:
                    frames = await asyncio.to_thread(
                        _sample_window_frames,
                        ffmpeg_bin,
                        source_path,
                        temp_root,
                        idx,
                        start,
                        end,
                        max(2, settings.dashscope_frames_per_window),
                    )
                except Exception as e:
                    logger.warning("Frame extraction failed for window %s: %s", idx, e)
                    return idx, [], None

                if not frames:
                    return idx, [], None

                content: list[dict] = []
                content.append({"text": f"Window [{start:.2f}, {end:.2f}] seconds"})
                for i, (ts, frame_path) in enumerate(frames):
                    content.append({"text": f"Frame {i + 1}, timestamp_seconds={ts:.2f}"})
                    content.append({"image": f"file://{frame_path}"})
                content.append({"text": WINDOW_PROMPT_SUFFIX})

                try:
                    response = await _dashscope_call(
                        multimodal_conversation_cls=multimodal_conversation_cls,
                        api_key=api_key,
                        model=model,
                        messages=[{"role": "user", "content": content}],
                        timeout_seconds=max(10, settings.dashscope_request_timeout_seconds),
                    )
                except Exception as e:
                    logger.warning("DashScope keyframe window %s timeout/error: %s", idx, e)
                    return idx, [], None

                if response.status_code != 200:
                    logger.warning(
                        "DashScope keyframe window %s failed: %s - %s",
                        idx,
                        getattr(response, "code", ""),
                        getattr(response, "message", ""),
                    )
                    return idx, [], None

                raw = _extract_response_text(response)
                if not raw:
                    return idx, [], None

                parsed = _parse_detection_response(
                    raw,
                    chain="dashscope",
                    default_duration=duration if duration > 0 else None,
                )
                return idx, parsed.events, raw

        tasks = [
            asyncio.create_task(process_window(idx, start, end))
            for idx, (start, end) in enumerate(windows)
        ]

        done = 0
        indexed_results: list[tuple[int, list[DetectionEvent], Optional[str]]] = []
        for finished in asyncio.as_completed(tasks):
            indexed_results.append(await finished)
            done += 1
            p = progress_start + (progress_end - progress_start) * (done / total)
            await _emit_progress(progress_callback, p)

        events: list[DetectionEvent] = []
        raw_chunks: list[str] = []
        for _, evs, raw in sorted(indexed_results, key=lambda x: x[0]):
            events.extend(evs)
            if raw:
                raw_chunks.append(raw)
        return events, raw_chunks
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


async def _dashscope_call(
    multimodal_conversation_cls,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout_seconds: int,
):
    return await asyncio.wait_for(
        asyncio.to_thread(
            multimodal_conversation_cls.call,
            api_key=api_key,
            model=model,
            messages=messages,
        ),
        timeout=max(1, int(timeout_seconds)),
    )


async def _emit_progress(progress_callback, value: float) -> None:
    if not progress_callback:
        return
    try:
        ret = progress_callback(max(0.0, min(1.0, float(value))))
        if inspect.isawaitable(ret):
            await ret
    except Exception as e:
        logger.debug("Ignore progress callback error: %s", e)


def _build_windows(
    duration: float,
    window_seconds: int,
    max_windows: int,
    overlap_ratio: float = 0.0,
) -> list[tuple[float, float]]:
    if duration <= 0:
        return [(0.0, float(window_seconds))]

    window = max(10.0, float(window_seconds))
    overlap = max(0.0, min(0.8, float(overlap_ratio)))
    stride = max(1.0, window * (1.0 - overlap))

    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + window)
        windows.append((round(start, 2), round(end, 2)))
        if end >= duration:
            break
        start += stride

    if not windows:
        return [(0.0, round(duration, 2))]

    if len(windows) <= max_windows:
        return windows

    # Too many windows: down-sample across full duration to keep tail coverage.
    if max_windows <= 1:
        return [(0.0, round(min(duration, window), 2))]

    max_start = max(0.0, duration - window)
    sampled: list[tuple[float, float]] = []
    for i in range(max_windows):
        ratio = i / (max_windows - 1)
        s = round(max_start * ratio, 2)
        e = round(min(duration, s + window), 2)
        sampled.append((s, e))

    deduped: list[tuple[float, float]] = []
    for pair in sampled:
        if not deduped or pair != deduped[-1]:
            deduped.append(pair)
    return deduped


def _sample_window_frames(
    ffmpeg_bin: str,
    source_path: str,
    temp_root: str,
    window_index: int,
    start: float,
    end: float,
    frames_per_window: int,
) -> list[tuple[float, str]]:
    window_dir = os.path.join(temp_root, f"w_{window_index:03d}")
    os.makedirs(window_dir, exist_ok=True)
    span = max(1.0, end - start)
    step = span / (frames_per_window + 1)
    times = [round(start + step * (i + 1), 2) for i in range(frames_per_window)]

    frames: list[tuple[float, str]] = []
    for i, ts in enumerate(times):
        frame_path = os.path.join(window_dir, f"f_{i:03d}.jpg")
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", str(ts),
            "-i", source_path,
            "-frames:v", "1",
            "-q:v", "4",
            frame_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(frame_path):
            frames.append((ts, frame_path))
    return frames


def _sample_video_frames(source_path: str, max_frames: int = 8) -> tuple[str, list[tuple[float, str]]]:
    ffmpeg_bin = require_binary("ffmpeg")
    ffprobe_bin = require_binary("ffprobe")

    duration = _probe_duration(ffprobe_bin, source_path)
    if duration <= 0:
        timestamps = [0.0]
    else:
        frame_count = max(3, min(max_frames, int(duration // 120) + 3))
        step = duration / (frame_count + 1)
        timestamps = [round(step * (i + 1), 2) for i in range(frame_count)]

    temp_dir = tempfile.mkdtemp(prefix="dashscope_frames_")
    frames: list[tuple[float, str]] = []
    for i, ts in enumerate(timestamps):
        frame_path = os.path.join(temp_dir, f"frame_{i:03d}.jpg")
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", str(ts),
            "-i", source_path,
            "-frames:v", "1",
            "-q:v", "4",
            frame_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(frame_path):
            frames.append((ts, frame_path))

    if not frames:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("Failed to extract keyframes for DashScope fallback")
    return temp_dir, frames


def _probe_duration(ffprobe_bin: str, source_path: str) -> float:
    cmd = [
        ffprobe_bin, "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        source_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return 0.0
    try:
        return float((result.stdout or "0").strip())
    except ValueError:
        return 0.0
