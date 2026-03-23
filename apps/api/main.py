"""
FastAPI application entry point.
Registers routers, CORS, and initializes DB on startup.
"""
import sys
import os

# Allow imports from monorepo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging

from apps.api.config import get_settings
from apps.api.models.database import init_db
from apps.api.routers import jobs, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

settings = get_settings()

app = FastAPI(
    title="Football Clip System API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(jobs.router)
app.include_router(health.router)


@app.on_event("startup")
async def startup():
    # Ensure data directories exist
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)
    os.makedirs("./data", exist_ok=True)
    # Initialize DB tables
    await init_db()
    logging.getLogger("main").info("API started, DB initialized")


@app.get("/")
async def root():
    return {"message": "Football Clip System API", "docs": "/api/docs"}
