"""Health check endpoint — verifies API, Redis, and SQLite."""
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from apps.api.models.database import get_db
from apps.api.queue.redis_client import ping_redis
from apps.api.schemas.job_schemas import HealthCheck

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthCheck)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Check API, Redis, and SQLite connectivity."""
    # Check SQLite
    sqlite_ok = False
    try:
        await db.execute(text("SELECT 1"))
        sqlite_ok = True
    except Exception:
        pass

    # Check Redis
    redis_ok = ping_redis()

    overall = "ok" if (sqlite_ok and redis_ok) else "degraded"

    return HealthCheck(
        status=overall,
        api=True,
        redis=redis_ok,
        sqlite=sqlite_ok,
        timestamp=datetime.utcnow(),
    )
