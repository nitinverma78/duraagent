"""
Type foundation for DuraAgent.

Layer: Software Engineering
Role:  Establishes the type vocabulary shared by every module in the system.

Design philosophy (synthesized from multiple influences):
- Matt Pocock:  Branded NewType IDs prevent accidental interchange of structurally
  identical but semantically different strings (RunId vs EventId).
- Ashwin Rao:   Frozen dataclasses / Pydantic models enforce immutability; Generic
  type parameters carry mathematical meaning.
- Ed Donner:    Pydantic BaseModel with Field(description=...) as the communication
  protocol between agents and components.
- Jeremy Howard: store_attr-style minimal boilerplate; expressive, terse definitions.

Every ID in the system flows through a branded NewType so that mypy (and humans
reading a diff) can distinguish RunId("abc") from EventId("abc") at a glance.
"""

from __future__ import annotations

import enum
from typing import Any, Literal, NewType, Union

from pydantic import BaseModel, ConfigDict, Field


# ── Branded ID Types ────────────────────────────────────────────────────
# These are NewType wrappers around str.  They cost nothing at runtime
# (NewType is erased), but give mypy and IDE tooling a way to catch
# mix-ups like passing a RunId where an EventId is expected.

RunId       = NewType("RunId", str)
EventId     = NewType("EventId", str)
StepName    = NewType("StepName", str)
SkillId     = NewType("SkillId", str)
PromptHash  = NewType("PromptHash", str)
SpanId      = NewType("SpanId", str)


# ── Autonomy Levels (L0 – L4) ──────────────────────────────────────────
# From the Foundation Agentic Engineering framework.
# Each level defines the boundary between agent autonomy and human oversight.

class AutonomyLevel(enum.IntEnum):
    """
    Graduated autonomy scale for agent governance.

    L0 — Monitor:   Pure automation / logging only.  Human-controlled.
    L1 — Advisory:  Agent reasons and suggests.  Human reviews and acts.
    L2 — Co-pilot:  Agent proposes actions within workflow.  Human approves.
    L3 — Autonomous: Agent acts independently.  Human intervenes on exceptions.
    L4 — Full:      Fully autonomous with self-recovery.  Strategic oversight.
    """
    L0_MONITOR   = 0
    L1_ADVISORY  = 1
    L2_COPILOT   = 2
    L3_AUTONOMOUS = 3
    L4_FULL      = 4


# ── Discriminated Union: Step Outcomes ──────────────────────────────────
# Matt Pocock pattern: tagged unions with Literal discriminators so that
# match/case is exhaustive and mypy catches unhandled variants.

class StepSuccess(BaseModel):
    """A step completed successfully."""
    model_config = ConfigDict(frozen=True)

    status: Literal["success"] = "success"
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


class StepFailure(BaseModel):
    """A step failed after exhausting retries."""
    model_config = ConfigDict(frozen=True)

    status: Literal["failure"] = "failure"
    error: str = ""
    attempts: int = 0


class StepEscalation(BaseModel):
    """A step requires human intervention."""
    model_config = ConfigDict(frozen=True)

    status: Literal["escalation"] = "escalation"
    reason: str = ""
    uncertainty: float = 0.0
    novelty: float = 0.0


# The discriminated union — use in type hints for step return values.
StepOutcome = Union[StepSuccess, StepFailure, StepEscalation]


# ── Agent Configuration ────────────────────────────────────────────────
# Replaces scattered constructor kwargs with a validated, frozen config.
# Builder pattern provides a fluent construction interface.

class AgentConfig(BaseModel):
    """
    Immutable, validated configuration for an Agent instance.

    Use ``AgentConfigBuilder`` for fluent construction, or instantiate
    directly for programmatic use.
    """
    model_config = ConfigDict(frozen=True)

    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="LLM model identifier for API calls.",
    )
    max_corrections: int = Field(
        default=3, ge=1, le=10,
        description="Maximum self-correction attempts before failing.",
    )
    autonomy_level: AutonomyLevel = Field(
        default=AutonomyLevel.L2_COPILOT,
        description="Maximum autonomy level the agent is permitted.",
    )
    timeout_s: int = Field(
        default=30, ge=1,
        description="Default timeout for sandbox execution (seconds).",
    )
    max_tokens_per_call: int = Field(
        default=4096, ge=1,
        description="Maximum tokens per LLM call.",
    )
    token_budget: int = Field(
        default=100_000, ge=0,
        description="Total token budget for an entire workflow run.",
    )
    enable_tracing: bool = Field(
        default=True,
        description="Whether to emit tracing spans for observability.",
    )
    enable_guardrails: bool = Field(
        default=True,
        description="Whether to run guardrail checks before execution.",
    )


class AgentConfigBuilder:
    """
    Fluent builder for ``AgentConfig``.

    Usage::

        config = (AgentConfigBuilder()
            .with_model("claude-haiku-35-20241022")
            .with_autonomy(AutonomyLevel.L3_AUTONOMOUS)
            .with_timeout(60)
            .build())
    """

    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}

    def with_model(self, model: str) -> AgentConfigBuilder:
        self._overrides["model"] = model
        return self

    def with_max_corrections(self, n: int) -> AgentConfigBuilder:
        self._overrides["max_corrections"] = n
        return self

    def with_autonomy(self, level: AutonomyLevel) -> AgentConfigBuilder:
        self._overrides["autonomy_level"] = level
        return self

    def with_timeout(self, seconds: int) -> AgentConfigBuilder:
        self._overrides["timeout_s"] = seconds
        return self

    def with_token_budget(self, budget: int) -> AgentConfigBuilder:
        self._overrides["token_budget"] = budget
        return self

    def with_tracing(self, enabled: bool = True) -> AgentConfigBuilder:
        self._overrides["enable_tracing"] = enabled
        return self

    def with_guardrails(self, enabled: bool = True) -> AgentConfigBuilder:
        self._overrides["enable_guardrails"] = enabled
        return self

    def build(self) -> AgentConfig:
        """Validate and freeze the configuration."""
        return AgentConfig(**self._overrides)
