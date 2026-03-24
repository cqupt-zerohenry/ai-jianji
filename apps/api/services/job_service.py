"""
JobService — orchestrates job lifecycle operations.
Bridges API routers with repositories and Redis queue.
"""
from __future__ import annotations
import os
import uuid
import shutil
from typing import Optional

from fastapi import UploadFile
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.repositories import job_repo
from apps.api.models.db_models import Job
from apps.api.schemas.job_schemas import RebuildRequest, JobDetail
from apps.api.queue.producer import enqueue_job, cancel_job_queue
from apps.api.services.source_manifest import (
    write_manifest, get_manifest_path, get_parts_dir,
    ensure_multi_source, append_source, list_sources,
)


settings = get_settings()


async def _save_upload_file(file: UploadFile, dest_path: str, chunk_size: int = 1024 * 1024) -> None:
    """Persist UploadFile to disk in chunks to avoid high memory usage."""
    with open(dest_path, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)


async def create_job_from_upload(
    db: AsyncSession,
    file: UploadFile,
    name: Optional[str] = None,
) -> Job:
    """Save uploaded file and create job record, then enqueue."""
    job_id = str(uuid.uuid4())
    original_name = file.filename or "video.mp4"
    ext = os.path.splitext(original_name)[1] or ".mp4"

    # Store file
    os.makedirs(settings.upload_dir, exist_ok=True)
    dest_path = os.path.join(settings.upload_dir, f"{job_id}{ext}")
    await _save_upload_file(file, dest_path)

    job_name = name or original_name
    job = await job_repo.create_job(
        db=db,
        job_id=job_id,
        name=job_name,
        source_path=dest_path,
        source_filename=original_name,
    )

    # Enqueue to Redis
    try:
        enqueue_job(job_id=job_id, source_path=dest_path)
    except Exception:
        # Upload is already written to disk; remove it on enqueue failure to avoid
        # orphan files when request transaction is rolled back.
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        raise
    return job


async def create_job_from_uploads(
    db: AsyncSession,
    files: list[UploadFile],
    name: Optional[str] = None,
) -> Job:
    """Save multiple uploaded videos and enqueue multi-source AI processing job."""
    if not files:
        raise ValueError("No files uploaded")

    job_id = str(uuid.uuid4())
    os.makedirs(settings.upload_dir, exist_ok=True)
    parts_dir = os.path.join(settings.upload_dir, f"{job_id}_parts")
    os.makedirs(parts_dir, exist_ok=True)

    saved_paths: list[str] = []
    source_segments: list[dict] = []

    try:
        # 1) Persist uploaded files
        for i, file in enumerate(files):
            original_name = file.filename or f"video_{i + 1}.mp4"
            ext = os.path.splitext(original_name)[1] or ".mp4"
            part_path = os.path.join(parts_dir, f"part_{i:03d}{ext}")
            await _save_upload_file(file, part_path)
            saved_paths.append(part_path)
            source_segments.append({
                "index": i,
                "name": file.filename or os.path.basename(part_path),
                "path": part_path,
            })

        write_manifest(job_id, {
            "job_id": job_id,
            "sources": source_segments,
            "status": "uploaded",
            "source_count": len(source_segments),
        })

        # 2) Create DB job and enqueue (AI processes multiple sources directly)
        display_name = name or f"Multi-source job ({len(files)} videos)"
        display_source = ", ".join((f.filename or f"video_{i + 1}") for i, f in enumerate(files))
        primary_source_path = saved_paths[0] if saved_paths else None
        if not primary_source_path:
            raise RuntimeError("No source files were saved")
        job = await job_repo.create_job(
            db=db,
            job_id=job_id,
            name=display_name,
            source_path=primary_source_path,
            source_filename=display_source,
        )
        enqueue_job(job_id=job_id, source_path=primary_source_path)
        return job
    except Exception:
        # Cleanup generated files on failure before DB commit.
        for p in [get_manifest_path(job_id)]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if os.path.isdir(parts_dir):
            shutil.rmtree(parts_dir, ignore_errors=True)
        raise


async def cancel_job(db: AsyncSession, job_id: str) -> bool:
    job = await job_repo.get_job(db, job_id)
    if not job or job.status not in ("queued", "processing"):
        return False

    cancel_job_queue(job_id)
    await job_repo.update_job_status(
        db, job_id, status="canceled",
        progress_message="Canceled by user"
    )
    return True


async def retry_job(db: AsyncSession, job_id: str) -> bool:
    job = await job_repo.get_job(db, job_id)
    if not job or job.status not in ("failed", "canceled"):
        return False

    await job_repo.update_job_status(
        db, job_id, status="queued",
        progress=0.0,
        progress_message="Queued for retry",
        error_message=None,
    )
    enqueue_job(job_id=job_id, source_path=job.source_path or "")
    return True


async def delete_job_and_files(db: AsyncSession, job_id: str) -> bool:
    job = await job_repo.get_job(db, job_id)
    if not job:
        return False

    # Remove source and output files
    for path in [job.source_path, job.output_path, get_manifest_path(job_id)]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    parts_dir = os.path.join(settings.upload_dir, f"{job_id}_parts")
    if os.path.isdir(parts_dir):
        shutil.rmtree(parts_dir, ignore_errors=True)

    await job_repo.delete_job(db, job_id)
    return True


async def rebuild_job(
    db: AsyncSession,
    job_id: str,
    request: RebuildRequest,
) -> bool:
    """Patch timelines with user edits and re-enqueue render."""
    from apps.api.repositories.job_repo import (
        get_timeline, delete_clips_for_timeline, bulk_insert_clips
    )

    job = await job_repo.get_job(db, job_id)
    if not job or job.status not in ("completed", "failed"):
        return False

    for tl_patch in request.timelines:
        tl = await get_timeline(db, tl_patch.timeline_id)

        if not tl:
            # New timeline created on the frontend — insert into DB
            existing_count = len(job.timelines) if job.timelines else 0
            tl = await job_repo.create_timeline(
                db,
                job_id=job_id,
                name=tl_patch.name or "Manual",
                order_index=existing_count,
            )

        # Update name if provided
        if tl_patch.name:
            tl.name = tl_patch.name

        # Replace clips
        await delete_clips_for_timeline(db, tl.id)
        clips_data = [
            {
                "title": c.title,
                "event_type": c.event_type,
                "event_id": c.event_id,
                "start_time": c.start_time,
                "end_time": c.end_time,
                "order_index": idx,
                "transition_type": c.transition_type,
                "transition_duration": c.transition_duration,
                "is_ai_generated": c.is_ai_generated if c.is_ai_generated is not None else False,
                "notes": c.notes,
            }
            for idx, c in enumerate(tl_patch.clips)
        ]
        await bulk_insert_clips(db, tl.id, clips_data)

    # Re-queue render task
    await job_repo.update_job_status(
        db, job_id, status="queued",
        progress=0.0,
        progress_message="Queued for rebuild"
    )
    enqueue_job(job_id=job_id, source_path=job.source_path or "", rebuild=True)
    return True


def get_output_path(job_id: str) -> Optional[str]:
    """Return output file path if it exists."""
    out_dir = settings.output_dir
    for ext in [".mp4", ".mov", ".avi"]:
        path = os.path.join(out_dir, f"{job_id}{ext}")
        if os.path.exists(path):
            return path
    return None


async def add_source_to_job(
    db: AsyncSession,
    job_id: str,
    file: UploadFile,
) -> list[dict]:
    """
    Append a new source video to an existing job.
    Upgrades single-source jobs to multi-source format if needed.
    Returns the full updated source list.
    """
    job = await job_repo.get_job(db, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    original_name = file.filename or "video.mp4"
    ext = os.path.splitext(original_name)[1] or ".mp4"

    # 1) Ensure multi-source structure exists
    ensure_multi_source(
        job_id,
        original_source_path=job.source_path or "",
        original_filename=job.source_filename or "",
    )

    # 2) Save new file into parts dir
    parts_dir = get_parts_dir(job_id)
    os.makedirs(parts_dir, exist_ok=True)

    # Determine next part index from existing files
    existing_parts = [f for f in os.listdir(parts_dir) if f.startswith("part_")]
    next_index = len(existing_parts)
    part_path = os.path.join(parts_dir, f"part_{next_index:03d}{ext}")
    await _save_upload_file(file, part_path)

    # 3) Append to manifest
    manifest = append_source(job_id, part_path, original_name)

    # 4) Update job source_filename to reflect all sources
    all_names = [s.get("name", "") for s in manifest.get("sources", [])]
    await db.execute(
        sa_update(Job)
        .where(Job.id == job_id)
        .values(source_filename=", ".join(all_names))
    )
    await db.flush()

    return manifest.get("sources", [])


async def get_job_sources(db: AsyncSession, job_id: str) -> list[dict]:
    """Return the source list for a job."""
    job = await job_repo.get_job(db, job_id)
    if not job:
        return []
    return list_sources(job_id, job.source_path, job.source_filename)
