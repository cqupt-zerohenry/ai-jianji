"""
Helpers for storing/loading source video segment manifests per job.
Supports incremental source addition (single → multi upgrade).
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any
from typing import Optional

from apps.api.config import get_settings

settings = get_settings()


def get_manifest_path(job_id: str) -> str:
    return os.path.join(settings.upload_dir, f"{job_id}_sources.json")


def get_parts_dir(job_id: str) -> str:
    return os.path.join(settings.upload_dir, f"{job_id}_parts")


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


def ensure_multi_source(job_id: str, original_source_path: str, original_filename: str) -> dict[str, Any]:
    """
    Upgrade a single-source job to multi-source format.
    If manifest already exists, return it as-is.
    Otherwise, move the original source into the parts dir and create the manifest.
    """
    existing = load_manifest(job_id)
    if existing and existing.get("sources"):
        return existing

    parts_dir = get_parts_dir(job_id)
    os.makedirs(parts_dir, exist_ok=True)

    ext = os.path.splitext(original_source_path)[1] or ".mp4"
    part_path = os.path.join(parts_dir, f"part_000{ext}")

    # Move original file into parts dir (if not already there)
    if not os.path.exists(part_path):
        if os.path.exists(original_source_path):
            shutil.copy2(original_source_path, part_path)

    manifest = {
        "job_id": job_id,
        "sources": [
            {
                "index": 0,
                "name": original_filename or os.path.basename(original_source_path),
                "path": part_path,
            }
        ],
        "status": "uploaded",
        "source_count": 1,
    }
    write_manifest(job_id, manifest)
    return manifest


def append_source(job_id: str, file_path: str, filename: str) -> dict[str, Any]:
    """
    Append a new source video file to an existing manifest.
    The file should already be saved to disk at file_path.
    Returns the updated manifest.
    """
    manifest = load_manifest(job_id)
    if not manifest or not isinstance(manifest.get("sources"), list):
        raise ValueError(f"No valid manifest for job {job_id}")

    sources: list[dict[str, Any]] = manifest["sources"]
    new_index = len(sources)

    sources.append({
        "index": new_index,
        "name": filename,
        "path": file_path,
    })

    manifest["sources"] = sources
    manifest["source_count"] = len(sources)
    write_manifest(job_id, manifest)
    return manifest


def list_sources(job_id: str, fallback_source_path: str | None = None, fallback_filename: str | None = None) -> list[dict[str, Any]]:
    """
    Return the list of sources for a job.
    For single-source jobs without a manifest, synthesize a single entry.
    """
    manifest = load_manifest(job_id)
    if manifest and isinstance(manifest.get("sources"), list) and manifest["sources"]:
        return manifest["sources"]

    # Single-source fallback
    if fallback_source_path and os.path.exists(fallback_source_path):
        return [{
            "index": 0,
            "name": fallback_filename or os.path.basename(fallback_source_path),
            "path": fallback_source_path,
        }]

    return []
