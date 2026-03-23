"""
Helpers for locating ffmpeg/ffprobe across common local setups.
"""
from __future__ import annotations

import os
from functools import lru_cache
from shutil import which
from typing import Optional

COMMON_BIN_DIRS = (
    "/opt/homebrew/bin",  # macOS (Apple Silicon Homebrew)
    "/usr/local/bin",     # macOS/Linux
    "/usr/bin",
    "/bin",
)


@lru_cache(maxsize=None)
def find_binary(name: str) -> Optional[str]:
    """Return executable path if available, else None."""
    path = which(name)
    if path:
        return path

    for directory in COMMON_BIN_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def require_binary(name: str) -> str:
    """Return executable path or raise a clear setup error."""
    path = find_binary(name)
    if path:
        return path
    raise RuntimeError(
        f"Missing required executable: {name}. "
        "Please install FFmpeg and ensure ffmpeg/ffprobe are available. "
        "macOS: `brew install ffmpeg`; Ubuntu/Debian: `sudo apt-get install -y ffmpeg`."
    )
