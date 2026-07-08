"""
Guardrails for DuraAgent.

Layer: Harness Engineering
Role:  Interception layer that runs before any LLM output is executed.
       Prevents dangerous actions (rm -rf, DROP TABLE) and enforces budgets
       (tokens, memory, time) to prevent runaway costs or death-loops.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GuardrailResult(BaseModel):
    """Result of a guardrail evaluation."""
    model_config = ConfigDict(frozen=True)

    passed: bool
    reason: str = ""
    remediation: str = ""


class AbstractGuardrail(ABC):
    """Base class for all guardrails."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def check(self, payload: dict[str, Any]) -> GuardrailResult:
        """Evaluate the payload and return whether it passes."""
        pass


class PatchSafetyGuardrail(AbstractGuardrail):
    """Detects overtly malicious or destructive patterns in code patches."""

    @property
    def name(self) -> str:
        return "PatchSafety"

    def check(self, payload: dict[str, Any]) -> GuardrailResult:
        code = payload.get("new_code", "")
        
        dangerous_patterns = [
            (r"os\.system\s*\(", "System call execution"),
            (r"subprocess\.", "Subprocess execution"),
            (r"DROP\s+TABLE", "Database destruction"),
            (r"rm\s+-rf", "File deletion"),
        ]
        
        for pattern, description in dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return GuardrailResult(
                    passed=False,
                    reason=f"Dangerous pattern detected: {description}",
                    remediation="Rewrite the patch to use safe, restricted APIs.",
                )
                
        return GuardrailResult(passed=True)


class RepetitionGuardrail(AbstractGuardrail):
    """Detects death loops by hashing recent LLM outputs."""

    def __init__(self, max_repetitions: int = 3):
        self.max_repetitions = max_repetitions
        self._history: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "Repetition"

    def check(self, payload: dict[str, Any]) -> GuardrailResult:
        # Simple content hash for exact repetition detection
        content = str(payload)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        self._history[content_hash] = self._history.get(content_hash, 0) + 1
        
        if self._history[content_hash] > self.max_repetitions:
            return GuardrailResult(
                passed=False,
                reason=f"LLM generated the exact same payload {self._history[content_hash]} times.",
                remediation="Force a high temperature retry or escalate to human.",
            )
            
        return GuardrailResult(passed=True)


class GuardrailPipeline:
    """Chains multiple guardrails together."""

    def __init__(self, guardrails: list[AbstractGuardrail] | None = None):
        self.guardrails = guardrails or []

    def check_all(self, payload: dict[str, Any]) -> GuardrailResult:
        """Run payload through all guardrails. Fails fast on first rejection."""
        for guardrail in self.guardrails:
            result = guardrail.check(payload)
            if not result.passed:
                # Augment reason with the guardrail name
                return GuardrailResult(
                    passed=False,
                    reason=f"[{guardrail.name}] {result.reason}",
                    remediation=result.remediation,
                )
        return GuardrailResult(passed=True)
