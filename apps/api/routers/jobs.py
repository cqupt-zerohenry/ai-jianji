"""
Jobs router — all job lifecycle endpoints.
"""
from __future__ import annotations
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.schemas.job_schemas import (
    JobCreateResponse, JobListItem, JobDetail, RebuildRequest
)
from apps.api.repositories import job_repo
from apps.api.services.job_service import (
    create_job_from_upload, create_job_from_uploads, cancel_job, retry_job,
    delete_job_and_files, rebuild_job, get_output_path
)
from apps.api.queue.redis_client import ping_redis
from apps.api.queue.producer import QueueUnavailableError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobCreateResponse, status_code=201)
async def upload_job(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Upload a video file and create an async processing job."""
    allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    if not ping_redis():
        raise HTTPException(
            status_code=503,
            detail="Task queue unavailable: Redis is not running on localhost:6379.",
        )

    try:
        job = await create_job_from_upload(db, file, name)
    except QueueUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return JobCreateResponse(
        id=job.id,
        name=job.name,
        status=job.status,
        created_at=job.created_at,
    )


@router.post("/multi", response_model=JobCreateResponse, status_code=201)
async def upload_multi_job(
    files: list[UploadFile] = File(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple videos and create one combined processing job."""
    allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    if not files:
        raise HTTPException(400, "No files uploaded")

    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in allowed:
            raise HTTPException(400, f"Unsupported file type: {ext}")

    if not ping_redis():
        raise HTTPException(
            status_code=503,
            detail="Task queue unavailable: Redis is not running on localhost:6379.",
        )

    try:
        job = await create_job_from_uploads(db, files, name)
    except QueueUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return JobCreateResponse(
        id=job.id,
        name=job.name,
        status=job.status,
        created_at=job.created_at,
    )


@router.get("", response_model=list[JobListItem])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List all jobs ordered by creation time (newest first)."""
    jobs = await job_repo.list_jobs(db)
    return jobs


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get full job details including events, timelines, and clips."""
    job = await job_repo.get_job(db, job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


@router.post("/{job_id}/rebuild", status_code=202)
async def rebuild_job_endpoint(
    job_id: str,
    request: RebuildRequest,
    db: AsyncSession = Depends(get_db),
):
    """Apply manual timeline edits and re-queue video assembly."""
    try:
        success = await rebuild_job(db, job_id, request)
    except QueueUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not success:
        raise HTTPException(400, "Job cannot be rebuilt in its current state")
    return {"message": "Rebuild queued", "job_id": job_id}


@router.post("/{job_id}/cancel", status_code=200)
async def cancel_job_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a queued or processing job."""
    success = await cancel_job(db, job_id)
    if not success:
        raise HTTPException(400, "Job cannot be canceled in its current state")
    return {"message": "Job canceled", "job_id": job_id}


@router.post("/{job_id}/retry", status_code=202)
async def retry_job_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    """Retry a failed or canceled job."""
    try:
        success = await retry_job(db, job_id)
    except QueueUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not success:
        raise HTTPException(400, "Job cannot be retried in its current state")
    return {"message": "Job queued for retry", "job_id": job_id}


@router.delete("/{job_id}", status_code=204)
async def delete_job_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    """Delete job record and all associated files."""
    success = await delete_job_and_files(db, job_id)
    if not success:
        raise HTTPException(404, f"Job {job_id} not found")


@router.get("/{job_id}/source")
async def stream_source(
    job_id: str,
    source_index: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Stream source video for preview (supports multi-source by source_index)."""
    from apps.api.services.source_manifest import load_manifest

    job = await job_repo.get_job(db, job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    source_path = job.source_path
    if source_index is not None:
        manifest = load_manifest(job_id) or {}
        sources = manifest.get("sources", []) if isinstance(manifest, dict) else []
        if source_index < 0 or source_index >= len(sources):
            raise HTTPException(404, f"Source index {source_index} not found")
        source_path = sources[source_index].get("path")

    if not source_path or not os.path.exists(source_path):
        raise HTTPException(404, "Source video not found")

    filename = os.path.basename(source_path)
    return FileResponse(
        path=source_path,
        media_type="video/mp4",
        filename=filename,
    )


@router.get("/{job_id}/download")
async def download_output(job_id: str, db: AsyncSession = Depends(get_db)):
    """Download the assembled output video."""
    job = await job_repo.get_job(db, job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    if job.status != "completed":
        raise HTTPException(400, "Job output not ready")

    output_path = job.output_path or get_output_path(job_id)
    if not output_path or not os.path.exists(output_path):
        raise HTTPException(404, "Output file not found")

    filename = f"highlight_{job.name[:20]}.mp4".replace(" ", "_")
    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=filename,
    )
