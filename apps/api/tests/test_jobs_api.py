"""
Integration tests for job API endpoints.
Run with: python -m pytest apps/api/tests/test_jobs_api.py -v
Requires: no Redis/SQLite running — uses TestClient with in-memory setup
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Patch settings for test environment
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_football.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")  # test DB

from apps.api.main import app
from apps.api.models.database import init_db

@pytest_asyncio.fixture
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "api" in data
    assert data["api"] is True


@pytest.mark.asyncio
async def test_list_jobs_empty(client):
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_upload_invalid_type(client):
    import io
    resp = await client.post(
        "/api/jobs",
        files={"file": ("test.txt", io.BytesIO(b"not a video"), "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_nonexistent_job(client):
    resp = await client.get("/api/jobs/nonexistent-id")
    assert resp.status_code == 404
