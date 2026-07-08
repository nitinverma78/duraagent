"""
Immutable event types for the DuraAgent event-sourced state store.

Every action in the system emits an event. Events are append-only, never mutated.
The event log IS the source of truth — materialized views (workflow_state, step_state)
are derived projections that can be rebuilt at any time by replaying the log.

This is the foundation of durability: if the process crashes, we replay events
to reconstruct exactly where we were.
"""

from __future__ import annotations

import json
import uuid

from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """All possible event types in the system."""

    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"

    # Step lifecycle
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"

    # Self-correction
    CORRECTION_ATTEMPTED = "correction_attempted"

    # Memory / learning
    MEMORY_STORED = "memory_stored"
    SKILL_CREATED = "skill_created"
    SKILL_MUTATED = "skill_mutated"

    # Observability
    LLM_CALL_RECORDED = "llm_call_recorded"
    SANDBOX_EXECUTION_RECORDED = "sandbox_execution_recorded"

    # Durable autonomy
    ESCALATION_REQUESTED = "escalation_requested"
    INTERVENTION_RESOLVED = "intervention_resolved"
    DRIFT_DETECTED = "drift_detected"


class WorkflowStatus(str, Enum):
    """Workflow-level status."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StepStatus(str, Enum):
    """Step-level status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


from pydantic import BaseModel, Field, ConfigDict

class Event(BaseModel):
    """
    A single immutable event in the system.

    Every event has:
    - A unique ID
    - The run it belongs to
    - A type
    - A timestamp (UTC)
    - A payload (arbitrary dict)
    
    Using Pydantic ensures strict type validation on creation.
    """
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    event_type: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string for storage."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> Event:
        """Deserialize from JSON string."""
        return cls.model_validate_json(json_str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        """Construct from a dictionary."""
        return cls.model_validate(data)


# ── Factory functions for each event type ──────────────────────────────────
# These enforce consistent payload structure per event type.


def workflow_started(
    run_id: str, workflow_name: str, config: dict[str, Any] | None = None
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.WORKFLOW_STARTED,
        payload={
            "workflow_name": workflow_name,
            "config": config or {},
        },
    )


def workflow_completed(run_id: str, summary: dict[str, Any] | None = None) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.WORKFLOW_COMPLETED,
        payload={"summary": summary or {}},
    )


def workflow_failed(run_id: str, error: str) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.WORKFLOW_FAILED,
        payload={"error": error},
    )


def workflow_paused(run_id: str, reason: str, awaiting: str = "human_approval") -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.WORKFLOW_PAUSED,
        payload={"reason": reason, "awaiting": awaiting},
    )


def workflow_resumed(run_id: str, decision: str, details: dict[str, Any] | None = None) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.WORKFLOW_RESUMED,
        payload={"decision": decision, "details": details or {}},
    )


def step_started(
    run_id: str, step_name: str, step_index: int, input_data: dict[str, Any] | None = None
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.STEP_STARTED,
        payload={
            "step_name": step_name,
            "step_index": step_index,
            "input_data": input_data or {},
        },
    )


def step_completed(
    run_id: str,
    step_name: str,
    step_index: int,
    output_data: dict[str, Any] | None = None,
    duration_ms: float = 0.0,
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.STEP_COMPLETED,
        payload={
            "step_name": step_name,
            "step_index": step_index,
            "output_data": output_data or {},
            "duration_ms": duration_ms,
        },
    )


def step_failed(
    run_id: str,
    step_name: str,
    step_index: int,
    error: str,
    attempt: int,
    will_retry: bool,
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.STEP_FAILED,
        payload={
            "step_name": step_name,
            "step_index": step_index,
            "error": error,
            "attempt": attempt,
            "will_retry": will_retry,
        },
    )


def step_skipped(run_id: str, step_name: str, step_index: int, reason: str = "already_completed") -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.STEP_SKIPPED,
        payload={
            "step_name": step_name,
            "step_index": step_index,
            "reason": reason,
        },
    )


def correction_attempted(
    run_id: str,
    step_name: str,
    attempt: int,
    approach_summary: str,
    result: str,
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.CORRECTION_ATTEMPTED,
        payload={
            "step_name": step_name,
            "attempt": attempt,
            "approach_summary": approach_summary,
            "result": result,
        },
    )


def memory_stored(
    run_id: str, key: str, fact: str, source: str = ""
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.MEMORY_STORED,
        payload={"key": key, "fact": fact, "source": source},
    )


def llm_call_recorded(
    run_id: str,
    step_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    prompt_hash: str,
    cached: bool = False,
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.LLM_CALL_RECORDED,
        payload={
            "step_name": step_name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "prompt_hash": prompt_hash,
            "cached": cached,
        },
    )


def sandbox_execution_recorded(
    run_id: str,
    step_name: str,
    exit_code: int,
    duration_ms: float,
    timed_out: bool = False,
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.SANDBOX_EXECUTION_RECORDED,
        payload={
            "step_name": step_name,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
        },
    )


def escalation_requested(
    run_id: str,
    issue_description: str,
    uncertainty: float,
    novelty: float,
    reason: str,
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.ESCALATION_REQUESTED,
        payload={
            "issue_description": issue_description,
            "uncertainty": uncertainty,
            "novelty": novelty,
            "reason": reason,
        },
    )


def intervention_resolved(
    run_id: str, human_decision: str, outcome: str
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.INTERVENTION_RESOLVED,
        payload={"human_decision": human_decision, "outcome": outcome},
    )


def drift_detected(
    run_id: str, metric: str, current_value: float, threshold: float
) -> Event:
    return Event(
        run_id=run_id,
        event_type=EventType.DRIFT_DETECTED,
        payload={
            "metric": metric,
            "current_value": current_value,
            "threshold": threshold,
        },
    )
