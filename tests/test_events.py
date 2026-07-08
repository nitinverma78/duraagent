"""Tests for the immutable event system."""

import json
from duraagent.events import (
    Event,
    EventType,
    workflow_started,
    workflow_completed,
    step_started,
    step_completed,
    step_failed,
    step_skipped,
    memory_stored,
    llm_call_recorded,
)


class TestEvent:
    """Test Event creation, serialization, and immutability."""

    def test_event_creation(self):
        event = Event(
            event_id="test-1",
            run_id="run-1",
            event_type=EventType.WORKFLOW_STARTED,
            payload={"workflow_name": "test"},
        )
        assert event.event_id == "test-1"
        assert event.run_id == "run-1"

    def test_event_is_immutable(self):
        event = Event(event_id="test-1", run_id="run-1")
        try:
            event.run_id = "changed"  # type: ignore
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass  # Expected — frozen dataclass

    def test_event_serialization_roundtrip(self):
        event = workflow_started("run-1", "my_workflow", {"key": "value"})
        json_str = event.to_json()
        restored = Event.from_json(json_str)
        assert restored.run_id == event.run_id
        assert restored.event_type == event.event_type
        assert restored.payload["workflow_name"] == "my_workflow"
        assert restored.payload["config"] == {"key": "value"}

    def test_event_has_uuid(self):
        event = Event(run_id="run-1")
        assert event.event_id  # auto-generated UUID
        assert len(event.event_id) == 36  # UUID format

    def test_event_has_timestamp(self):
        event = Event(run_id="run-1")
        assert event.timestamp  # auto-generated
        assert "T" in event.timestamp  # ISO format


class TestEventFactories:
    """Test that factory functions produce correctly structured events."""

    def test_workflow_started(self):
        event = workflow_started("run-1", "code_review", {"diff": "..."})
        assert event.event_type == EventType.WORKFLOW_STARTED
        assert event.payload["workflow_name"] == "code_review"
        assert event.payload["config"] == {"diff": "..."}

    def test_workflow_completed(self):
        event = workflow_completed("run-1", {"steps": 5})
        assert event.event_type == EventType.WORKFLOW_COMPLETED
        assert event.payload["summary"]["steps"] == 5

    def test_step_started(self):
        event = step_started("run-1", "analyze", 0, {"code": "..."})
        assert event.payload["step_name"] == "analyze"
        assert event.payload["step_index"] == 0
        assert event.payload["input_data"]["code"] == "..."

    def test_step_completed(self):
        event = step_completed("run-1", "analyze", 0, {"issues": []}, 150.5)
        assert event.payload["duration_ms"] == 150.5
        assert event.payload["output_data"]["issues"] == []

    def test_step_failed(self):
        event = step_failed("run-1", "call_llm", 2, "Timeout", 1, True)
        assert event.payload["attempt"] == 1
        assert event.payload["will_retry"] is True
        assert event.payload["error"] == "Timeout"

    def test_step_skipped(self):
        event = step_skipped("run-1", "fetch_code", 0)
        assert event.payload["reason"] == "already_completed"

    def test_memory_stored(self):
        event = memory_stored("run-1", "repo/x", "uses ruff not black")
        assert event.payload["key"] == "repo/x"
        assert event.payload["fact"] == "uses ruff not black"

    def test_llm_call_recorded(self):
        event = llm_call_recorded(
            "run-1", "analyze", "claude-sonnet-4-20250514", 500, 200, 1200.0, "abc123"
        )
        assert event.payload["input_tokens"] == 500
        assert event.payload["output_tokens"] == 200
        assert event.payload["prompt_hash"] == "abc123"
