"""
SQLAlchemy ORM models — defines DB schema for SQLite persistence.
Redis is NOT referenced here; it only handles queue state.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Text, DateTime,
    ForeignKey, JSON, Boolean
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    status = Column(String, default="queued")  # queued/processing/completed/failed/canceled
    progress = Column(Float, default=0.0)
    progress_message = Column(String, default="")
    error_message = Column(Text, nullable=True)

    source_path = Column(String, nullable=True)
    output_path = Column(String, nullable=True)
    source_filename = Column(String, nullable=True)
    video_duration = Column(Float, nullable=True)

    detection_chain = Column(String, nullable=True)  # "dashscope" | "openai" | null
    ai_plan = Column(JSON, nullable=True)             # AI generated clip plan

    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    completed_at = Column(DateTime, nullable=True)

    events = relationship("DetectedEvent", back_populates="job", cascade="all, delete-orphan")
    timelines = relationship("Timeline", back_populates="job", cascade="all, delete-orphan")


class DetectedEvent(Base):
    __tablename__ = "detected_events"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)

    event_type = Column(String, nullable=False)  # GOAL, SHOT_ON_TARGET, etc.
    timestamp_seconds = Column(Float, nullable=False)
    confidence = Column(Float, default=1.0)
    description = Column(Text, nullable=True)
    extra_data = Column(JSON, nullable=True)  # renamed from metadata (reserved by SQLAlchemy)

    job = relationship("Job", back_populates="events")


class Timeline(Base):
    __tablename__ = "timelines"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)

    name = Column(String, default="Main Timeline")
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    job = relationship("Job", back_populates="timelines")
    clips = relationship("Clip", back_populates="timeline", cascade="all, delete-orphan",
                         order_by="Clip.order_index")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=_uuid)
    timeline_id = Column(String, ForeignKey("timelines.id"), nullable=False)

    title = Column(String, default="")
    event_type = Column(String, nullable=True)
    event_id = Column(String, nullable=True)  # ref to DetectedEvent

    start_time = Column(Float, nullable=False)    # seconds in source video
    end_time = Column(Float, nullable=False)      # seconds in source video
    order_index = Column(Integer, default=0)

    # Transition to NEXT clip
    transition_type = Column(String, default="cut")  # cut/fade/wipe/slide/circle
    transition_duration = Column(Float, default=0.5)

    is_ai_generated = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    timeline = relationship("Timeline", back_populates="clips")
