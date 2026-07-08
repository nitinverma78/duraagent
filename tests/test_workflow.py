"""Tests for the durable workflow engine."""

import pytest

from duraagent.events import StepStatus, WorkflowStatus
from duraagent.state_store import StateStore
from duraagent.workflow import (
    DurableWorkflow,
    RetryPolicy,
    Step,
    StepFailedPermanently,
    WorkflowPaused,
)


@pytest.fixture
def store(tmp_path):
    """Create a fresh state store for each test."""
    return StateStore(tmp_path / "test.db")


class TestRetryPolicy:
    """Test retry policy delay calculation."""

    def test_exponential_backoff(self):
        policy = RetryPolicy(base_delay_s=1.0, backoff_multiplier=2.0)
        assert policy.delay_for_attempt(1) == 1.0
        assert policy.delay_for_attempt(2) == 2.0
        assert policy.delay_for_attempt(3) == 4.0

    def test_max_delay_cap(self):
        policy = RetryPolicy(base_delay_s=1.0, backoff_multiplier=10.0, max_delay_s=5.0)
        assert policy.delay_for_attempt(3) == 5.0  # 100.0 capped to 5.0


class TestDurableWorkflow:
    """Test the core workflow engine."""

    def test_simple_workflow_runs_to_completion(self, store):
        steps = [
            Step("s1", lambda x: {"a": 1}),
            Step("s2", lambda x: {"b": 2}),
            Step("s3", lambda x: {"c": 3}),
        ]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")
        result = wf.run()

        assert result == {"c": 3}
        state = store.get_workflow_state("run-1")
        assert state["status"] == WorkflowStatus.COMPLETED.value

    def test_step_output_flows_to_next_step(self, store):
        """Verify data flows through the pipeline."""
        captured = {}

        def s1(inp):
            return {"value": 10}

        def s2(inp):
            captured["s2_input"] = inp
            return {"doubled": inp.get("value", 0) * 2}

        steps = [Step("s1", s1), Step("s2", s2)]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")
        result = wf.run()

        assert captured["s2_input"] == {"value": 10}
        assert result == {"doubled": 20}

    def test_idempotent_resume_skips_completed_steps(self, store):
        """Core durability test: completed steps are skipped on resume."""
        call_counts = {"s1": 0, "s2": 0, "s3": 0}

        def s1(inp):
            call_counts["s1"] += 1
            return {"step": 1}

        def s2(inp):
            call_counts["s2"] += 1
            return {"step": 2}

        def make_s3():
            """s3 fails first time, succeeds second time."""
            attempts = {"count": 0}

            def s3(inp):
                call_counts["s3"] += 1
                attempts["count"] += 1
                if attempts["count"] <= 1:
                    raise RuntimeError("Transient failure")
                return {"step": 3}

            return s3

        steps = [
            Step("s1", s1),
            Step("s2", s2),
            Step("s3", make_s3(), retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.01)),
        ]

        # Run 1: all steps execute, s3 fails once then succeeds on retry
        wf = DurableWorkflow("test", steps, store, run_id="run-1")
        wf.run()

        assert call_counts == {"s1": 1, "s2": 1, "s3": 2}  # s3 called twice (fail + success)

        # Run 2 (resume): all steps should be skipped
        call_counts = {"s1": 0, "s2": 0, "s3": 0}
        wf2 = DurableWorkflow("test", steps, store, run_id="run-1")
        wf2.run()

        assert call_counts == {"s1": 0, "s2": 0, "s3": 0}  # all skipped

    def test_retry_on_transient_failure(self, store):
        """Step retries according to policy."""
        attempts = {"count": 0}

        def flaky(inp):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionError("Transient")
            return {"ok": True}

        steps = [
            Step("flaky", flaky, retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.01))
        ]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")
        result = wf.run()

        assert result == {"ok": True}
        assert attempts["count"] == 3

    def test_permanent_failure_after_max_retries(self, store):
        """Step that always fails raises StepFailedPermanently."""

        def always_fail(inp):
            raise RuntimeError("Always fails")

        steps = [
            Step("fail", always_fail, retry_policy=RetryPolicy(max_attempts=2, base_delay_s=0.01))
        ]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")

        with pytest.raises(StepFailedPermanently) as exc_info:
            wf.run()

        assert exc_info.value.step_name == "fail"
        assert exc_info.value.attempts == 2

        state = store.get_workflow_state("run-1")
        assert state["status"] == WorkflowStatus.FAILED.value

    def test_approval_gate_pauses_workflow(self, store):
        """Workflow pauses at approval gate."""
        steps = [
            Step("s1", lambda x: {"a": 1}),
            Step("approve", lambda x: {}, is_approval_gate=True),
            Step("s3", lambda x: {"c": 3}),
        ]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")

        with pytest.raises(WorkflowPaused):
            wf.run()

        state = store.get_workflow_state("run-1")
        assert state["status"] == WorkflowStatus.PAUSED.value

    def test_event_log_captures_all_actions(self, store):
        """Every action produces events in the log."""
        steps = [
            Step("s1", lambda x: {"v": 1}),
            Step("s2", lambda x: {"v": 2}),
        ]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")
        wf.run()

        events = store.get_events("run-1")
        event_types = [e.event_type for e in events]

        # Should have: workflow_started, step_started, step_completed (x2), workflow_completed
        assert len(events) >= 5

    def test_get_run_summary(self, store):
        steps = [
            Step("s1", lambda x: {"v": 1}),
        ]
        wf = DurableWorkflow("test", steps, store, run_id="run-1")
        wf.run()

        summary = wf.get_run_summary()
        assert summary["run_id"] == "run-1"
        assert summary["total_events"] > 0
