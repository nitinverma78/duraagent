"""Tests for the event-sourced state store."""

import json
import tempfile
import os

import pytest

from duraagent.events import (
    EventType,
    StepStatus,
    WorkflowStatus,
    workflow_started,
    workflow_completed,
    step_started,
    step_completed,
    step_failed,
    step_skipped,
    memory_stored,
)
from duraagent.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    """Create a fresh state store for each test."""
    db_path = tmp_path / "test.db"
    return StateStore(db_path)


class TestEventLog:
    """Test the append-only event log."""

    def test_append_and_retrieve_events(self, store):
        event = workflow_started("run-1", "test_workflow")
        store.append_event(event)

        events = store.get_events("run-1")
        assert len(events) == 1
        assert events[0].run_id == "run-1"
        assert events[0].payload["workflow_name"] == "test_workflow"

    def test_events_ordered_by_sequence(self, store):
        store.append_event(step_started("run-1", "step_a", 0))
        store.append_event(step_completed("run-1", "step_a", 0, {"result": "a"}))
        store.append_event(step_started("run-1", "step_b", 1))
        store.append_event(step_completed("run-1", "step_b", 1, {"result": "b"}))

        events = store.get_events("run-1")
        assert len(events) == 4
        assert events[0].payload["step_name"] == "step_a"
        assert events[2].payload["step_name"] == "step_b"

    def test_events_isolated_by_run(self, store):
        store.append_event(workflow_started("run-1", "wf1"))
        store.append_event(workflow_started("run-2", "wf2"))

        assert len(store.get_events("run-1")) == 1
        assert len(store.get_events("run-2")) == 1
        assert len(store.get_events("run-3")) == 0


class TestMaterializedViews:
    """Test the derived materialized state views."""

    def test_workflow_state_created_on_start(self, store):
        store.append_event(workflow_started("run-1", "test_wf"))
        state = store.get_workflow_state("run-1")
        assert state is not None
        assert state["status"] == WorkflowStatus.RUNNING.value
        assert state["workflow_name"] == "test_wf"

    def test_workflow_state_completed(self, store):
        store.append_event(workflow_started("run-1", "test_wf"))
        store.append_event(workflow_completed("run-1"))
        state = store.get_workflow_state("run-1")
        assert state["status"] == WorkflowStatus.COMPLETED.value

    def test_step_state_tracking(self, store):
        store.append_event(workflow_started("run-1", "test_wf"))
        store.append_event(step_started("run-1", "analyze", 0, {"code": "x"}))
        store.append_event(step_completed("run-1", "analyze", 0, {"issues": 3}, 100.0))

        step = store.get_step_state("run-1", "analyze")
        assert step is not None
        assert step["status"] == StepStatus.COMPLETED.value
        assert step["duration_ms"] == 100.0

    def test_step_failure_tracking(self, store):
        store.append_event(workflow_started("run-1", "test_wf"))
        store.append_event(step_started("run-1", "call_llm", 1))
        store.append_event(step_failed("run-1", "call_llm", 1, "Timeout", 1, True))

        step = store.get_step_state("run-1", "call_llm")
        assert step["status"] == StepStatus.FAILED.value
        assert step["error"] == "Timeout"
        assert step["attempt"] == 1

    def test_last_completed_step_index(self, store):
        store.append_event(workflow_started("run-1", "test_wf"))
        assert store.get_last_completed_step_index("run-1") == -1

        store.append_event(step_started("run-1", "step_0", 0))
        store.append_event(step_completed("run-1", "step_0", 0, {}))
        assert store.get_last_completed_step_index("run-1") == 0

        store.append_event(step_started("run-1", "step_1", 1))
        store.append_event(step_completed("run-1", "step_1", 1, {}))
        assert store.get_last_completed_step_index("run-1") == 1

    def test_get_all_step_states(self, store):
        store.append_event(workflow_started("run-1", "test_wf"))
        store.append_event(step_started("run-1", "a", 0))
        store.append_event(step_completed("run-1", "a", 0, {}))
        store.append_event(step_started("run-1", "b", 1))
        store.append_event(step_completed("run-1", "b", 1, {}))

        steps = store.get_all_step_states("run-1")
        assert len(steps) == 2
        assert steps[0]["step_name"] == "a"
        assert steps[1]["step_name"] == "b"


class TestReplay:
    """Test that materialized views can be rebuilt from events."""

    def test_rebuild_produces_same_state(self, store):
        # Create a workflow with several steps
        store.append_event(workflow_started("run-1", "test_wf"))
        store.append_event(step_started("run-1", "s1", 0))
        store.append_event(step_completed("run-1", "s1", 0, {"v": 1}, 50.0))
        store.append_event(step_started("run-1", "s2", 1))
        store.append_event(step_failed("run-1", "s2", 1, "boom", 1, True))
        store.append_event(step_started("run-1", "s2", 1))
        store.append_event(step_completed("run-1", "s2", 1, {"v": 2}, 75.0))
        store.append_event(workflow_completed("run-1"))

        # Snapshot the current state
        original_wf = store.get_workflow_state("run-1")
        original_steps = store.get_all_step_states("run-1")

        # Rebuild from events
        store.rebuild_materialized_views("run-1")

        # Verify consistency
        rebuilt_wf = store.get_workflow_state("run-1")
        rebuilt_steps = store.get_all_step_states("run-1")

        assert rebuilt_wf["status"] == original_wf["status"]
        assert rebuilt_wf["last_step_index"] == original_wf["last_step_index"]
        assert len(rebuilt_steps) == len(original_steps)


class TestMemory:
    """Test cross-run memory operations."""

    def test_store_and_retrieve_memory(self, store):
        store.store_memory("repo/myapp", "uses ruff for formatting", "run-1")
        store.store_memory("repo/myapp", "tests need DATABASE_URL env var", "run-1")

        memories = store.get_memories("repo/myapp")
        assert len(memories) == 2
        facts = [m["fact"] for m in memories]
        assert "uses ruff for formatting" in facts

    def test_memory_is_idempotent(self, store):
        store.store_memory("repo/x", "fact_a", "run-1")
        store.store_memory("repo/x", "fact_a", "run-2")  # duplicate

        memories = store.get_memories("repo/x")
        assert len(memories) == 1  # deduped

    def test_memory_isolated_by_repo(self, store):
        store.store_memory("repo/a", "fact_a")
        store.store_memory("repo/b", "fact_b")

        assert len(store.get_memories("repo/a")) == 1
        assert len(store.get_memories("repo/b")) == 1
        assert len(store.get_memories("repo/c")) == 0

    def test_get_all_runs(self, store):
        store.append_event(workflow_started("run-1", "wf_a"))
        store.append_event(workflow_started("run-2", "wf_b"))

        runs = store.get_all_runs()
        assert len(runs) == 2
