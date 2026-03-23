"""
Repository layer for Job CRUD — all SQLite interactions go here.
Never import Redis from this module.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.db_models import Job, DetectedEvent, Timeline, Clip


# ─── Job Repository ───────────────────────────────────────────────────────────

async def create_job(
    db: AsyncSession,
    job_id: str,
    name: str,
    source_path: str,
    source_filename: str,
) -> Job:
    job = Job(
        id=job_id,
        name=name,
        source_path=source_path,
        source_filename=source_filename,
        status="queued",
    )
    db.add(job)
    await db.flush()
    return job


async def get_job(db: AsyncSession, job_id: str) -> Optional[Job]:
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.events),
            selectinload(Job.timelines).selectinload(Timeline.clips),
        )
    )
    return result.scalar_one_or_none()


async def list_jobs(db: AsyncSession) -> list[Job]:
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc())
    )
    return list(result.scalars().all())


async def update_job_status(
    db: AsyncSession,
    job_id: str,
    status: str,
    progress: float = 0.0,
    progress_message: str = "",
    error_message: Optional[str] = None,
    output_path: Optional[str] = None,
    video_duration: Optional[float] = None,
    detection_chain: Optional[str] = None,
    ai_plan: Optional[dict[str, Any]] = None,
) -> None:
    values: dict[str, Any] = {
        "status": status,
        "progress": progress,
        "progress_message": progress_message,
        "updated_at": datetime.utcnow(),
    }
    if error_message is not None:
        values["error_message"] = error_message
    if output_path is not None:
        values["output_path"] = output_path
    if video_duration is not None:
        values["video_duration"] = video_duration
    if detection_chain is not None:
        values["detection_chain"] = detection_chain
    if ai_plan is not None:
        values["ai_plan"] = ai_plan
    if status == "completed":
        values["completed_at"] = datetime.utcnow()

    await db.execute(update(Job).where(Job.id == job_id).values(**values))


async def delete_job(db: AsyncSession, job_id: str) -> None:
    await db.execute(delete(Job).where(Job.id == job_id))


# ─── Event Repository ─────────────────────────────────────────────────────────

async def bulk_insert_events(
    db: AsyncSession,
    job_id: str,
    events: list[dict[str, Any]],
) -> list[DetectedEvent]:
    objs = [DetectedEvent(job_id=job_id, **e) for e in events]
    db.add_all(objs)
    await db.flush()
    return objs


async def delete_events_for_job(db: AsyncSession, job_id: str) -> None:
    await db.execute(delete(DetectedEvent).where(DetectedEvent.job_id == job_id))


# ─── Timeline Repository ──────────────────────────────────────────────────────

async def create_timeline(
    db: AsyncSession,
    job_id: str,
    name: str,
    order_index: int = 0,
) -> Timeline:
    tl = Timeline(job_id=job_id, name=name, order_index=order_index)
    db.add(tl)
    await db.flush()
    return tl


async def get_timeline(db: AsyncSession, timeline_id: str) -> Optional[Timeline]:
    result = await db.execute(
        select(Timeline)
        .where(Timeline.id == timeline_id)
        .options(selectinload(Timeline.clips))
    )
    return result.scalar_one_or_none()


async def delete_timelines_for_job(db: AsyncSession, job_id: str) -> None:
    await db.execute(delete(Timeline).where(Timeline.job_id == job_id))


# ─── Clip Repository ──────────────────────────────────────────────────────────

async def bulk_insert_clips(
    db: AsyncSession,
    timeline_id: str,
    clips: list[dict[str, Any]],
) -> list[Clip]:
    objs = [Clip(timeline_id=timeline_id, **c) for c in clips]
    db.add_all(objs)
    await db.flush()
    return objs


async def delete_clips_for_timeline(db: AsyncSession, timeline_id: str) -> None:
    await db.execute(delete(Clip).where(Clip.timeline_id == timeline_id))
