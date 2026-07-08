"""
Typed tool contracts for DuraAgent.

Every tool interaction (sandbox execution, LLM call, patch application)
has a defined contract with:
- Input/output schemas
- Error codes
- Timeout limits
- Idempotency guarantees

This prevents "hallucinated" tool usage and ensures the agent operates
within safe, predictable boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolContract:
    """Defines the contract for a tool interaction."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    error_codes: dict[int, str] = field(default_factory=dict)
    timeout_ms: int = 30_000
    idempotent: bool = False


SANDBOX_EXECUTE = ToolContract(
    name="sandbox_execute",
    description="Execute Python code in an isolated subprocess",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "timeout_s": {"type": "number", "default": 30},
        },
        "required": ["code"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "duration_ms": {"type": "number"},
            "timed_out": {"type": "boolean"},
        },
    },
    error_codes={1: "General error", 2: "Syntax error", 124: "Timeout", 137: "Killed"},
    timeout_ms=30_000,
    idempotent=True,
)

RUN_TESTS = ToolContract(
    name="run_tests",
    description="Run pytest test suite in a project directory",
    input_schema={
        "type": "object",
        "properties": {
            "project_dir": {"type": "string"},
            "test_command": {"type": "string", "default": "python3 -m pytest -v"},
        },
        "required": ["project_dir"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "passed": {"type": "integer"},
            "failed": {"type": "integer"},
            "errors": {"type": "integer"},
            "output": {"type": "string"},
            "exit_code": {"type": "integer"},
        },
    },
    error_codes={0: "All passed", 1: "Some failed", 2: "Interrupted", 5: "No tests"},
    timeout_ms=60_000,
    idempotent=True,
)

LLM_CALL = ToolContract(
    name="llm_call",
    description="Call Claude API for code analysis or generation",
    input_schema={
        "type": "object",
        "properties": {
            "system_prompt": {"type": "string"},
            "user_prompt": {"type": "string"},
            "model": {"type": "string", "default": "claude-sonnet-4-20250514"},
            "max_tokens": {"type": "integer", "default": 4096},
        },
        "required": ["user_prompt"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "input_tokens": {"type": "integer"},
            "output_tokens": {"type": "integer"},
            "latency_ms": {"type": "number"},
            "prompt_hash": {"type": "string"},
        },
    },
    error_codes={429: "Rate limited", 500: "Server error", 401: "Bad key"},
    timeout_ms=120_000,
    idempotent=False,
)

PATCH_APPLY = ToolContract(
    name="patch_apply",
    description="Apply a code patch to source files",
    input_schema={
        "type": "object",
        "properties": {
            "diff_text": {"type": "string"},
            "target_dir": {"type": "string"},
        },
        "required": ["diff_text", "target_dir"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "files_modified": {"type": "array"},
            "error": {"type": "string"},
        },
    },
    error_codes={1: "Patch conflict", 2: "File not found"},
    timeout_ms=5_000,
    idempotent=False,
)
