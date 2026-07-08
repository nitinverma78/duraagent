"""
DuraAgent: Production-grade self-evolving agentic code review engine.

Exposes a clean public API organized by engineering layers.
"""

from __future__ import annotations

# Software Engineering Layer
from duraagent.types import (
    RunId,
    EventId,
    StepName,
    SkillId,
    PromptHash,
    SpanId,
    AutonomyLevel,
    StepOutcome,
    StepSuccess,
    StepFailure,
    StepEscalation,
    AgentConfig,
    AgentConfigBuilder,
)
from duraagent.events import Event, EventType, StepStatus, WorkflowStatus
from duraagent.state_store import AbstractStateStore, SQLiteStateStore
from duraagent.workflow import DurableWorkflow, Step
from duraagent.agent import Agent

# Harness Engineering Layer
from duraagent.harness import SandboxRunner, PatchApplier, ExecutionResult, PatchResult, TestResult
from duraagent.contracts import ToolContract

__all__ = [
    # Types
    "RunId",
    "EventId",
    "StepName",
    "SkillId",
    "PromptHash",
    "SpanId",
    "AutonomyLevel",
    "StepOutcome",
    "StepSuccess",
    "StepFailure",
    "StepEscalation",
    "AgentConfig",
    "AgentConfigBuilder",
    
    # Events & State
    "Event",
    "EventType",
    "StepStatus",
    "WorkflowStatus",
    "AbstractStateStore",
    "SQLiteStateStore",
    
    # Core Orchestration
    "DurableWorkflow",
    "Step",
    "Agent",
    
    # Harness
    "SandboxRunner",
    "PatchApplier",
    "ExecutionResult",
    "PatchResult",
    "TestResult",
    "ToolContract",
]
