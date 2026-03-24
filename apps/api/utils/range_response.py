"""
HTTP Range-aware file streaming for video seeking support.
Browsers require Range request support to allow <video> seeking.
"""
from __future__ import annotations

import os
import mimetypes
from typing import Generator

from fastapi import Request
from fastapi.responses import StreamingResponse, Response


CHUNK_SIZE = 1024 * 1024  # 1 MB


def _file_iterator(path: str, start: int, end: int) -> Generator[bytes, None, None]:
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def range_file_response(request: Request, file_path: str, filename: str | None = None) -> Response:
    """
    Return a StreamingResponse that honours HTTP Range headers.
    Falls back to a full 200 response when no Range header is present.
    """
    file_size = os.path.getsize(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    fname = filename or os.path.basename(file_path)

    range_header = request.headers.get("range")

    if range_header:
        # Parse "bytes=START-END"
        range_spec = range_header.strip().lower()
        if range_spec.startswith("bytes="):
            range_spec = range_spec[6:]

        parts = range_spec.split("-", 1)
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1

        # Clamp
        start = max(0, start)
        end = min(end, file_size - 1)

        content_length = end - start + 1

        return StreamingResponse(
            _file_iterator(file_path, start, end),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Disposition": f'inline; filename="{fname}"',
            },
        )

    # No Range header — full file
    return StreamingResponse(
        _file_iterator(file_path, 0, file_size - 1),
        status_code=200,
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{fname}"',
        },
    )
