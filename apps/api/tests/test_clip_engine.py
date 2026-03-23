"""
Unit tests for clip engine — deduplication and plan generation.
Run with: python -m pytest apps/api/tests/test_clip_engine.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

import pytest
import apps.api.services.clip_engine as clip_engine
from apps.api.services.clip_engine import deduplicate_events, build_clip_plan
from apps.api.schemas.detection_schemas import (
    DetectionEvent, DetectionResult, EventType
)


def make_event(event_type: EventType, ts: float, conf: float = 0.9) -> DetectionEvent:
    return DetectionEvent(
        event_type=event_type,
        timestamp_seconds=ts,
        confidence=conf,
        description=f"{event_type.value} at {ts}s",
    )


class TestDeduplication:
    def test_empty(self):
        assert deduplicate_events([]) == []

    def test_no_duplicates(self):
        events = [
            make_event(EventType.GOAL, 100.0),
            make_event(EventType.SAVE, 200.0),
        ]
        result = deduplicate_events(events, window_seconds=10.0)
        assert len(result) == 2

    def test_removes_duplicate_within_window(self):
        events = [
            make_event(EventType.GOAL, 100.0, conf=0.9),
            make_event(EventType.GOAL, 105.0, conf=0.7),  # within 10s window
        ]
        result = deduplicate_events(events, window_seconds=10.0)
        assert len(result) == 1
        assert result[0].confidence == 0.9  # keeps higher confidence

    def test_keeps_duplicate_outside_window(self):
        events = [
            make_event(EventType.GOAL, 100.0),
            make_event(EventType.GOAL, 115.0),  # outside 10s window
        ]
        result = deduplicate_events(events, window_seconds=10.0)
        assert len(result) == 2

    def test_different_types_not_deduped(self):
        events = [
            make_event(EventType.GOAL, 100.0),
            make_event(EventType.SAVE, 101.0),  # different type, same time
        ]
        result = deduplicate_events(events, window_seconds=10.0)
        assert len(result) == 2


class TestBuildClipPlan:
    def test_empty_events(self):
        result = DetectionResult(events=[], chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        assert plan["clips"] == []
        assert plan["total_events"] == 0

    def test_clips_clamped_to_duration(self):
        events = [make_event(EventType.GOAL, 10.0)]  # near start
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result, pre_buffer=20.0, post_buffer=10.0)
        clip = plan["clips"][0]
        assert clip["start_time"] >= 0.0
        assert clip["end_time"] <= 5400.0

    def test_default_window_is_extended_for_shot_context(self):
        events = [make_event(EventType.SHOT_ON_TARGET, 100.0)]
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        clip = plan["clips"][0]
        assert clip["start_time"] <= 94.0
        assert clip["end_time"] >= 106.5

    def test_clips_have_transition_suggestions(self):
        events = [
            make_event(EventType.GOAL, 1000.0),
            make_event(EventType.RED_CARD, 2000.0),
        ]
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        goal_clip = next(c for c in plan["clips"] if c["event_type"] == "GOAL")
        card_clip = next(c for c in plan["clips"] if c["event_type"] == "RED_CARD")
        assert goal_clip["transition_type"] == "fade"
        assert card_clip["transition_type"] == "wipe"

    def test_events_sorted_by_timeline_order(self):
        events = [
            make_event(EventType.HIGHLIGHT, 100.0),
            make_event(EventType.GOAL, 200.0),
        ]
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        assert plan["clips"][0]["event_type"] == "HIGHLIGHT"
        assert plan["clips"][1]["event_type"] == "GOAL"

    def test_multi_source_same_timestamp_not_deduped(self):
        events = [
            DetectionEvent(
                event_type=EventType.GOAL,
                timestamp_seconds=120.0,
                confidence=0.91,
                description="Cam A goal",
                metadata={"source_index": 0, "source_name": "Cam A", "source_path": "/tmp/a.mp4"},
            ),
            DetectionEvent(
                event_type=EventType.GOAL,
                timestamp_seconds=121.0,  # within dedup window
                confidence=0.90,
                description="Cam B goal",
                metadata={"source_index": 1, "source_name": "Cam B", "source_path": "/tmp/b.mp4"},
            ),
        ]
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result, pre_buffer=2.0, post_buffer=2.0)

        assert len(plan["clips"]) == 2
        assert {c.get("source_index") for c in plan["clips"]} == {0, 1}

    def test_diversity_keeps_non_shot_events(self):
        events = []
        for i in range(14):
            events.append(make_event(EventType.SHOT_ON_TARGET, 40.0 + i * 8.0, conf=0.86))
        events.extend([
            make_event(EventType.CORNER_KICK, 70.0, conf=0.82),
            make_event(EventType.FOUL, 130.0, conf=0.83),
            make_event(EventType.SUBSTITUTION, 190.0, conf=0.9),
            make_event(EventType.OFFSIDE, 250.0, conf=0.87),
        ])

        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        event_types = [c["event_type"] for c in plan["clips"]]

        assert "CORNER_KICK" in event_types
        assert "FOUL" in event_types
        assert "SUBSTITUTION" in event_types
        shot_count = sum(1 for t in event_types if t in {"SHOT_ON_TARGET", "SHOT_BLOCKED", "SAVE"})
        assert shot_count < len(event_types)

    def test_new_event_transition_suggestions(self):
        events = [
            make_event(EventType.CORNER_KICK, 100.0),
            make_event(EventType.SUBSTITUTION, 200.0),
        ]
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        corner = next(c for c in plan["clips"] if c["event_type"] == "CORNER_KICK")
        sub = next(c for c in plan["clips"] if c["event_type"] == "SUBSTITUTION")
        assert corner["transition_type"] == "slide"
        assert sub["transition_type"] == "wipe"

    def test_foul_clip_extends_to_referee_decision_context(self):
        events = [
            make_event(EventType.FOUL, 200.0, conf=0.85),
            make_event(EventType.YELLOW_CARD, 212.0, conf=0.9),
        ]
        result = DetectionResult(events=events, chain_used="mock", video_duration=5400.0)
        plan = build_clip_plan(result)
        foul_clip = next(c for c in plan["clips"] if c["event_type"] == "FOUL")
        # Should include yellow-card decision aftermath, not end immediately at foul.
        assert foul_clip["end_time"] >= 221.0


def test_get_video_duration_without_ffprobe(monkeypatch, tmp_path):
    video_file = tmp_path / "sample.mp4"
    video_file.write_text("not-a-real-video")

    monkeypatch.setattr(clip_engine, "find_binary", lambda _: None)
    duration = clip_engine.get_video_duration(str(video_file))

    assert duration == 0.0
