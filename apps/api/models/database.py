"""Database session management and initialization."""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from apps.api.config import get_settings
from apps.api.models.db_models import Base


def _get_engine():
    settings = get_settings()
    db_url = settings.database_url

    # Ensure data directory exists
    db_path = db_url.replace("sqlite+aiosqlite:///", "")
    if db_path.startswith("./"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # NullPool is needed for SQLite with async (StaticPool not compatible)
    return create_async_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )


engine = _get_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """FastAPI dependency — yields an async db session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
