"""
Redis client and queue connection.
Only used for task queue scheduling — NOT for persistent state.
"""
from __future__ import annotations
from typing import Optional
import redis
from apps.api.config import get_settings

_settings = get_settings()
_redis_client = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            _settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=5,
        )
    return _redis_client


def get_queue(name: Optional[str] = None):
    """Return an RQ Queue instance."""
    from rq import Queue
    r = get_redis()
    return Queue(name or _settings.task_queue_name, connection=r)


def ping_redis() -> bool:
    """Health check — True if Redis is reachable."""
    try:
        get_redis().ping()
        return True
    except Exception:
        return False
