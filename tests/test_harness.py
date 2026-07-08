"""Tests for the execution harness."""

import os
import tempfile
from pathlib import Path

import pytest

from duraagent.harness import PatchApplier, SandboxRunner


class TestSandboxRunner:
    """Test sandboxed code execution and validation."""

    def test_syntax_validation_catches_errors(self):
        runner = SandboxRunner()
        err = runner.validate_syntax("def broken(")
        assert err is not None
        assert "SyntaxError" in err

    def test_syntax_validation_passes_valid_code(self):
        runner = SandboxRunner()
        err = runner.validate_syntax("def works(): return True")
        assert err is None

    def test_execute_valid_code(self):
        runner = SandboxRunner()
        res = runner.execute("print('hello')")
        assert res.exit_code == 0
        assert res.stdout.strip() == "hello"

    def test_execute_catches_runtime_error(self):
        runner = SandboxRunner()
        res = runner.execute("1 / 0")
        assert res.exit_code != 0
        assert "ZeroDivisionError" in res.stderr

    def test_execute_enforces_timeout(self):
        runner = SandboxRunner(timeout_s=1)
        res = runner.execute("import time; time.sleep(2)")
        assert res.exit_code == 124
        assert res.timed_out is True


class TestPatchApplier:
    """Test patch application and rollback."""

    def test_apply_and_revert_simple_patch(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def add(a, b):\n    return a + b\n")

        # Apply
        res = PatchApplier.apply_simple_patch(
            f,
            old_content="return a + b",
            new_content="return a + b + 1",
        )
        assert res.success is True
        assert "return a + b + 1" in f.read_text()

        # Revert
        res2 = PatchApplier.revert_simple_patch(
            f,
            old_content="return a + b",
            new_content="return a + b + 1",
        )
        assert res2.success is True
        assert "return a + b\n" in f.read_text()
        assert "return a + b + 1" not in f.read_text()

    def test_apply_fails_if_old_content_not_found(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo(): pass")

        res = PatchApplier.apply_simple_patch(f, "old_stuff", "new_stuff")
        assert res.success is False
        assert "not found" in res.error

    def test_backup_and_restore(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "a.py").write_text("a")

        backup_dir = PatchApplier.create_backup(project_dir)

        # Modify project
        (project_dir / "a.py").write_text("b")
        (project_dir / "c.py").write_text("c")

        # Restore
        PatchApplier.restore_backup(backup_dir, project_dir)

        assert (project_dir / "a.py").read_text() == "a"
        assert not (project_dir / "c.py").exists()
