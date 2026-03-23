"""
Shared event merging, filtering, and multimodal fusion logic.

Extracted from dashscope_detector to be reusable across detection chains.
"""
from __future__ import annotations

import logging
from typing import Iterable

from apps.api.schemas.detection_schemas import DetectionEvent, EventType

logger = logging.getLogger(__name__)

# ── Confidence thresholds per event type ──────────────────────────────────────

MIN_CONFIDENCE_BY_TYPE: dict[EventType, float] = {
    EventType.GOAL: 0.67,
    EventType.PENALTY: 0.5,
    EventType.RED_CARD: 0.5,
    EventType.VAR: 0.45,
    EventType.CORNER_KICK: 0.54,
    EventType.FREE_KICK: 0.56,
    EventType.OFFSIDE: 0.58,
    EventType.FOUL: 0.56,
    EventType.SUBSTITUTION: 0.62,
    EventType.SAVE: 0.38,
    EventType.SHOT_ON_TARGET: 0.36,
    EventType.SHOT_BLOCKED: 0.34,
    EventType.YELLOW_CARD: 0.38,
    EventType.HIGHLIGHT: 0.3,
}

# ── Keyword dictionaries for description-based relabelling ────────────────────

EVENT_KEYWORDS: dict[EventType, tuple[str, ...]] = {
    EventType.GOAL: ("goal", "scores", "scored", "net", "入网", "进球"),
    EventType.SHOT_ON_TARGET: ("shot on target", "on target", "射正", "射门"),
    EventType.SHOT_BLOCKED: ("blocked", "block", "封堵", "被挡出"),
    EventType.SAVE: ("save", "saved", "扑救", "门将扑出"),
    EventType.CORNER_KICK: ("corner", "corner kick", "角球"),
    EventType.FREE_KICK: ("free kick", "任意球"),
    EventType.OFFSIDE: ("offside", "越位"),
    EventType.FOUL: ("foul", "犯规"),
    EventType.SUBSTITUTION: ("substitution", "subbed", "comes on", "替补登场", "换人"),
    EventType.YELLOW_CARD: ("yellow card", "黄牌"),
    EventType.RED_CARD: ("red card", "红牌"),
    EventType.PENALTY: ("penalty", "点球"),
    EventType.VAR: ("var", "video assistant", "视频助理裁判"),
}

GOAL_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "miss", "missed", "wide", "off target", "off-target", "wide of goal",
    "saved", "save", "goalkeeper", "keeper", "扑救", "扑出", "被扑",
    "blocked", "block", "deflect", "deflected", "封堵", "被挡",
    "post", "woodwork", "crossbar", "bar", "门柱", "横梁",
    "offside", "越位", "disallowed", "ruled out", "no goal", "not a goal",
    "foul in attack", "进攻犯规", "犯规在先",
)

GOAL_STRONG_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "scores", "scored", "finds the net", "into the net",
    "nets", "puts it in", "入网", "破门", "绝杀", "扳平",
)

GOAL_WEAK_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "goal", "进球",
)


# ── Public API ────────────────────────────────────────────────────────────────

def merge_and_filter_events(
    events: Iterable[DetectionEvent],
    duration: float,
) -> list[DetectionEvent]:
    """
    Normalize, deduplicate nearby events (weighted-average merge),
    relabel by description cues, and filter by confidence threshold.
    """
    normalized_events = [_relabel_by_description(e) for e in events]
    sorted_events = sorted(
        normalized_events,
        key=lambda e: (e.event_type.value, e.timestamp_seconds),
    )
    merged: list[DetectionEvent] = []

    for ev in sorted_events:
        ts = ev.timestamp_seconds
        if duration > 0:
            ts = max(0.0, min(ts, duration))
        confidence = max(0.0, min(1.0, float(ev.confidence)))
        normalized = DetectionEvent(
            event_type=ev.event_type,
            timestamp_seconds=ts,
            confidence=confidence,
            description=ev.description,
            metadata=ev.metadata,
        )

        if not merged:
            merged.append(normalized)
            continue

        prev = merged[-1]
        merge_window = 14.0 if normalized.event_type == EventType.GOAL else 2.5
        if (
            prev.event_type == normalized.event_type
            and abs(prev.timestamp_seconds - normalized.timestamp_seconds) <= merge_window
        ):
            total_w = max(0.01, prev.confidence + normalized.confidence)
            merged_ts = (
                prev.timestamp_seconds * prev.confidence
                + normalized.timestamp_seconds * normalized.confidence
            ) / total_w
            merged_conf = min(1.0, max(prev.confidence, normalized.confidence) + 0.05)
            merged_desc = prev.description or normalized.description
            if (normalized.description or "") and len(normalized.description or "") > len(merged_desc or ""):
                merged_desc = normalized.description
            merged[-1] = DetectionEvent(
                event_type=prev.event_type,
                timestamp_seconds=round(merged_ts, 2),
                confidence=round(merged_conf, 3),
                description=merged_desc,
            )
        else:
            merged.append(normalized)

    filtered: list[DetectionEvent] = []
    for ev in merged:
        min_conf = MIN_CONFIDENCE_BY_TYPE.get(ev.event_type, 0.4)
        if ev.confidence >= min_conf:
            filtered.append(ev)
    return filtered


def fuse_multimodal_events(
    visual_events: list[DetectionEvent],
    audio_events: list[DetectionEvent],
    duration: float,
    match_window: float = 8.0,
    confidence_boost: float = 0.10,
) -> list[DetectionEvent]:
    """
    Fuse visual (DashScope) and audio (OpenAI/Whisper) detection results.

    - Matched pairs (same type, within match_window): weighted-average timestamps,
      boost confidence by confidence_boost.
    - Unmatched events from both lists are kept as-is.
    - Final result is run through merge_and_filter_events().
    """
    fused: list[DetectionEvent] = []
    audio_matched: set[int] = set()

    for v_event in visual_events:
        best_match_idx: int | None = None
        best_match_dist: float = match_window + 1.0

        for a_idx, a_event in enumerate(audio_events):
            if a_idx in audio_matched:
                continue
            if a_event.event_type != v_event.event_type:
                continue
            dist = abs(v_event.timestamp_seconds - a_event.timestamp_seconds)
            if dist <= match_window and dist < best_match_dist:
                best_match_idx = a_idx
                best_match_dist = dist

        if best_match_idx is not None:
            a_event = audio_events[best_match_idx]
            audio_matched.add(best_match_idx)

            # Weighted-average timestamp
            total_w = max(0.01, v_event.confidence + a_event.confidence)
            fused_ts = (
                v_event.timestamp_seconds * v_event.confidence
                + a_event.timestamp_seconds * a_event.confidence
            ) / total_w
            fused_conf = min(1.0, max(v_event.confidence, a_event.confidence) + confidence_boost)
            # Prefer the longer/richer description
            desc = v_event.description or a_event.description
            if (a_event.description or "") and len(a_event.description or "") > len(desc or ""):
                desc = a_event.description

            fused.append(DetectionEvent(
                event_type=v_event.event_type,
                timestamp_seconds=round(fused_ts, 2),
                confidence=round(fused_conf, 3),
                description=desc,
            ))
        else:
            fused.append(v_event)

    # Add unmatched audio events
    for a_idx, a_event in enumerate(audio_events):
        if a_idx not in audio_matched:
            fused.append(a_event)

    return merge_and_filter_events(fused, duration)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _relabel_by_description(event: DetectionEvent) -> DetectionEvent:
    """Re-classify event type based on description keywords (precision guard)."""
    desc = (event.description or "").lower()
    if not desc:
        return event

    def has_any(keywords: tuple[str, ...]) -> bool:
        return any(k in desc for k in keywords)

    if event.event_type == EventType.GOAL:
        has_goal_strong = has_any(GOAL_STRONG_POSITIVE_KEYWORDS)
        has_goal_weak = has_any(GOAL_WEAK_POSITIVE_KEYWORDS)
        has_goal_negative = has_any(GOAL_NEGATIVE_KEYWORDS)

        if has_goal_negative and not has_goal_strong:
            if has_any(EVENT_KEYWORDS[EventType.SAVE]):
                new_type = EventType.SAVE
            elif has_any(EVENT_KEYWORDS[EventType.SHOT_BLOCKED]):
                new_type = EventType.SHOT_BLOCKED
            elif has_any(EVENT_KEYWORDS[EventType.VAR]):
                new_type = EventType.VAR
            else:
                new_type = EventType.SHOT_ON_TARGET
            return DetectionEvent(
                event_type=new_type,
                timestamp_seconds=event.timestamp_seconds,
                confidence=max(0.38, event.confidence - 0.12),
                description=event.description,
                metadata=event.metadata,
            )

        if has_any(EVENT_KEYWORDS[EventType.RED_CARD]):
            new_type = EventType.RED_CARD
        elif has_any(EVENT_KEYWORDS[EventType.YELLOW_CARD]):
            new_type = EventType.YELLOW_CARD
        elif has_any(EVENT_KEYWORDS[EventType.PENALTY]):
            new_type = EventType.PENALTY
        elif has_any(EVENT_KEYWORDS[EventType.VAR]):
            new_type = EventType.VAR
        elif has_any(EVENT_KEYWORDS[EventType.OFFSIDE]):
            new_type = EventType.OFFSIDE
        elif has_any(EVENT_KEYWORDS[EventType.FOUL]):
            new_type = EventType.FOUL
        elif has_any(EVENT_KEYWORDS[EventType.SHOT_BLOCKED]):
            new_type = EventType.SHOT_BLOCKED
        elif has_any(EVENT_KEYWORDS[EventType.SAVE]):
            new_type = EventType.SAVE
        elif has_any(EVENT_KEYWORDS[EventType.SHOT_ON_TARGET]) and not has_any(EVENT_KEYWORDS[EventType.GOAL]):
            new_type = EventType.SHOT_ON_TARGET
        elif not (has_goal_strong or has_goal_weak) and event.confidence < 0.78:
            new_type = EventType.SHOT_ON_TARGET
        else:
            new_type = event.event_type
        if new_type != event.event_type:
            return DetectionEvent(
                event_type=new_type,
                timestamp_seconds=event.timestamp_seconds,
                confidence=max(0.38, event.confidence - 0.08),
                description=event.description,
                metadata=event.metadata,
            )

    return event
