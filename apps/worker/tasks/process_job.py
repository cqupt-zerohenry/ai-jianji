"""
Core worker task — executed by RQ worker process.
Handles the full pipeline: detect → plan → store → assemble.
Progress is persisted to SQLite at each step.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
import threading

logger = logging.getLogger(__name__)


def _normalize_source_segments(
    source_segments: list[dict],
    get_video_duration_fn,
) -> list[dict]:
    """
    Validate and normalize uploaded source segments.
    Each source keeps its own local timeline [0, duration].
    """
    if not source_segments:
        return []

    normalized: list[dict] = []
    for i, seg in enumerate(source_segments):
        seg_path = seg.get("path", "")
        if not seg_path or not os.path.exists(seg_path):
            raise FileNotFoundError(f"Missing source segment: {seg_path}")

        duration = float(seg.get("duration") or 0.0)
        if duration <= 0:
            duration = max(0.0, float(get_video_duration_fn(seg_path)))
        duration = round(duration, 3)

        seg_index = seg.get("index")
        try:
            seg_index = int(seg_index)
        except (TypeError, ValueError):
            seg_index = i

        normalized.append({
            "index": seg_index,
            "name": seg.get("name") or f"Video {i + 1}",
            "path": seg_path,
            "duration": duration,
            "start_time": 0.0,
            "end_time": duration,
        })

    return normalized


def run_job_task(job_id: str, source_path: str, rebuild: bool = False) -> dict:
    """
    Synchronous entry point for RQ.
    Wraps async logic in asyncio.run().
    """
    try:
        return asyncio.run(_async_run_job(job_id, source_path, rebuild))
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        asyncio.run(_mark_failed(job_id, str(e)))
        raise


async def _async_run_job(job_id: str, source_path: str, rebuild: bool) -> dict:
    """Full async job pipeline."""
    from apps.api.models.database import AsyncSessionLocal
    from apps.api.repositories import job_repo
    from apps.api.services.clip_engine import (
        build_clip_plan, assemble_video, get_video_duration
    )
    from apps.api.config import get_settings
    from apps.api.schemas.detection_schemas import DetectionEvent, DetectionResult
    from apps.api.services.source_manifest import load_manifest, write_manifest
    from apps.worker.detectors.pipeline import run_detection_pipeline

    async with AsyncSessionLocal() as db:
        # Mark processing
        await job_repo.update_job_status(
            db, job_id, status="processing",
            progress=0.05, progress_message="Starting processing..."
        )
        await db.commit()

        job = await job_repo.get_job(db, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found in DB")

    source_manifest = load_manifest(job_id) or {}
    source_segments = source_manifest.get("sources", []) if isinstance(source_manifest, dict) else []

    # Multi-source jobs are processed directly from independent source files.
    if source_segments:
        normalized_segments = await asyncio.to_thread(
            _normalize_source_segments,
            source_segments,
            get_video_duration,
        )
        source_segments = normalized_segments
        write_manifest(job_id, {
            "job_id": job_id,
            "sources": normalized_segments,
            "source_count": len(normalized_segments),
            "status": "ready",
        })
    elif not os.path.exists(source_path):
        raise FileNotFoundError(f"Source video not found: {source_path}")

    # ── Step 1: Get video duration ─────────────────────────────────────
    async with AsyncSessionLocal() as db:
        await job_repo.update_job_status(
            db, job_id, status="processing",
            progress=0.08,
            progress_message=(
                "Reading source metadata..." if source_segments else "Reading video metadata..."
            )
        )
        await db.commit()

    if source_segments:
        duration = sum(float(seg.get("duration") or 0.0) for seg in source_segments)
    else:
        duration = get_video_duration(source_path)
    logger.info(f"Job {job_id}: video duration = {duration:.1f}s")

    # ── Step 2: AI Detection (skip on rebuild) ─────────────────────────
    if not rebuild:
        async with AsyncSessionLocal() as db:
            await job_repo.update_job_status(
                db, job_id, status="processing",
                progress=0.1,
                progress_message=(
                    "Running AI event detection on sources..."
                    if source_segments
                    else "Running AI event detection..."
                )
            )
            await db.commit()

        if source_segments:
            merged_events: list[DetectionEvent] = []
            chains: list[str] = []
            total_sources = len(source_segments)
            source_progress = [0.0 for _ in range(total_sources)]
            progress_lock = asyncio.Lock()
            last_sent_progress = 0.1
            last_sent_time = 0.0
            max_parallel = max(1, int(get_settings().multi_source_detection_concurrency))
            semaphore = asyncio.Semaphore(max_parallel)

            async def emit_detection_progress(force: bool = False) -> None:
                nonlocal last_sent_progress, last_sent_time
                avg_progress = sum(source_progress) / max(1, total_sources)
                overall = 0.1 + (0.25 * avg_progress)
                now = asyncio.get_running_loop().time()

                async with progress_lock:
                    if not force:
                        if overall <= (last_sent_progress + 0.003) and (now - last_sent_time) < 0.5:
                            return
                    if overall < last_sent_progress:
                        overall = last_sent_progress
                    last_sent_progress = overall
                    last_sent_time = now

                await _update_progress(
                    job_id,
                    overall,
                    f"AI analyzing {total_sources} source videos...",
                )

            async def analyze_source(i: int, seg: dict) -> tuple[int, dict, DetectionResult | Exception]:
                async with semaphore:
                    async def source_progress_cb(local_progress: float) -> None:
                        source_progress[i] = max(0.0, min(1.0, float(local_progress)))
                        await emit_detection_progress(force=False)

                    try:
                        result = await run_detection_pipeline(
                            source_path=seg["path"],
                            video_duration=float(seg.get("duration") or 0.0),
                            progress_callback=source_progress_cb,
                        )
                        return i, seg, result
                    except Exception as e:
                        return i, seg, e
                    finally:
                        source_progress[i] = 1.0
                        await emit_detection_progress(force=True)

            tasks = [
                asyncio.create_task(analyze_source(i, seg))
                for i, seg in enumerate(source_segments)
            ]
            source_results = await asyncio.gather(*tasks)

            success_count = 0
            errors: list[str] = []
            for i, seg, result in sorted(source_results, key=lambda x: x[0]):
                if isinstance(result, Exception):
                    errors.append(f"source {i + 1} ({seg.get('name', 'unknown')}): {result}")
                    logger.warning("Source %s detection failed: %s", i + 1, result)
                    continue

                success_count += 1
                if result.chain_used and result.chain_used not in chains:
                    chains.append(result.chain_used)

                for event in result.events:
                    metadata = dict(event.metadata or {})
                    metadata.setdefault("source_index", seg["index"])
                    metadata.setdefault("source_name", seg["name"])
                    metadata.setdefault("source_path", seg["path"])
                    merged_events.append(
                        DetectionEvent(
                            event_type=event.event_type,
                            timestamp_seconds=event.timestamp_seconds,
                            confidence=event.confidence,
                            description=event.description,
                            metadata=metadata,
                        )
                    )

            if success_count == 0:
                raise RuntimeError(
                    "AI detection failed for all uploaded sources: " + " | ".join(errors[:4])
                )

            detection_result = DetectionResult(
                events=merged_events,
                chain_used="+".join(chains) if chains else "mock",
                video_duration=duration,
            )
        else:
            async def single_progress_cb(local_progress: float) -> None:
                p = max(0.0, min(1.0, float(local_progress)))
                overall = 0.1 + (0.25 * p)
                await _update_progress(job_id, overall, "AI analyzing video...")

            detection_result = await run_detection_pipeline(
                source_path=source_path,
                video_duration=duration,
                progress_callback=single_progress_cb,
            )
            detection_result.video_duration = detection_result.video_duration or duration

        # ── Step 3: Store events in SQLite ─────────────────────────────
        async with AsyncSessionLocal() as db:
            from apps.api.repositories.job_repo import (
                bulk_insert_events, delete_events_for_job,
                delete_timelines_for_job, create_timeline, bulk_insert_clips
            )

            await job_repo.update_job_status(
                db, job_id, status="processing",
                progress=0.4, progress_message="Storing detected events..."
            )

            await delete_events_for_job(db, job_id)
            events_data = [
                {
                    "event_type": e.event_type.value,
                    "timestamp_seconds": e.timestamp_seconds,
                    "confidence": e.confidence,
                    "description": e.description,
                    "extra_data": e.metadata,
                }
                for e in detection_result.events
            ]
            await bulk_insert_events(db, job_id, events_data)

            # ── Step 4: Build clip plan ─────────────────────────────
            clip_plan = build_clip_plan(detection_result)

            # ── Step 5: Create timeline + clips in SQLite ───────────
            await delete_timelines_for_job(db, job_id)
            timeline = await create_timeline(db, job_id, "AI Generated", order_index=0)

            clips_data = [
                {
                    "title": c["title"],
                    "event_type": c["event_type"],
                    "start_time": c["start_time"],
                    "end_time": c["end_time"],
                    "order_index": c["order_index"],
                    "transition_type": c["transition_type"],
                    "transition_duration": c["transition_duration"],
                    "is_ai_generated": True,
                    "notes": json.dumps(
                        {
                            k: v
                            for k, v in {
                                "description": c.get("description"),
                                "source_index": c.get("source_index"),
                                "source_name": c.get("source_name"),
                                "source_path": c.get("source_path"),
                            }.items()
                            if v is not None
                        },
                        ensure_ascii=False,
                    ) or None,
                }
                for c in clip_plan["clips"]
            ]
            await bulk_insert_clips(db, timeline.id, clips_data)

            # Optional read-only source tracks for multi-video jobs.
            if source_segments:
                for i, seg in enumerate(source_segments):
                    source_tl = await create_timeline(
                        db,
                        job_id,
                        f"Source: {seg.get('name', f'Video {i + 1}')}",
                        order_index=i + 1,
                    )
                    source_clips = [{
                        "title": seg.get("name", f"Video {i + 1}"),
                        "event_type": "SOURCE",
                        "start_time": float(seg.get("start_time", 0.0)),
                        "end_time": float(seg.get("end_time", 0.0)),
                        "order_index": 0,
                        "transition_type": "cut",
                        "transition_duration": 0.0,
                        "is_ai_generated": False,
                        "notes": json.dumps(
                            {
                                "source_track": True,
                                "source_index": seg.get("index"),
                                "source_name": seg.get("name", f"Video {i + 1}"),
                                "source_path": seg.get("path", ""),
                            },
                            ensure_ascii=False,
                        ),
                    }]
                    await bulk_insert_clips(db, source_tl.id, source_clips)

            await job_repo.update_job_status(
                db, job_id,
                status="processing",
                progress=0.5,
                progress_message="Clip plan ready, starting video assembly...",
                video_duration=duration,
                detection_chain=detection_result.chain_used,
                ai_plan={**clip_plan, "source_segments": source_segments},
            )
            await db.commit()

    else:
        # Rebuild: load existing clips from DB
        async with AsyncSessionLocal() as db:
            job = await job_repo.get_job(db, job_id)
            if not job or not job.timelines:
                raise ValueError("No timelines found for rebuild")

            clip_plan = {"clips": [], "chain_used": "user_edit"}
            for tl in sorted(job.timelines, key=lambda t: t.order_index):
                if (tl.name or "").startswith("Source:"):
                    continue
                for clip in sorted(tl.clips, key=lambda c: c.order_index):
                    clip_dict = {
                        "start_time": clip.start_time,
                        "end_time": clip.end_time,
                        "transition_type": clip.transition_type,
                        "transition_duration": clip.transition_duration,
                        "title": clip.title,
                        "notes": clip.notes,
                    }
                    # Restore description from notes JSON for subtitle rendering
                    if clip.notes:
                        try:
                            notes_payload = json.loads(clip.notes)
                            if isinstance(notes_payload, dict) and notes_payload.get("description"):
                                clip_dict["description"] = notes_payload["description"]
                        except (json.JSONDecodeError, TypeError):
                            pass
                    clip_plan["clips"].append(clip_dict)

            await job_repo.update_job_status(
                db, job_id,
                status="processing",
                progress=0.5,
                progress_message="Starting video rebuild..."
            )
            await db.commit()

    # ── Step 6: Assemble video ─────────────────────────────────────────
    if not clip_plan["clips"]:
        async with AsyncSessionLocal() as db:
            await job_repo.update_job_status(
                db, job_id, status="failed",
                progress=1.0,
                error_message="No clips generated — video may have no detected events"
            )
            await db.commit()
        return {"status": "failed"}

    settings_obj = get_settings()
    os.makedirs(settings_obj.output_dir, exist_ok=True)
    output_path = os.path.join(settings_obj.output_dir, f"{job_id}.mp4")

    async with AsyncSessionLocal() as db:
        await job_repo.update_job_status(
            db, job_id, status="processing",
            progress=0.6, progress_message="Encoding output video..."
        )
        await db.commit()

    try:
        loop = asyncio.get_running_loop()
        cb_lock = threading.Lock()
        cb_state = {"last_progress": 0.0, "last_emit_at": 0.0}

        def encode_progress_cb(local_progress: float) -> None:
            p = max(0.0, min(1.0, float(local_progress)))
            now = time.monotonic()
            with cb_lock:
                if p < cb_state["last_progress"]:
                    p = cb_state["last_progress"]
                should_emit = (
                    (p - cb_state["last_progress"] >= 0.01)
                    or (now - cb_state["last_emit_at"] >= 1.0)
                    or p >= 0.999
                )
                cb_state["last_progress"] = p
                if not should_emit:
                    return
                cb_state["last_emit_at"] = now

            overall = 0.6 + 0.38 * p
            asyncio.run_coroutine_threadsafe(
                _update_progress(job_id, overall, "Encoding output video..."),
                loop,
            )

        # Run encoding in a background thread so async progress updates can flush.
        await asyncio.to_thread(
            assemble_video,
            source_path=source_path,
            clips=clip_plan["clips"],
            output_path=output_path,
            progress_callback=encode_progress_cb,
        )
    except Exception as e:
        async with AsyncSessionLocal() as db:
            await job_repo.update_job_status(
                db, job_id, status="failed",
                progress=1.0,
                error_message=f"Video assembly failed: {str(e)}"
            )
            await db.commit()
        raise

    # ── Step 7: Mark complete ──────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        await job_repo.update_job_status(
            db, job_id, status="completed",
            progress=1.0,
            progress_message="Processing complete!",
            output_path=output_path,
        )
        await db.commit()

    logger.info(f"Job {job_id} completed. Output: {output_path}")
    return {"status": "completed", "output_path": output_path}


async def _update_progress(job_id: str, progress: float, message: str) -> None:
    from apps.api.models.database import AsyncSessionLocal
    from apps.api.repositories import job_repo
    async with AsyncSessionLocal() as db:
        await job_repo.update_job_status(
            db, job_id, status="processing",
            progress=progress, progress_message=message
        )
        await db.commit()


async def _mark_failed(job_id: str, error: str) -> None:
    try:
        from apps.api.models.database import AsyncSessionLocal
        from apps.api.repositories import job_repo
        async with AsyncSessionLocal() as db:
            await job_repo.update_job_status(
                db, job_id, status="failed",
                progress=1.0,
                error_message=error
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as failed: {e}")
