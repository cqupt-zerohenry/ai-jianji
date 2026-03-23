"""
Central configuration loaded from environment variables / .env file.
Single source of truth for all settings across api and worker.
"""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    dashscope_api_key: str = ""
    dashscope_base_http_api_url: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_model: str = "qwen3-vl-flash"
    dashscope_window_seconds: int = 180
    dashscope_frames_per_window: int = 8
    dashscope_max_windows: int = 20
    dashscope_window_overlap_ratio: float = 0.25
    dashscope_request_timeout_seconds: int = 90
    dashscope_window_concurrency: int = 2
    openai_api_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    task_queue_name: str = "football_clip_jobs"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/football_clips.db"

    # Storage
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # Worker
    worker_concurrency: int = 2
    multi_source_detection_concurrency: int = 2
    rq_job_timeout_seconds: int = 14400

    # Detection config
    event_dedup_window_seconds: float = 10.0
    clip_pre_buffer_seconds: float = 5.0
    clip_post_buffer_seconds: float = 3.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
