"""
Detection pipeline — multimodal fusion when both visual and audio-semantic
chains are available, single-chain fallback otherwise, and hard-fail when no
real AI chain is configured.
"""
from __future__ import annotations
import asyncio
import hashlib
import inspect
import json
import logging
import os
import time
from typing import Optional, Callable

from apps.api.schemas.detection_schemas import (
    DetectionResult
)
from apps.api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_DETECTION_CACHE_VERSION = "v1"


async def _emit_progress(progress_callback, value: float) -> None:
    if not progress_callback:
        return
    try:
        ret = progress_callback(max(0.0, min(1.0, float(value))))
        if inspect.isawaitable(ret):
            await ret
    except Exception:
        return


def _should_use_detection_cache(has_dashscope: bool, has_audio_chain: bool) -> bool:
    # Cache only meaningful (and deterministic enough) when real inference chains are enabled.
    return bool(settings.detection_cache_enabled) and (has_dashscope or has_audio_chain)


def _build_detection_cache_key(
    source_path: str,
    video_duration: float,
    has_dashscope: bool,
    has_audio_chain: bool,
) -> Optional[str]:
    if not source_path or not os.path.exists(source_path):
        return None

    try:
        stat = os.stat(source_path)
    except OSError:
        return None

    payload = {
        "version": _DETECTION_CACHE_VERSION,
        "source_path": os.path.abspath(source_path),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "video_duration": round(float(video_duration or 0.0), 3),
        "dashscope_enabled": bool(has_dashscope),
        "audio_chain_enabled": bool(has_audio_chain),
        # Inference-related knobs (cache should invalidate when these change).
        "dashscope_model": settings.dashscope_model,
        "dashscope_audio_asr_model": settings.dashscope_audio_asr_model,
        "dashscope_audio_text_model": settings.dashscope_audio_text_model,
        "dashscope_window_seconds": settings.dashscope_window_seconds,
        "dashscope_frames_per_window": settings.dashscope_frames_per_window,
        "dashscope_max_windows": settings.dashscope_max_windows,
        "dashscope_window_overlap_ratio": settings.dashscope_window_overlap_ratio,
        "dashscope_request_timeout_seconds": settings.dashscope_request_timeout_seconds,
        "dashscope_window_concurrency": settings.dashscope_window_concurrency,
        "dashscope_compatible_base_url": settings.dashscope_compatible_base_url,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _get_detection_cache_path(cache_key: str) -> str:
    return os.path.join(settings.detection_cache_dir, f"{cache_key}.json")


def _load_detection_cache(cache_key: str) -> Optional[DetectionResult]:
    cache_path = _get_detection_cache_path(cache_key)
    if not os.path.exists(cache_path):
        return None

    ttl = max(0, int(settings.detection_cache_ttl_seconds))
    if ttl > 0:
        try:
            age_seconds = time.time() - os.path.getmtime(cache_path)
            if age_seconds > ttl:
                os.remove(cache_path)
                return None
        except OSError:
            return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        result_payload = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result_payload, dict):
            return None
        result = DetectionResult.model_validate(result_payload)
        return result
    except Exception:
        return None


def _save_detection_cache(cache_key: str, result: DetectionResult) -> None:
    os.makedirs(settings.detection_cache_dir, exist_ok=True)
    cache_path = _get_detection_cache_path(cache_key)
    tmp_path = f"{cache_path}.tmp.{os.getpid()}"
    payload = {
        "cached_at": int(time.time()),
        "result": result.model_dump(mode="json"),
    }
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def run_detection_pipeline(
    source_path: str,
    video_duration: float = 0.0,
    progress_callback: Optional[Callable] = None,
) -> DetectionResult:
    """
    Detection strategy:
    - Visual DashScope + audio-semantic Qwen chain available: run in parallel, fuse.
    - Single chain available: run that chain alone.
    - No keys: fail fast (production-safe behavior).
    """
    has_dashscope = bool(settings.dashscope_api_key)
    has_audio_chain = bool(
        settings.dashscope_api_key
        and settings.dashscope_audio_asr_model
        and settings.dashscope_audio_text_model
    )
    cache_key: Optional[str] = None
    if _should_use_detection_cache(has_dashscope, has_audio_chain):
        cache_key = _build_detection_cache_key(
            source_path=source_path,
            video_duration=video_duration,
            has_dashscope=has_dashscope,
            has_audio_chain=has_audio_chain,
        )
        if cache_key:
            cached_result = _load_detection_cache(cache_key)
            if cached_result:
                if cached_result.video_duration is None:
                    cached_result.video_duration = video_duration
                logger.info("Detection cache hit: %s (%s)", source_path, cached_result.chain_used)
                await _emit_progress(progress_callback, 1.0)
                return cached_result

    # ── Multimodal fusion mode (both keys configured) ─────────────────
    if has_dashscope and has_audio_chain:
        result = await _run_fusion_detection(source_path, video_duration, progress_callback)
        if result.video_duration is None:
            result.video_duration = video_duration
        if cache_key:
            _save_detection_cache(cache_key, result)
        return result

    # ── Single-chain mode ─────────────────────────────────────────────
    dashscope_error: Optional[Exception] = None
    audio_chain_error: Optional[Exception] = None

    if has_dashscope:
        try:
            from apps.worker.detectors.dashscope_detector import detect_with_dashscope
            logger.info("Running DashScope detection...")
            result = await detect_with_dashscope(source_path, progress_callback)
            if result.video_duration is None:
                result.video_duration = video_duration
            if cache_key:
                _save_detection_cache(cache_key, result)
            logger.info(f"DashScope detected {len(result.events)} events")
            return result
        except Exception as e:
            dashscope_error = e
            logger.warning(f"DashScope chain failed: {e}")

    if has_audio_chain:
        try:
            from apps.worker.detectors.openai_detector import detect_with_openai
            logger.info("Running Qwen audio-semantic detection fallback...")
            result = await detect_with_openai(source_path, progress_callback)
            if result.video_duration is None:
                result.video_duration = video_duration
            if cache_key:
                _save_detection_cache(cache_key, result)
            logger.info("Qwen audio-semantic chain detected %d events", len(result.events))
            return result
        except Exception as e:
            audio_chain_error = e
            logger.warning("Qwen audio-semantic chain failed: %s", e)

    if has_dashscope or has_audio_chain:
        parts = []
        if dashscope_error is not None:
            parts.append(f"DashScope failed: {dashscope_error}")
        if audio_chain_error is not None:
            parts.append(f"Qwen audio chain failed: {audio_chain_error}")
        reason = " | ".join(parts) if parts else "No AI chain succeeded."
        raise RuntimeError(
            "AI detection failed when API keys are configured. "
            + reason
        )

    raise RuntimeError(
        "No AI detection chain available. Configure DASHSCOPE_API_KEY."
    )


async def _run_fusion_detection(
    source_path: str,
    video_duration: float,
    progress_callback: Optional[Callable],
) -> DetectionResult:
    """Run DashScope visual chain + Qwen audio-semantic chain in parallel, then fuse."""
    from apps.worker.detectors.dashscope_detector import detect_with_dashscope
    from apps.worker.detectors.openai_detector import detect_with_openai
    from apps.worker.detectors.event_merger import fuse_multimodal_events

    logger.info("Running multimodal fusion detection (DashScope visual + Qwen audio)")

    results = await asyncio.gather(
        detect_with_dashscope(source_path, progress_callback),
        detect_with_openai(source_path),
        return_exceptions=True,
    )

    dashscope_result = results[0]
    audio_result = results[1]

    dashscope_ok = isinstance(dashscope_result, DetectionResult)
    audio_ok = isinstance(audio_result, DetectionResult)

    # Both succeeded → fuse
    if dashscope_ok and audio_ok:
        duration = video_duration or dashscope_result.video_duration or audio_result.video_duration or 0.0
        fused_events = fuse_multimodal_events(
            visual_events=dashscope_result.events,
            audio_events=audio_result.events,
            duration=duration,
        )
        logger.info(
            "Multimodal fusion: %d visual + %d audio → %d fused events",
            len(dashscope_result.events),
            len(audio_result.events),
            len(fused_events),
        )
        return DetectionResult(
            events=fused_events,
            chain_used="dashscope+qwen-audio",
            video_duration=duration if duration > 0 else None,
            raw_response=dashscope_result.raw_response,
        )

    # Graceful degradation: one succeeded
    if dashscope_ok:
        logger.warning("Qwen audio chain failed during fusion (%s), using DashScope only", audio_result)
        if dashscope_result.video_duration is None:
            dashscope_result.video_duration = video_duration
        return dashscope_result

    if audio_ok:
        logger.warning("DashScope visual chain failed during fusion (%s), using Qwen audio only", dashscope_result)
        if audio_result.video_duration is None:
            audio_result.video_duration = video_duration
        return audio_result

    # Both failed
    raise RuntimeError(
        f"Multimodal fusion: both chains failed. "
        f"DashScope: {dashscope_result} | Qwen audio: {audio_result}"
    )
