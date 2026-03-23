"""Pydantic schemas for API request/response validation."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


# ─── Event Schemas ──────────────────────────────────────────────────────────

class EventSchema(BaseModel):
    id: str
    job_id: str
    event_type: str
    timestamp_seconds: float
    confidence: float
    description: Optional[str] = None
    extra_data: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


# ─── Clip Schemas ────────────────────────────────────────────────────────────

class ClipCreate(BaseModel):
    title: str = ""
    event_type: Optional[str] = None
    event_id: Optional[str] = None
    start_time: float
    end_time: float
    order_index: int = 0
    transition_type: str = "cut"
    transition_duration: float = 0.5
    notes: Optional[str] = None


class ClipUpdate(BaseModel):
    title: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    order_index: Optional[int] = None
    transition_type: Optional[str] = None
    transition_duration: Optional[float] = None
    notes: Optional[str] = None


class ClipSchema(BaseModel):
    id: str
    timeline_id: str
    title: str
    event_type: Optional[str] = None
    event_id: Optional[str] = None
    start_time: float
    end_time: float
    order_index: int
    transition_type: str
    transition_duration: float
    is_ai_generated: bool
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


# ─── Timeline Schemas ────────────────────────────────────────────────────────

class TimelineCreate(BaseModel):
    name: str = "Main Timeline"
    order_index: int = 0


class TimelineUpdate(BaseModel):
    name: Optional[str] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None


class TimelineSchema(BaseModel):
    id: str
    job_id: str
    name: str
    order_index: int
    is_active: bool
    clips: list[ClipSchema] = []

    model_config = {"from_attributes": True}


# ─── Job Schemas ─────────────────────────────────────────────────────────────

class JobListItem(BaseModel):
    id: str
    name: str
    status: str
    progress: float
    progress_message: str
    source_filename: Optional[str] = None
    video_duration: Optional[float] = None
    detection_chain: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class JobDetail(JobListItem):
    source_path: Optional[str] = None
    output_path: Optional[str] = None
    ai_plan: Optional[dict[str, Any]] = None
    events: list[EventSchema] = []
    timelines: list[TimelineSchema] = []


class JobCreateResponse(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime


# ─── Rebuild / Timeline Patch ────────────────────────────────────────────────

class ClipPatch(BaseModel):
    id: Optional[str] = None  # existing clip id; None = new clip
    title: str = ""
    event_type: Optional[str] = None
    event_id: Optional[str] = None
    start_time: float
    end_time: float
    transition_type: str = "cut"
    transition_duration: float = 0.5
    is_ai_generated: Optional[bool] = None
    notes: Optional[str] = None


class TimelinePatch(BaseModel):
    timeline_id: str
    name: Optional[str] = None
    clips: list[ClipPatch] = []


class RebuildRequest(BaseModel):
    timelines: list[TimelinePatch]


# ─── Health ──────────────────────────────────────────────────────────────────

class HealthCheck(BaseModel):
    status: str
    api: bool
    redis: bool
    sqlite: bool
    timestamp: datetime
