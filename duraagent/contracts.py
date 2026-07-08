"""
Typed tool contracts for DuraAgent.

Layer: Harness Engineering
Role:  Every tool interaction (sandbox execution, LLM call, patch application)
       has a defined contract with input/output schemas, error codes, and
       idempotency guarantees. This prevents hallucinated tool usage and
       ensures the agent operates within safe, predictable boundaries.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolContract(BaseModel):
    """
    Defines the strict contract for a tool interaction.
    Using Pydantic allows runtime validation of inputs and outputs
    against JSON Schema before executing tools or returning to LLM.
    """
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="LLM-facing tool description")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    error_codes: dict[int, str] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30_000, ge=1)
    idempotent: bool = Field(default=False)

    def validate_input(self, data: dict[str, Any]) -> bool:
        """Validate input payload against the contract schema."""
        required = self.input_schema.get("required", [])
        for req in required:
            if req not in data:
                return False
        return True

    def validate_output(self, data: dict[str, Any]) -> bool:
        """Validate output payload against the contract schema."""
        properties = self.output_schema.get("properties", {})
        for key in data:
            if key not in properties:
                return False
        return True


class ToolRegistry:
    """Registry of all available tool contracts."""
    
    def __init__(self):
        self._tools: dict[str, ToolContract] = {}

    def register(self, contract: ToolContract) -> None:
        self._tools[contract.name] = contract

    def get(self, name: str) -> ToolContract | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolContract]:
        return list(self._tools.values())


# Standard Tools
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

# Initialize default registry
default_registry = ToolRegistry()
default_registry.register(SANDBOX_EXECUTE)
default_registry.register(RUN_TESTS)
default_registry.register(LLM_CALL)
default_registry.register(PATCH_APPLY)
