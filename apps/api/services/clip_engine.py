"""
ClipEngine — converts DetectionResult events into Timeline/Clip DB records
and assembles the final video using ffmpeg/moviepy.

Responsibilities:
- Deduplication of nearby events (time window)
- Auto-build timelines from events
- Merge and encode video segments
- Transition application (fade in/out)
- Event subtitle overlay (drawtext)
"""
from __future__ import annotations
import os
import json
import uuid
import logging
import subprocess
import re
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from apps.api.config import get_settings
from apps.api.schemas.detection_schemas import DetectionResult, DetectionEvent, EventType, EVENT_PRIORITY
from apps.api.utils.media_binaries import find_binary, require_binary

logger = logging.getLogger(__name__)
settings = get_settings()
_DRAWTEXT_SUPPORTED_CACHE: Optional[bool] = None
_FFMPEG_FILTERS_CACHE: Optional[set[str]] = None

TRANSITION_FILTERS = {
    "cut": None,
    "fade": "fade=t=in:st=0:d={dur},fade=t=out:st={out_start}:d={dur}",
    "wipe": "wipe",
    "slide": "slide",
    "circle": "circleopen",
}

SHOT_LIKE_EVENTS = {
    EventType.SHOT_ON_TARGET,
    EventType.SHOT_BLOCKED,
    EventType.SAVE,
}

MAX_CLIPS_DEFAULT = 28
SHOT_RATIO_MAX_DEFAULT = 0.6
PER_TYPE_CAP: dict[EventType, int] = {
    EventType.GOAL: 8,
    EventType.PENALTY: 4,
    EventType.RED_CARD: 3,
    EventType.VAR: 4,
    EventType.CORNER_KICK: 4,
    EventType.FREE_KICK: 4,
    EventType.OFFSIDE: 4,
    EventType.FOUL: 4,
    EventType.SHOT_ON_TARGET: 6,
    EventType.SHOT_BLOCKED: 5,
    EventType.SAVE: 6,
    EventType.SUBSTITUTION: 3,
    EventType.YELLOW_CARD: 4,
    EventType.HIGHLIGHT: 5,
}

EVENT_DISPLAY_NAME_ZH: dict[EventType, str] = {
    EventType.GOAL: "进球",
    EventType.SHOT_ON_TARGET: "射正",
    EventType.SHOT_BLOCKED: "射门被封堵",
    EventType.SAVE: "扑救",
    EventType.CORNER_KICK: "角球",
    EventType.FREE_KICK: "任意球",
    EventType.OFFSIDE: "越位",
    EventType.FOUL: "犯规",
    EventType.SUBSTITUTION: "换人",
    EventType.YELLOW_CARD: "黄牌",
    EventType.RED_CARD: "红牌",
    EventType.PENALTY: "点球",
    EventType.VAR: "VAR回看",
    EventType.HIGHLIGHT: "精彩镜头",
}

# Event-specific context windows (seconds): capture lead-up + aftermath.
EVENT_BUFFER_SECONDS: dict[EventType, tuple[float, float]] = {
    EventType.GOAL: (8.0, 9.0),
    EventType.SHOT_ON_TARGET: (6.0, 6.5),
    EventType.SHOT_BLOCKED: (6.0, 6.0),
    EventType.SAVE: (6.0, 7.0),
    EventType.CORNER_KICK: (7.0, 8.0),
    EventType.FREE_KICK: (7.0, 8.0),
    EventType.OFFSIDE: (6.0, 7.0),
    EventType.FOUL: (8.0, 12.0),
    EventType.SUBSTITUTION: (7.0, 12.0),
    EventType.YELLOW_CARD: (8.0, 12.0),
    EventType.RED_CARD: (10.0, 16.0),
    EventType.PENALTY: (10.0, 12.0),
    EventType.VAR: (12.0, 16.0),
    EventType.HIGHLIGHT: (7.0, 8.0),
}

CONTEXT_FOLLOW_EVENT_TYPES = {
    EventType.FOUL,
    EventType.OFFSIDE,
    EventType.PENALTY,
    EventType.FREE_KICK,
}
FOLLOW_UP_DECISION_TYPES = {
    EventType.YELLOW_CARD,
    EventType.RED_CARD,
    EventType.VAR,
    EventType.PENALTY,
}
FOLLOW_UP_LOOKAHEAD_SECONDS = 22.0


def _event_source_key(event: DetectionEvent) -> str:
    metadata = event.metadata or {}
    source_key = metadata.get("source_index")
    return str(source_key) if source_key is not None else "__single__"


# ─── Deduplication ────────────────────────────────────────────────────────────

def deduplicate_events(
    events: list[DetectionEvent],
    window_seconds: Optional[float] = None,
) -> list[DetectionEvent]:
    """Remove duplicate events within time window, keep highest confidence."""
    if not events:
        return []

    window = window_seconds or settings.event_dedup_window_seconds
    sorted_events = sorted(events, key=lambda e: e.timestamp_seconds)
    result: list[DetectionEvent] = []

    for event in sorted_events:
        overlap = next(
            (
                r for r in result
                if r.event_type == event.event_type
                and _event_source_key(r) == _event_source_key(event)
                and abs(r.timestamp_seconds - event.timestamp_seconds) < window
            ),
            None,
        )
        if overlap is None:
            result.append(event)
        elif event.confidence > overlap.confidence:
            result.remove(overlap)
            result.append(event)

    return result


# ─── Clip Plan Generation ─────────────────────────────────────────────────────

def build_clip_plan(
    detection_result: DetectionResult,
    pre_buffer: Optional[float] = None,
    post_buffer: Optional[float] = None,
) -> dict:
    """Convert detection events → ordered clip segments with metadata."""
    pre = pre_buffer or settings.clip_pre_buffer_seconds
    post = post_buffer or settings.clip_post_buffer_seconds
    duration = detection_result.video_duration or float("inf")

    deduped = deduplicate_events(detection_result.events)

    # Sort primarily by timeline order (time), with priority as tie-breaker.
    sorted_events = sorted(
        deduped,
        key=lambda e: (e.timestamp_seconds, -EVENT_PRIORITY.get(e.event_type, 0)),
    )
    selected_events = _select_diverse_events(
        sorted_events,
        max_clips=MAX_CLIPS_DEFAULT,
        max_shot_ratio=SHOT_RATIO_MAX_DEFAULT,
    )

    clips = []
    for idx, event in enumerate(selected_events):
        start, end = _compute_event_clip_window(
            event=event,
            ordered_events=selected_events,
            event_index=idx,
            default_pre=pre,
            default_post=post,
            duration=duration,
        )
        if end <= start:
            continue

        metadata = event.metadata or {}

        clip = {
            "order_index": idx,
            "title": f"{EVENT_DISPLAY_NAME_ZH.get(event.event_type, event.event_type.value)} · {_fmt_time(event.timestamp_seconds)}",
            "event_type": event.event_type.value,
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "confidence": event.confidence,
            "description": event.description,
            "transition_type": _suggest_transition(event.event_type.value),
            "transition_duration": 0.5,
        }

        # Preserve source linkage for multi-source jobs.
        if metadata.get("source_index") is not None:
            clip["source_index"] = metadata.get("source_index")
        if metadata.get("source_name"):
            clip["source_name"] = metadata.get("source_name")
        if metadata.get("source_path"):
            clip["source_path"] = metadata.get("source_path")

        clips.append(clip)

    return {
        "chain_used": detection_result.chain_used,
        "total_events": len(deduped),
        "clips": clips,
        "ai_summary": (
            f"Detected {len(deduped)} events, selected {len(selected_events)} diverse moments, "
            f"generated {len(clips)} clips"
        ),
    }


def _compute_event_clip_window(
    event: DetectionEvent,
    ordered_events: list[DetectionEvent],
    event_index: int,
    default_pre: float,
    default_post: float,
    duration: float,
) -> tuple[float, float]:
    base_pre, base_post = EVENT_BUFFER_SECONDS.get(event.event_type, (default_pre, default_post))
    pre = max(default_pre, base_pre)
    post = max(default_post, base_post)

    start = max(0.0, event.timestamp_seconds - pre)
    end = min(duration, event.timestamp_seconds + post)

    # Include downstream referee/decision context for foul-like incidents.
    if event.event_type in CONTEXT_FOLLOW_EVENT_TYPES:
        for next_event in ordered_events[event_index + 1 :]:
            delta = next_event.timestamp_seconds - event.timestamp_seconds
            if delta < 0:
                continue
            if delta > FOLLOW_UP_LOOKAHEAD_SECONDS:
                break
            if next_event.event_type not in FOLLOW_UP_DECISION_TYPES:
                continue
            _, follow_post = EVENT_BUFFER_SECONDS.get(next_event.event_type, (default_pre, default_post))
            end = max(end, min(duration, next_event.timestamp_seconds + max(default_post, follow_post * 0.75)))

    return round(start, 2), round(end, 2)


def _select_diverse_events(
    events: list[DetectionEvent],
    max_clips: int,
    max_shot_ratio: float,
) -> list[DetectionEvent]:
    if not events:
        return []

    capped_events: list[DetectionEvent] = []
    per_type_counts: dict[EventType, int] = {}
    deferred_shots: list[DetectionEvent] = []

    for i, event in enumerate(events):
        if len(capped_events) >= max_clips:
            break

        event_type = event.event_type
        if per_type_counts.get(event_type, 0) >= PER_TYPE_CAP.get(event_type, 6):
            continue

        is_shot = event_type in SHOT_LIKE_EVENTS
        current_shots = sum(1 for e in capped_events if e.event_type in SHOT_LIKE_EVENTS)
        projected_total = len(capped_events) + 1
        projected_shot_ratio = (current_shots + 1) / max(1, projected_total)

        remaining_non_shot = sum(
            1
            for e in events[i + 1 :]
            if e.event_type not in SHOT_LIKE_EVENTS
        )
        if is_shot and projected_shot_ratio > max_shot_ratio and remaining_non_shot > 0:
            deferred_shots.append(event)
            continue

        capped_events.append(event)
        per_type_counts[event_type] = per_type_counts.get(event_type, 0) + 1

    if len(capped_events) < max_clips and deferred_shots:
        for event in deferred_shots:
            if len(capped_events) >= max_clips:
                break
            event_type = event.event_type
            if per_type_counts.get(event_type, 0) >= PER_TYPE_CAP.get(event_type, 6):
                continue
            capped_events.append(event)
            per_type_counts[event_type] = per_type_counts.get(event_type, 0) + 1

    return sorted(capped_events, key=lambda e: (e.timestamp_seconds, -EVENT_PRIORITY.get(e.event_type, 0)))


def _suggest_transition(event_type: str) -> str:
    """AI-suggested default transition per event type."""
    mapping = {
        "GOAL": "fade",
        "RED_CARD": "wipe",
        "PENALTY": "fade",
        "VAR": "slide",
        "CORNER_KICK": "slide",
        "FREE_KICK": "fade",
        "OFFSIDE": "cut",
        "FOUL": "cut",
        "SUBSTITUTION": "wipe",
        "SAVE": "cut",
        "SHOT_BLOCKED": "cut",
    }
    return mapping.get(event_type, "cut")


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ─── Subtitle / Drawtext Helpers ──────────────────────────────────────────────

_CHINESE_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
]


def _find_chinese_font() -> Optional[str]:
    """Search for a CJK-capable font on the system."""
    for path in _CHINESE_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _ffmpeg_filters(ffmpeg_bin: str) -> set[str]:
    global _FFMPEG_FILTERS_CACHE
    if _FFMPEG_FILTERS_CACHE is not None:
        return _FFMPEG_FILTERS_CACHE
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        names = set(re.findall(r"\b([a-zA-Z0-9_]+)\b", output))
        _FFMPEG_FILTERS_CACHE = names
    except Exception as e:
        logger.warning("Could not probe ffmpeg filters: %s", e)
        _FFMPEG_FILTERS_CACHE = set()
    return _FFMPEG_FILTERS_CACHE


def _ffmpeg_supports_filter(ffmpeg_bin: str, filter_name: str) -> bool:
    return filter_name in _ffmpeg_filters(ffmpeg_bin)


def _ffmpeg_supports_drawtext(ffmpeg_bin: str) -> bool:
    """Detect whether current ffmpeg build has drawtext filter support."""
    global _DRAWTEXT_SUPPORTED_CACHE
    if _DRAWTEXT_SUPPORTED_CACHE is not None:
        return _DRAWTEXT_SUPPORTED_CACHE

    _DRAWTEXT_SUPPORTED_CACHE = _ffmpeg_supports_filter(ffmpeg_bin, "drawtext")

    if not _DRAWTEXT_SUPPORTED_CACHE:
        logger.warning("ffmpeg drawtext filter unavailable; will use subtitle overlay fallback")
    return _DRAWTEXT_SUPPORTED_CACHE


def _escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext filter."""
    if not text:
        return ""
    # Keep escaping minimal after sanitization.
    result = text.replace("\\", "\\\\")
    result = result.replace("'", "\\'")
    result = result.replace("%", "")
    return result


def _sanitize_subtitle_text(text: str, max_len: int = 96) -> str:
    """
    Remove drawtext-risky special chars to keep ffmpeg filter stable.
    User requirement: prefer stripping special symbols instead of keeping them.
    """
    if not text:
        return ""

    s = text.replace("\n", " ").replace("\r", " ").strip()
    for ch in ("\\", ":", ";", "=", ",", "'", '"', "[", "]", "{", "}", "%"):
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


def _extract_subtitle_texts(clip: dict) -> tuple[str, str]:
    title = str(clip.get("title") or "").strip()
    description = str(clip.get("description") or "").strip()

    if not description:
        notes = clip.get("notes")
        if isinstance(notes, str) and notes:
            try:
                payload = json.loads(notes)
                if isinstance(payload, dict):
                    description = str(payload.get("description") or "").strip()
            except (json.JSONDecodeError, TypeError):
                pass

    title = _sanitize_subtitle_text(title or "精彩片段", max_len=40)
    description = _sanitize_subtitle_text(description, max_len=96)
    return title, description


def _probe_video_dimensions(ffprobe_bin: str, source_path: str) -> tuple[int, int]:
    cmd = [
        ffprobe_bin, "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        source_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return 1920, 1080
    raw = (result.stdout or "").strip()
    if "x" not in raw:
        return 1920, 1080
    try:
        w_str, h_str = raw.split("x", 1)
        w = max(320, int(float(w_str)))
        h = max(180, int(float(h_str)))
        return w, h
    except Exception:
        return 1920, 1080


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = (bbox[2] - bbox[0]) if bbox else 0
        if current and width > max_width:
            lines.append(current)
            current = ch
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _render_subtitle_overlay_png(
    clip: dict,
    width: int,
    height: int,
    font_path: Optional[str],
    output_png_path: str,
) -> bool:
    title, description = _extract_subtitle_texts(clip)
    if not title and not description:
        return False

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    try:
        title_font = ImageFont.truetype(font_path, size=max(22, int(height * 0.035))) if font_path else ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()
    try:
        body_font = ImageFont.truetype(font_path, size=max(16, int(height * 0.024))) if font_path else ImageFont.load_default()
    except Exception:
        body_font = ImageFont.load_default()

    margin_x = max(20, int(width * 0.04))
    max_text_width = width - (margin_x * 2)

    # Title block (top center)
    if title:
        title_lines = _wrap_text(draw, title, title_font, max_text_width)[:2]
        title_text = "\n".join(title_lines)
        bbox = draw.multiline_textbbox((0, 0), title_text, font=title_font, spacing=4, align="center")
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (width - tw) // 2
        ty = max(20, int(height * 0.04))
        pad = 10
        draw.rectangle((tx - pad, ty - pad, tx + tw + pad, ty + th + pad), fill=(0, 0, 0, 165))
        draw.multiline_text((tx, ty), title_text, font=title_font, fill=(255, 255, 255, 255), spacing=4, align="center")

    # Description block (bottom center)
    if description:
        body_lines = _wrap_text(draw, description, body_font, max_text_width)[:3]
        body_text = "\n".join(body_lines)
        bbox = draw.multiline_textbbox((0, 0), body_text, font=body_font, spacing=4, align="center")
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        bx = (width - bw) // 2
        by = height - bh - max(28, int(height * 0.06))
        pad = 12
        draw.rectangle((bx - pad, by - pad, bx + bw + pad, by + bh + pad), fill=(0, 0, 0, 140))
        draw.multiline_text((bx, by), body_text, font=body_font, fill=(255, 255, 255, 255), spacing=4, align="center")

    image.save(output_png_path, format="PNG")
    return True


def _segment_timeout_seconds(duration: float) -> int:
    """
    Adaptive timeout for segment encoding.
    High-res sources with subtitle overlay can be much slower than realtime.
    """
    d = max(1.0, float(duration))
    return max(300, int(180 + d * 25))


def _build_subtitle_filters(
    clip: dict,
    duration: float,
    font_path: Optional[str],
) -> list[str]:
    """
    Build drawtext filter entries for event title and description.
    - Title (e.g. "进球 · 12:34") at top-center, shown for first 4s
    - Description at bottom-center with box background, full duration
    """
    filters: list[str] = []
    title, description = _extract_subtitle_texts(clip)

    font_spec = f"fontfile='{font_path}':" if font_path else ""
    title_show_duration = min(4.0, duration)

    if title:
        safe_title = _sanitize_subtitle_text(title, max_len=40)
        escaped_title = _escape_drawtext(safe_title)
        filters.append(
            f"drawtext={font_spec}"
            f"text='{escaped_title}':"
            f"fontsize=36:fontcolor=white:"
            f"borderw=2:bordercolor=black:"
            f"x=(w-text_w)/2:y=40:"
            f"enable='between(t,0,{title_show_duration:.1f})'"
        )

    if description:
        safe_desc = _sanitize_subtitle_text(description, max_len=96)
        escaped_desc = _escape_drawtext(safe_desc)
        filters.append(
            f"drawtext={font_spec}"
            f"text='{escaped_desc}':"
            f"fontsize=24:fontcolor=white:"
            f"box=1:boxcolor=black@0.5:boxborderw=6:"
            f"x=(w-text_w)/2:y=h-60:"
            f"enable='between(t,0,{duration:.1f})'"
        )

    return filters


# ─── Video Assembly ───────────────────────────────────────────────────────────

def assemble_video(
    source_path: str,
    clips: list[dict],
    output_path: str,
    progress_callback=None,
) -> str:
    """
    Use ffmpeg to cut and concatenate clips with transition effects and subtitles.
    clips: list of {start_time, end_time, transition_type, transition_duration, title, description}
    Returns output_path on success.
    """
    if not clips:
        raise ValueError("No clips to assemble")

    ffmpeg_bin = require_binary("ffmpeg")
    ffprobe_bin = require_binary("ffprobe")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    drawtext_supported = _ffmpeg_supports_drawtext(ffmpeg_bin)
    overlay_supported = _ffmpeg_supports_filter(ffmpeg_bin, "overlay")
    if not drawtext_supported and not overlay_supported:
        raise RuntimeError(
            "Current ffmpeg has neither drawtext nor overlay filter; cannot render required subtitles."
        )

    font_path: Optional[str] = None
    font_path = _find_chinese_font()
    if font_path:
        logger.info("Using CJK font for subtitles: %s", font_path)
    else:
        logger.warning("No CJK font found — subtitles may not render Chinese characters")

    # Step 1: extract individual segments with transition + subtitle filters
    temp_dir = os.path.join(os.path.dirname(output_path), "_tmp_" + str(uuid.uuid4())[:8])
    os.makedirs(temp_dir, exist_ok=True)
    segment_paths = []
    source_size_cache: dict[str, tuple[int, int]] = {}

    try:
        for i, clip in enumerate(clips):
            seg_path = os.path.join(temp_dir, f"seg_{i:04d}.mp4")
            start = clip["start_time"]
            duration = clip["end_time"] - clip["start_time"]
            if duration <= 0:
                continue
            clip_source_path = _resolve_clip_source_path(clip, source_path)

            # ── Build video filter chain ──────────────────────────
            vf_parts: list[str] = []
            af_parts: list[str] = []

            transition_type = (clip.get("transition_type") or "cut").lower()
            transition_dur = float(clip.get("transition_duration") or 0.5)
            # Clamp transition duration to max 1/3 of segment
            transition_dur = min(transition_dur, duration / 3.0)

            if transition_type != "cut" and transition_dur > 0:
                # Fade-in at start
                vf_parts.append(f"fade=t=in:st=0:d={transition_dur:.2f}")
                af_parts.append(f"afade=t=in:st=0:d={transition_dur:.2f}")
                # Fade-out at end
                out_start = max(0, duration - transition_dur)
                vf_parts.append(f"fade=t=out:st={out_start:.2f}:d={transition_dur:.2f}")
                af_parts.append(f"afade=t=out:st={out_start:.2f}:d={transition_dur:.2f}")

            # Subtitle is required: try drawtext first, then PNG overlay fallback.
            modes: list[str] = []
            if drawtext_supported:
                modes.append("drawtext")
            if overlay_supported:
                modes.append("overlay")

            segment_ok = False
            last_err = ""
            for mode in modes:
                mode_vf_parts = list(vf_parts)
                cmd = [
                    ffmpeg_bin, "-y",
                    "-ss", str(start),
                    "-t", str(duration),
                    "-i", clip_source_path,
                ]

                if mode == "drawtext":
                    subtitle_filters = _build_subtitle_filters(clip, duration, font_path)
                    mode_vf_parts.extend(subtitle_filters)
                    if mode_vf_parts:
                        cmd.extend(["-vf", ",".join(mode_vf_parts)])
                    if af_parts:
                        cmd.extend(["-af", ",".join(af_parts)])
                    cmd.extend([
                        "-c:v", "libx264", "-preset", "veryfast",
                        "-c:a", "aac",
                        "-pix_fmt", "yuv420p",
                        "-avoid_negative_ts", "make_zero",
                        seg_path,
                    ])
                else:
                    if clip_source_path not in source_size_cache:
                        source_size_cache[clip_source_path] = _probe_video_dimensions(ffprobe_bin, clip_source_path)
                    width, height = source_size_cache[clip_source_path]
                    overlay_png = os.path.join(temp_dir, f"overlay_{i:04d}.png")
                    overlay_ready = _render_subtitle_overlay_png(
                        clip=clip,
                        width=width,
                        height=height,
                        font_path=font_path,
                        output_png_path=overlay_png,
                    )
                    if not overlay_ready:
                        last_err = "overlay subtitle image generation returned empty content"
                        continue

                    cmd.extend(["-loop", "1", "-t", str(duration), "-i", overlay_png])
                    base_chain = ",".join(mode_vf_parts)
                    if base_chain:
                        filter_complex = f"[0:v]{base_chain}[v0];[v0][1:v]overlay=0:0[vout]"
                    else:
                        filter_complex = "[0:v][1:v]overlay=0:0[vout]"
                    cmd.extend([
                        "-filter_complex", filter_complex,
                        "-map", "[vout]",
                        "-map", "0:a?",
                    ])
                    if af_parts:
                        cmd.extend(["-af", ",".join(af_parts)])
                    cmd.extend([
                        "-c:v", "libx264", "-preset", "veryfast",
                        "-c:a", "aac",
                        "-pix_fmt", "yuv420p",
                        "-avoid_negative_ts", "make_zero",
                        seg_path,
                    ])

                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=_segment_timeout_seconds(duration),
                    )
                except subprocess.TimeoutExpired as e:
                    last_err = (
                        f"ffmpeg segment timeout after {e.timeout}s "
                        f"(mode={mode}, duration={duration:.2f}s)"
                    )
                    logger.warning("Segment %s subtitle mode '%s' timeout: %s", i, mode, last_err)
                    continue
                segment_ok = result.returncode == 0 and os.path.exists(seg_path)
                if segment_ok:
                    break
                last_err = (result.stderr or "")[-700:]
                logger.warning(
                    "Segment %s subtitle mode '%s' failed: %s",
                    i, mode, last_err
                )

            if not segment_ok:
                raise RuntimeError(
                    f"Segment {i} failed with all subtitle render modes. Last ffmpeg error: {last_err}"
                )

            segment_paths.append(seg_path)
            if progress_callback:
                progress_callback(0.4 + 0.4 * (i + 1) / len(clips))

        if not segment_paths:
            raise RuntimeError("ffmpeg segment extraction failed for all clips")

        # Step 2: create concat list
        concat_list_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_list_path, "w") as f:
            for p in segment_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")

        # Step 3: concatenate (re-encode for consistency after filters)
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-1000:]}")

        if progress_callback:
            progress_callback(0.95)

        return output_path

    finally:
        # Cleanup temp
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _resolve_clip_source_path(clip: dict, fallback_source_path: str) -> str:
    path = clip.get("source_path")
    if isinstance(path, str) and path and os.path.exists(path):
        return path

    notes = clip.get("notes")
    if isinstance(notes, str) and notes:
        try:
            payload = json.loads(notes)
            if isinstance(payload, dict):
                note_path = payload.get("source_path")
                if isinstance(note_path, str) and note_path and os.path.exists(note_path):
                    return note_path
        except json.JSONDecodeError:
            if notes.startswith("source-track:"):
                track_path = notes.split("source-track:", 1)[1].strip()
                if track_path and os.path.exists(track_path):
                    return track_path

    return fallback_source_path


def get_video_duration(source_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    ffprobe_bin = find_binary("ffprobe")
    if not ffprobe_bin:
        logger.warning(
            "ffprobe not found in PATH/common locations; skipping duration probe for %s",
            source_path,
        )
        return 0.0

    cmd = [
        ffprobe_bin, "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        source_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        logger.warning("ffprobe execution failed (binary not found): %s", ffprobe_bin)
        return 0.0

    if result.returncode != 0:
        return 0.0
    try:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except (json.JSONDecodeError, ValueError):
        return 0.0
