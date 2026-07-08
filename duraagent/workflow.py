"""
Durable workflow engine for DuraAgent.

This is the orchestration layer that provides:
- Crash recovery: resume from the last completed step
- Idempotency: steps check "have I already completed?" before executing
- Retry policy: exponential backoff on transient failures
- Positional awareness: the engine always knows "where am I?"
- Pause/resume: support for human-in-the-loop approval gates

Design philosophy (from the Temporal vs LangGraph comparison):
We choose the LangGraph philosophy — explicit control, developer decides what to save —
but build it ourselves for full visibility into what's persisted and why.
"""

from __future__ import annotations

import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from duraagent import events
from duraagent.events import StepStatus, WorkflowStatus
from duraagent.state_store import StateStore


@dataclass
class RetryPolicy:
    """Configurable retry policy with exponential backoff."""

    max_attempts: int = 3
    base_delay_s: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_s: float = 30.0

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay for a given attempt number (1-indexed)."""
        delay = self.base_delay_s * (self.backoff_multiplier ** (attempt - 1))
        return min(delay, self.max_delay_s)


@dataclass
class Step:
    """
    A single step in a durable workflow.

    Each step has:
    - A name (unique within the workflow)
    - A callable that does the actual work
    - A retry policy for transient failures
    - An optional flag marking it as a human approval gate
    """

    name: str
    fn: Callable[[dict[str, Any]], dict[str, Any]]
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    is_approval_gate: bool = False


class WorkflowPaused(Exception):
    """Raised when a workflow enters AWAITING_APPROVAL state."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Workflow paused: {reason}")


class StepFailedPermanently(Exception):
    """Raised when a step exhausts all retries."""

    def __init__(self, step_name: str, error: str, attempts: int):
        self.step_name = step_name
        self.error = error
        self.attempts = attempts
        super().__init__(
            f"Step '{step_name}' failed after {attempts} attempts: {error}"
        )


class DurableWorkflow:
    """
    Event-sourced durable workflow engine.

    Key guarantees:
    1. Every step's input/output is persisted BEFORE the next step runs
    2. On resume, completed steps are skipped (idempotent replay)
    3. Failed steps are retried according to their retry policy
    4. The full event history is available for inspection and debugging
    """

    def __init__(
        self,
        name: str,
        steps: list[Step],
        store: StateStore,
        run_id: str | None = None,
    ):
        self.name = name
        self.steps = steps
        self.store = store
        self.run_id = run_id or str(uuid.uuid4())
        self._step_outputs: dict[str, dict[str, Any]] = {}

    def run(self, initial_input: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Execute the workflow from the beginning or resume from last checkpoint.

        Returns the output of the final step.
        """
        # Check if this run already exists (resume case)
        existing = self.store.get_workflow_state(self.run_id)

        if existing is None:
            # Fresh run — emit WorkflowStarted
            self.store.append_event(
                events.workflow_started(
                    self.run_id,
                    self.name,
                    {"initial_input": initial_input or {}},
                )
            )
        elif existing["status"] == WorkflowStatus.COMPLETED.value:
            # Already completed — return cached final output
            final_step = self.steps[-1]
            step_state = self.store.get_step_state(self.run_id, final_step.name)
            if step_state:
                import json
                return json.loads(step_state["output_data"]) if isinstance(step_state["output_data"], str) else step_state["output_data"]
            return {}
        elif existing["status"] == WorkflowStatus.PAUSED.value:
            # Paused — check for approval and resume
            self.store.append_event(
                events.workflow_resumed(self.run_id, "auto_resume")
            )

        # Execute steps in order
        current_input = initial_input or {}

        for idx, step in enumerate(self.steps):
            # Check if step is already completed (idempotent skip)
            step_state = self.store.get_step_state(self.run_id, step.name)
            if step_state and step_state["status"] == StepStatus.COMPLETED.value:
                # Skip — emit event for observability
                self.store.append_event(
                    events.step_skipped(self.run_id, step.name, idx)
                )
                # Recover the cached output for downstream steps
                import json
                cached_output = step_state["output_data"]
                if isinstance(cached_output, str):
                    cached_output = json.loads(cached_output)
                self._step_outputs[step.name] = cached_output
                current_input = cached_output
                continue

            # Check for approval gate
            if step.is_approval_gate:
                self.store.append_event(
                    events.workflow_paused(
                        self.run_id,
                        reason=f"Awaiting approval at step '{step.name}'",
                        awaiting="human_approval",
                    )
                )
                raise WorkflowPaused(f"Approval required at step '{step.name}'")

            # Execute step with retry policy
            output = self._execute_step_with_retries(step, idx, current_input)
            self._step_outputs[step.name] = output
            current_input = output

        # All steps completed
        self.store.append_event(
            events.workflow_completed(
                self.run_id,
                summary={
                    "total_steps": len(self.steps),
                    "step_names": [s.name for s in self.steps],
                },
            )
        )

        return current_input

    def _execute_step_with_retries(
        self, step: Step, step_index: int, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a step, retrying on failure according to the retry policy."""
        last_error = ""

        for attempt in range(1, step.retry_policy.max_attempts + 1):
            # Emit StepStarted
            self.store.append_event(
                events.step_started(self.run_id, step.name, step_index, input_data)
            )

            start_time = time.monotonic()
            try:
                output = step.fn(input_data)
                duration_ms = (time.monotonic() - start_time) * 1000

                # Success — emit StepCompleted
                self.store.append_event(
                    events.step_completed(
                        self.run_id, step.name, step_index, output, duration_ms
                    )
                )
                return output

            except WorkflowPaused:
                # Let it bubble up to pause the workflow without failing the step
                raise
            except Exception as exc:
                duration_ms = (time.monotonic() - start_time) * 1000
                last_error = f"{type(exc).__name__}: {exc}"
                will_retry = attempt < step.retry_policy.max_attempts

                # Emit StepFailed
                self.store.append_event(
                    events.step_failed(
                        self.run_id,
                        step.name,
                        step_index,
                        last_error,
                        attempt,
                        will_retry,
                    )
                )

                if will_retry:
                    delay = step.retry_policy.delay_for_attempt(attempt)
                    time.sleep(delay)

        # All retries exhausted
        self.store.append_event(
            events.workflow_failed(self.run_id, f"Step '{step.name}' failed permanently: {last_error}")
        )
        raise StepFailedPermanently(step.name, last_error, step.retry_policy.max_attempts)

    def get_step_output(self, step_name: str) -> dict[str, Any] | None:
        """Get the output of a previously completed step."""
        return self._step_outputs.get(step_name)

    def get_run_summary(self) -> dict[str, Any]:
        """Get a summary of the current run state."""
        wf_state = self.store.get_workflow_state(self.run_id)
        step_states = self.store.get_all_step_states(self.run_id)
        event_count = len(self.store.get_events(self.run_id))
        return {
            "run_id": self.run_id,
            "workflow": wf_state,
            "steps": step_states,
            "total_events": event_count,
        }
