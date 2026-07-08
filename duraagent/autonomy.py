"""
Autonomy Scoring & Policy Engine for DuraAgent.

Layer: Harness Engineering
Role:  Determines whether an agent should proceed autonomously or escalate
       to a human based on uncertainty and novelty scores.

Implements the L0-L4 autonomy governance framework from Foundation Agentic Engineering.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from duraagent.types import AutonomyLevel


class AutonomyScore(BaseModel):
    """Structured output from an autonomy evaluation."""
    model_config = ConfigDict(frozen=True)

    uncertainty: float = Field(..., ge=0.0, le=1.0)
    novelty: float = Field(..., ge=0.0, le=1.0)
    should_escalate: bool
    reasons: list[str] = Field(default_factory=list)


class AbstractAutonomyScorer(ABC):
    """Base class for evaluating patch/plan autonomy risks."""
    
    @abstractmethod
    def evaluate(self, payload: dict[str, Any], max_level: AutonomyLevel) -> AutonomyScore:
        """Evaluate action payload and return an autonomy score."""
        pass


class HeuristicScorer(AbstractAutonomyScorer):
    """Fast, rule-based autonomy evaluation."""

    def __init__(self, uncertainty_threshold: float = 0.7, novelty_threshold: float = 0.8):
        self.uncertainty_threshold = uncertainty_threshold
        self.novelty_threshold = novelty_threshold

    def evaluate(self, payload: dict[str, Any], max_level: AutonomyLevel) -> AutonomyScore:
        uncertainty = 0.1
        novelty = 0.1
        reasons = []

        # Heuristic 1: Large diffs increase uncertainty
        old_code = payload.get("old_code", "")
        new_code = payload.get("new_code", "")
        
        if abs(len(new_code) - len(old_code)) > 500:
            uncertainty += 0.5
            reasons.append("Large code modification detected.")
            
        if payload.get("requires_db_migration", False):
            uncertainty += 0.8
            reasons.append("Database migration detected.")
            
        # Heuristic 2: Touching core configuration increases novelty
        file_path = payload.get("file", "")
        if "config" in file_path or "settings" in file_path or file_path.endswith(".toml"):
            novelty += 0.7
            reasons.append("Core configuration modification detected.")

        uncertainty = round(min(1.0, uncertainty), 3)
        novelty = round(min(1.0, novelty), 3)
        
        should_escalate = False
        if max_level < AutonomyLevel.L3_AUTONOMOUS:
            if uncertainty >= self.uncertainty_threshold or novelty >= self.novelty_threshold:
                should_escalate = True
                
        if max_level == AutonomyLevel.L1_ADVISORY:
            should_escalate = True # Always escalate in advisory mode
            reasons.append("Advisory mode requires explicit approval.")

        return AutonomyScore(
            uncertainty=uncertainty,
            novelty=novelty,
            should_escalate=should_escalate,
            reasons=reasons
        )


class AutonomyPolicy:
    """Governance rules for autonomy levels."""
    
    @staticmethod
    def can_execute(level: AutonomyLevel, action_type: str) -> bool:
        """Returns True if the current autonomy level permits the action."""
        if level >= AutonomyLevel.L4_FULL:
            return True
            
        if level == AutonomyLevel.L0_MONITOR:
            return False # Can't do anything actively
            
        if action_type == "delete_file":
            return level >= AutonomyLevel.L3_AUTONOMOUS
            
        if action_type == "modify_config":
            return level >= AutonomyLevel.L3_AUTONOMOUS
            
        if action_type in ("apply_patch", "run_tests"):
            return level >= AutonomyLevel.L2_COPILOT
            
        # L1 can basically only analyze and propose
        return action_type in ("analyze", "propose_patch")
