"""
Helpers for storing/loading source video segment manifests per job.
"""
from __future__ import annotations

import json
import os
from typing import Any
from typing import Optional

from apps.api.config import get_settings

settings = get_settings()


def get_manifest_path(job_id: str) -> str:
    return os.path.join(settings.upload_dir, f"{job_id}_sources.json")


def write_manifest(job_id: str, payload: dict[str, Any]) -> None:
    os.makedirs(settings.upload_dir, exist_ok=True)
    with open(get_manifest_path(job_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_manifest(job_id: str) -> Optional[dict[str, Any]]:
    path = get_manifest_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
