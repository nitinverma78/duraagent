"""
Agent Loop with Self-Correction for DuraAgent.

This layer orchestrates the core agentic loop:
1. Analyze code to find bugs
2. Generate patches
3. Verify patches in the sandbox (tests)
4. Self-correct if verification fails (using the error output)

The loop is implemented as a durable workflow, so if it crashes mid-correction,
it resumes exactly where it left off.
"""

from __future__ import annotations

import json
from typing import Any

from duraagent import events
from duraagent.contracts import LLM_CALL, PATCH_APPLY, RUN_TESTS
from duraagent.harness import PatchApplier, SandboxRunner
from duraagent.llm import AbstractLLMClient
from duraagent.state_store import SQLiteStateStore
from duraagent.workflow import DurableWorkflow, RetryPolicy, Step


class Agent:
    """
    Self-correcting code review and repair agent.
    """

    def __init__(
        self,
        store: SQLiteStateStore,
        llm: AbstractLLMClient | None = None,
        runner: SandboxRunner | None = None,
    ):
        self.store = store
        self.llm = llm or AbstractLLMClient()
        self.runner = runner or SandboxRunner()

    def review_and_fix(self, project_dir: str, run_id: str | None = None) -> dict[str, Any]:
        """
        Run the full review and repair loop on a project directory.
        """
        steps = [
            Step("analyze_code", self._step_analyze_code),
            Step("generate_patch", self._step_generate_patch),
            Step("verify_and_correct", self._step_verify_and_correct),
        ]

        workflow = DurableWorkflow("agent_loop", steps, self.store, run_id)
        return workflow.run({
            "project_dir": project_dir,
            "run_id": workflow.run_id,
        })

    def _step_analyze_code(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Ask LLM to analyze the code for bugs."""
        project_dir = input_data["project_dir"]

        # In a real system, you'd read all project files here.
        # For the demo, we assume the LLM has context or we pass specific files.
        system = "You are an expert Python developer. Analyze the code for bugs."
        user = f"Find bugs in the project at {project_dir}"

        resp = self.llm.call(system, user)

        try:
            # Parse the JSON response
            analysis = json.loads(resp.content)
            return {"project_dir": project_dir, "run_id": input_data.get("run_id"), "analysis": analysis}
        except json.JSONDecodeError:
            # Fallback if mock didn't return perfect JSON
            return {"project_dir": project_dir, "run_id": input_data.get("run_id"), "analysis": {"raw": resp.content}}

    def _step_generate_patch(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Ask LLM to generate a fix for the found bugs."""
        project_dir = input_data["project_dir"]
        analysis = input_data.get("analysis", {})
        run_id = input_data.get("run_id")

        system = "You are an expert Python developer. Generate a patch to fix the bugs."
        user = f"Fix these bugs: {json.dumps(analysis)}"

        resp = self.llm.call(system, user)

        patch_data = {}
        try:
            patch_data = json.loads(resp.content)
        except json.JSONDecodeError:
            patch_data = {"raw": resp.content}
            
        # Layer 6: Autonomy Check
        from duraagent.autonomy import AutonomyScorer
        from duraagent.workflow import WorkflowPaused
        from duraagent import events
        
        scorer = AutonomyScorer()
        autonomy_result = scorer.evaluate_patch(patch_data)
        
        if autonomy_result["should_escalate"]:
            self.store.append_event(
                events.Event(
                    run_id=run_id,
                    event_type="workflow_paused",
                    payload={"reason": "Autonomy threshold exceeded", "details": autonomy_result["reasons"]}
                )
            )
            raise WorkflowPaused("Autonomy check failed. Escalating to human.")

        return {
            "project_dir": project_dir,
            "run_id": run_id,
            "analysis": analysis,
            "patch": patch_data,
        }

    def _step_verify_and_correct(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Verify the patch against tests. If it fails, enter a self-correction loop.
        """
        project_dir = input_data["project_dir"]
        patch = input_data.get("patch", {})
        max_corrections = 3

        # Apply the initial patch
        if "old_code" in patch and "new_code" in patch and "file" in patch:
            target = f"{project_dir}/{patch['file']}"
            PatchApplier.apply_simple_patch(target, patch["old_code"], patch["new_code"])

        for attempt in range(1, max_corrections + 1):
            # Verify via tests
            test_res = self.runner.run_tests(project_dir)

            if test_res.exit_code == 0:
                # Tests passed!
                self.store.append_event(
                    events.correction_attempted(
                        input_data.get("run_id", "unknown"),
                        "verify_and_correct",
                        attempt,
                        "Initial patch" if attempt == 1 else f"Correction {attempt-1}",
                        "SUCCESS: All tests passed",
                    )
                )
                return {
                    "status": "success",
                    "attempts": attempt,
                    "test_output": test_res.output,
                }

            # Tests failed — self-correction time
            self.store.append_event(
                events.correction_attempted(
                    input_data.get("run_id", "unknown"),
                    "verify_and_correct",
                    attempt,
                    "Initial patch" if attempt == 1 else f"Correction {attempt-1}",
                    f"FAILED: Exit code {test_res.exit_code}. {test_res.failed} tests failed.",
                )
            )

            if attempt == max_corrections:
                break

            # Ask LLM to correct the patch based on test output
            system = "You are an expert Python developer. Your previous fix failed the tests. Provide a new fix."
            user = f"The tests failed with output:\n{test_res.output[-1000:]}\n\nProvide a corrected patch."

            resp = self.llm.call(system, user)

            try:
                new_patch = json.loads(resp.content)
                if "old_code" in new_patch and "new_code" in new_patch and "file" in new_patch:
                    # In a real system, you'd revert the old patch first or apply the new one
                    target = f"{project_dir}/{new_patch['file']}"
                    PatchApplier.apply_simple_patch(target, new_patch["old_code"], new_patch["new_code"])
            except json.JSONDecodeError:
                pass  # Ignore malformed correction responses in demo

        return {
            "status": "failed",
            "attempts": max_corrections,
            "test_output": "Tests still failing after max corrections",
        }
