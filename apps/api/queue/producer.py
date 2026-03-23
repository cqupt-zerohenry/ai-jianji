"""
Task producer — enqueues jobs to Redis for worker consumption.
Cancel is best-effort (RQ supports cancel for queued jobs).
"""
from __future__ import annotations
import logging
import redis
from rq.job import Job as RQJob
from rq.exceptions import NoSuchJobError

from apps.api.queue.redis_client import get_queue, get_redis
from apps.api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Map job_id -> rq_job_id for cancellation
_job_map: dict[str, str] = {}


class QueueUnavailableError(RuntimeError):
    """Raised when Redis/RQ queue is not reachable."""


def enqueue_job(job_id: str, source_path: str, rebuild: bool = False) -> str:
    """Enqueue a processing task; returns RQ job ID."""
    from apps.worker.tasks.process_job import run_job_task

    try:
        queue = get_queue()
        rq_job = queue.enqueue(
            run_job_task,
            kwargs={"job_id": job_id, "source_path": source_path, "rebuild": rebuild},
            job_id=f"rq_{job_id}",
            # Keep long AI analyses alive as long as worker is still running.
            job_timeout=max(3600, int(settings.rq_job_timeout_seconds)),
            result_ttl=86400,
            failure_ttl=86400,
        )
    except redis.exceptions.RedisError as e:
        logger.error("Redis queue unavailable while enqueueing job %s: %s", job_id, e)
        raise QueueUnavailableError(
            f"Task queue unavailable (Redis: {settings.redis_url}). "
            "Please ensure Redis is running and retry."
        ) from e

    _job_map[job_id] = rq_job.id
    logger.info(f"Enqueued job {job_id} as RQ job {rq_job.id}")
    return rq_job.id


def cancel_job_queue(job_id: str) -> bool:
    """Cancel a queued or running RQ job."""
    rq_job_id = _job_map.get(job_id, f"rq_{job_id}")
    try:
        rq_job = RQJob.fetch(rq_job_id, connection=get_redis())
        rq_job.cancel()
        logger.info(f"Canceled RQ job {rq_job_id} for job {job_id}")
        return True
    except (NoSuchJobError, Exception) as e:
        logger.warning(f"Could not cancel RQ job {rq_job_id}: {e}")
        return False
