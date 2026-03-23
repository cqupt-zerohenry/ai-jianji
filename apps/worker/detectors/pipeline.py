"""
Detection pipeline — multimodal fusion when both keys available,
single-chain fallback otherwise, mock for dev mode.
"""
from __future__ import annotations
import asyncio
import logging
import random
from typing import Optional, Callable

from apps.api.schemas.detection_schemas import (
    DetectionResult, DetectionEvent, EventType
)
from apps.api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def run_detection_pipeline(
    source_path: str,
    video_duration: float = 0.0,
    progress_callback: Optional[Callable] = None,
) -> DetectionResult:
    """
    Detection strategy:
    - Both DashScope + OpenAI keys: run in parallel, fuse results.
    - Single key: run that chain alone.
    - No keys: mock fallback (dev mode).
    """
    has_dashscope = bool(settings.dashscope_api_key)
    has_openai = bool(settings.openai_api_key)

    # ── Multimodal fusion mode (both keys configured) ─────────────────
    if has_dashscope and has_openai:
        return await _run_fusion_detection(source_path, video_duration, progress_callback)

    # ── Single-chain mode ─────────────────────────────────────────────
    dashscope_error: Optional[Exception] = None
    openai_error: Optional[Exception] = None

    if has_dashscope:
        try:
            from apps.worker.detectors.dashscope_detector import detect_with_dashscope
            logger.info("Running DashScope detection...")
            result = await detect_with_dashscope(source_path, progress_callback)
            if result.video_duration is None:
                result.video_duration = video_duration
            logger.info(f"DashScope detected {len(result.events)} events")
            return result
        except Exception as e:
            dashscope_error = e
            logger.warning(f"DashScope chain failed: {e}")

    if has_openai:
        try:
            from apps.worker.detectors.openai_detector import detect_with_openai
            logger.info("Running OpenAI detection fallback...")
            result = await detect_with_openai(source_path, progress_callback)
            if result.video_duration is None:
                result.video_duration = video_duration
            logger.info(f"OpenAI detected {len(result.events)} events")
            return result
        except Exception as e:
            openai_error = e
            logger.warning(f"OpenAI chain failed: {e}")

    if has_dashscope or has_openai:
        parts = []
        if dashscope_error is not None:
            parts.append(f"DashScope failed: {dashscope_error}")
        if openai_error is not None:
            parts.append(f"OpenAI failed: {openai_error}")
        reason = " | ".join(parts) if parts else "No AI chain succeeded."
        raise RuntimeError(
            "AI detection failed and mock fallback is disabled when API keys are configured. "
            + reason
        )

    # Mock fallback (dev mode only, no API keys configured)
    logger.warning("No AI API keys configured — using mock detection for development")
    return _generate_mock_detection(video_duration)


async def _run_fusion_detection(
    source_path: str,
    video_duration: float,
    progress_callback: Optional[Callable],
) -> DetectionResult:
    """Run DashScope (visual) + OpenAI (audio) in parallel, fuse results."""
    from apps.worker.detectors.dashscope_detector import detect_with_dashscope
    from apps.worker.detectors.openai_detector import detect_with_openai
    from apps.worker.detectors.event_merger import fuse_multimodal_events

    logger.info("Running multimodal fusion detection (DashScope + OpenAI)")

    results = await asyncio.gather(
        detect_with_dashscope(source_path, progress_callback),
        detect_with_openai(source_path),
        return_exceptions=True,
    )

    dashscope_result = results[0]
    openai_result = results[1]

    dashscope_ok = isinstance(dashscope_result, DetectionResult)
    openai_ok = isinstance(openai_result, DetectionResult)

    # Both succeeded → fuse
    if dashscope_ok and openai_ok:
        duration = video_duration or dashscope_result.video_duration or openai_result.video_duration or 0.0
        fused_events = fuse_multimodal_events(
            visual_events=dashscope_result.events,
            audio_events=openai_result.events,
            duration=duration,
        )
        logger.info(
            "Multimodal fusion: %d visual + %d audio → %d fused events",
            len(dashscope_result.events),
            len(openai_result.events),
            len(fused_events),
        )
        return DetectionResult(
            events=fused_events,
            chain_used="dashscope+openai",
            video_duration=duration if duration > 0 else None,
            raw_response=dashscope_result.raw_response,
        )

    # Graceful degradation: one succeeded
    if dashscope_ok:
        logger.warning("OpenAI chain failed during fusion (%s), using DashScope only", openai_result)
        if dashscope_result.video_duration is None:
            dashscope_result.video_duration = video_duration
        return dashscope_result

    if openai_ok:
        logger.warning("DashScope chain failed during fusion (%s), using OpenAI only", dashscope_result)
        if openai_result.video_duration is None:
            openai_result.video_duration = video_duration
        return openai_result

    # Both failed
    raise RuntimeError(
        f"Multimodal fusion: both chains failed. "
        f"DashScope: {dashscope_result} | OpenAI: {openai_result}"
    )


def _generate_mock_detection(duration: float) -> DetectionResult:
    """Generate realistic-looking mock events for development/demo."""
    if duration <= 0:
        duration = 5400.0  # 90 min default

    event_templates = [
        (EventType.GOAL, 0.95, "Spectacular goal scored!"),
        (EventType.CORNER_KICK, 0.82, "Dangerous corner kick delivered"),
        (EventType.FREE_KICK, 0.81, "Free kick from the edge of the box"),
        (EventType.SHOT_ON_TARGET, 0.88, "Shot on target, goalkeeper saves"),
        (EventType.SHOT_BLOCKED, 0.86, "Powerful shot blocked by defender"),
        (EventType.SAVE, 0.92, "Brilliant save by goalkeeper"),
        (EventType.OFFSIDE, 0.84, "Attack halted for offside"),
        (EventType.FOUL, 0.83, "Midfield foul stops the counter attack"),
        (EventType.YELLOW_CARD, 0.97, "Foul play, yellow card shown"),
        (EventType.SUBSTITUTION, 0.8, "Substitution: fresh striker comes on"),
        (EventType.SHOT_ON_TARGET, 0.85, "Long range effort tests keeper"),
        (EventType.HIGHLIGHT, 0.78, "Exciting build-up play"),
        (EventType.GOAL, 0.93, "Header goal from corner kick"),
        (EventType.RED_CARD, 0.99, "Serious foul, red card!"),
        (EventType.PENALTY, 0.96, "Penalty awarded after VAR review"),
        (EventType.VAR, 0.90, "VAR check underway"),
        (EventType.SAVE, 0.88, "Penalty saved!"),
    ]

    events = []
    num_events = min(len(event_templates), max(3, int(duration / 500)))
    step = duration / (num_events + 1)

    for i in range(num_events):
        template = event_templates[i % len(event_templates)]
        timestamp = step * (i + 1) + random.uniform(-30, 30)
        timestamp = max(30.0, min(duration - 30.0, timestamp))
        events.append(
            DetectionEvent(
                event_type=template[0],
                timestamp_seconds=round(timestamp, 1),
                confidence=template[1],
                description=template[2],
            )
        )

    return DetectionResult(
        events=events,
        chain_used="mock",
        video_duration=duration,
    )
