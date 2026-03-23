"""Internal event/detection schemas shared between API and Worker."""
from __future__ import annotations
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel


class EventType(str, Enum):
    GOAL = "GOAL"
    SHOT_ON_TARGET = "SHOT_ON_TARGET"
    SHOT_BLOCKED = "SHOT_BLOCKED"
    SAVE = "SAVE"
    CORNER_KICK = "CORNER_KICK"
    FREE_KICK = "FREE_KICK"
    OFFSIDE = "OFFSIDE"
    FOUL = "FOUL"
    SUBSTITUTION = "SUBSTITUTION"
    YELLOW_CARD = "YELLOW_CARD"
    RED_CARD = "RED_CARD"
    PENALTY = "PENALTY"
    VAR = "VAR"
    HIGHLIGHT = "HIGHLIGHT"


class DetectionEvent(BaseModel):
    """Unified event format consumed by the clip engine."""
    event_type: EventType
    timestamp_seconds: float
    confidence: float = 1.0
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class DetectionResult(BaseModel):
    """Complete detection output from any chain."""
    events: list[DetectionEvent]
    chain_used: str  # "dashscope" | "openai" | "mock"
    video_duration: Optional[float] = None
    raw_response: Optional[str] = None


# Priority weights for event ordering in auto-clip
EVENT_PRIORITY: dict[EventType, int] = {
    EventType.GOAL: 10,
    EventType.PENALTY: 9,
    EventType.RED_CARD: 8,
    EventType.VAR: 7,
    EventType.SAVE: 6,
    EventType.CORNER_KICK: 6,
    EventType.FREE_KICK: 6,
    EventType.OFFSIDE: 6,
    EventType.FOUL: 5,
    EventType.SHOT_ON_TARGET: 5,
    EventType.SHOT_BLOCKED: 5,
    EventType.SUBSTITUTION: 4,
    EventType.YELLOW_CARD: 4,
    EventType.HIGHLIGHT: 3,
}
