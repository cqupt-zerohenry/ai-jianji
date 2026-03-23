"""
Unit tests for DashScope detector parsing/merging utilities.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

from apps.worker.detectors.dashscope_detector import (
    _parse_detection_response, _merge_and_filter_events, _relabel_by_description, _build_windows
)
from apps.api.schemas.detection_schemas import DetectionEvent, EventType


def test_parse_standard_events_with_shot_blocked():
    raw = """
    {
      "events": [
        {"event_type": "GOAL", "timestamp_seconds": 120.3, "confidence": 0.93, "description": "Goal"},
        {"event_type": "SHOT_BLOCKED", "timestamp_seconds": 88.5, "confidence": 0.71, "description": "Blocked"}
      ],
      "video_duration": 600.0
    }
    """
    result = _parse_detection_response(raw, chain="dashscope")
    assert len(result.events) == 2
    assert result.events[0].event_type == EventType.GOAL
    assert result.events[1].event_type == EventType.SHOT_BLOCKED
    assert result.video_duration == 600.0


def test_parse_goal_line_format():
    raw = '\n'.join([
        '{"goal": true, "moment": 101.2}',
        '{"goal": true, "moment": "02:05"}',
        '{"goal": false}',
    ])
    result = _parse_detection_response(raw, chain="dashscope")
    assert len(result.events) == 2
    assert all(e.event_type == EventType.GOAL for e in result.events)
    assert result.events[0].timestamp_seconds == 101.2
    assert result.events[1].timestamp_seconds == 125.0


def test_merge_and_filter_events():
    events = [
        DetectionEvent(event_type=EventType.GOAL, timestamp_seconds=100.0, confidence=0.9, description="A"),
        DetectionEvent(event_type=EventType.GOAL, timestamp_seconds=101.4, confidence=0.8, description="B"),
        DetectionEvent(event_type=EventType.SHOT_BLOCKED, timestamp_seconds=200.0, confidence=0.2, description="low"),
    ]
    merged = _merge_and_filter_events(events, duration=500.0)
    assert len(merged) == 1
    assert merged[0].event_type == EventType.GOAL
    assert merged[0].confidence > 0.9


def test_relabel_goal_bias_from_description():
    ev = DetectionEvent(
        event_type=EventType.GOAL,
        timestamp_seconds=320.0,
        confidence=0.9,
        description="Striker shoots on target but goalkeeper makes a save",
    )
    relabeled = _relabel_by_description(ev)
    assert relabeled.event_type == EventType.SAVE


def test_relabel_goal_for_miss_not_goal():
    ev = DetectionEvent(
        event_type=EventType.GOAL,
        timestamp_seconds=410.0,
        confidence=0.88,
        description="Powerful shot goes wide of goal",
    )
    relabeled = _relabel_by_description(ev)
    assert relabeled.event_type == EventType.SHOT_ON_TARGET
    assert relabeled.confidence < ev.confidence


def test_parse_unknown_event_type_infers_from_description():
    raw = """
    {
      "events": [
        {"event_type": "SHOT_OFF_TARGET", "timestamp_seconds": 300.0, "confidence": 0.74, "description": "Goalkeeper makes a save from close range"}
      ],
      "video_duration": 600.0
    }
    """
    result = _parse_detection_response(raw, chain="dashscope")
    assert len(result.events) == 1
    assert result.events[0].event_type == EventType.SAVE


def test_parse_unknown_event_type_infers_context_event():
    raw = """
    {
      "events": [
        {"event_type": "SET_PIECE", "timestamp_seconds": 410.0, "confidence": 0.76, "description": "Corner kick from the right side"}
      ],
      "video_duration": 600.0
    }
    """
    result = _parse_detection_response(raw, chain="dashscope")
    assert len(result.events) == 1
    assert result.events[0].event_type == EventType.CORNER_KICK


def test_build_windows_downsample_still_covers_full_duration():
    windows = _build_windows(duration=5400.0, window_seconds=180, max_windows=20, overlap_ratio=0.25)
    assert len(windows) <= 20
    assert windows[0][0] == 0.0
    assert windows[-1][1] == 5400.0
