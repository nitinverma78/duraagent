"""
Execution harness for DuraAgent.

The harness is the "operational substrate" — everything that ISN'T the model.
"If you are not the model, you are the harness."

Provides:
- Sandboxed code execution with timeout enforcement
- Syntax pre-validation (cheap, fast feedback before subprocess)
- Test suite execution with structured result parsing
- Patch application and rollback
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExecutionResult:
    """Structured result from sandbox code execution."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    timed_out: bool = False
    syntax_error: str | None = None


@dataclass(frozen=True)
class TestResult:
    """Structured result from running a test suite."""
    passed: int = 0
    failed: int = 0
    errors: int = 0
    output: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0


@dataclass(frozen=True)
class PatchResult:
    """Result of applying a code patch."""
    success: bool = False
    files_modified: list[str] = field(default_factory=list)
    error: str = ""


class SandboxRunner:
    """
    Sandboxed code execution environment.

    Runs code in isolated subprocesses with timeout enforcement,
    stdout/stderr capture, and pre-execution syntax validation.
    """

    def __init__(self, timeout_s: int = 30, python_cmd: str = "python3"):
        self.timeout_s = timeout_s
        self.python_cmd = python_cmd

    def validate_syntax(self, code: str) -> str | None:
        """
        Pre-validate Python syntax using ast.parse().
        Returns None if valid, or the error message if invalid.
        """
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"

    def execute(self, code: str, timeout_s: int | None = None) -> ExecutionResult:
        """Execute Python code in an isolated subprocess."""
        timeout = timeout_s or self.timeout_s

        # Pre-check syntax (cheap, avoids subprocess overhead)
        syntax_err = self.validate_syntax(code)
        if syntax_err:
            return ExecutionResult(stderr=syntax_err, exit_code=2, syntax_error=syntax_err)

        start = time.monotonic()
        try:
            result = subprocess.run(
                [self.python_cmd, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            duration_ms = (time.monotonic() - start) * 1000
            return ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic() - start) * 1000
            return ExecutionResult(
                stderr=f"Execution timed out after {timeout}s",
                exit_code=124,
                duration_ms=duration_ms,
                timed_out=True,
            )

    def run_tests(
        self,
        project_dir: str | Path,
        test_command: str | None = None,
        timeout_s: int | None = None,
    ) -> TestResult:
        """
        Run the test suite for a project.
        This is the VERIFICATION GATE — the external oracle that determines
        whether a patch is correct. The model never checks its own work.
        """
        project_dir = Path(project_dir)
        timeout = timeout_s or self.timeout_s * 2
        cmd = test_command or f"{self.python_cmd} -m pytest -v --tb=short"

        start = time.monotonic()
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(project_dir),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            duration_ms = (time.monotonic() - start) * 1000
            passed, failed, errors = self._parse_pytest_output(result.stdout + result.stderr)
            return TestResult(
                passed=passed, failed=failed, errors=errors,
                output=result.stdout + result.stderr,
                exit_code=result.returncode, duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic() - start) * 1000
            return TestResult(
                output=f"Test execution timed out after {timeout}s",
                exit_code=124, duration_ms=duration_ms,
            )

    def _parse_pytest_output(self, output: str) -> tuple[int, int, int]:
        """Parse pytest summary line for pass/fail/error counts."""
        passed = failed = errors = 0
        m_p = re.search(r"(\d+)\s+passed", output)
        m_f = re.search(r"(\d+)\s+failed", output)
        m_e = re.search(r"(\d+)\s+error", output)
        if m_p: passed = int(m_p.group(1))
        if m_f: failed = int(m_f.group(1))
        if m_e: errors = int(m_e.group(1))
        return passed, failed, errors


class PatchApplier:
    """Applies and reverts code patches."""

    @staticmethod
    def apply_simple_patch(
        file_path: str | Path, old_content: str, new_content: str,
    ) -> PatchResult:
        """Apply a simple find-and-replace patch to a file."""
        file_path = Path(file_path)
        if not file_path.exists():
            return PatchResult(success=False, error=f"File not found: {file_path}")

        content = file_path.read_text()
        if old_content not in content:
            return PatchResult(success=False, error=f"Patch target not found in {file_path.name}")

        file_path.write_text(content.replace(old_content, new_content, 1))
        return PatchResult(success=True, files_modified=[str(file_path)])

    @staticmethod
    def revert_simple_patch(
        file_path: str | Path, old_content: str, new_content: str,
    ) -> PatchResult:
        """Revert a previously applied patch."""
        return PatchApplier.apply_simple_patch(file_path, new_content, old_content)

    @staticmethod
    def create_backup(project_dir: str | Path) -> str:
        """Create a temporary backup of a project directory."""
        backup_dir = tempfile.mkdtemp(prefix="duraagent_backup_")
        shutil.copytree(str(project_dir), os.path.join(backup_dir, "project"), dirs_exist_ok=True)
        return backup_dir

    @staticmethod
    def restore_backup(backup_dir: str, project_dir: str | Path) -> None:
        """Restore a project from backup."""
        backup_project = os.path.join(backup_dir, "project")
        if os.path.exists(backup_project):
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
            shutil.copytree(backup_project, project_dir)
