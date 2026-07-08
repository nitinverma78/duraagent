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


class CodeAnalyzer:
    """Component responsible for finding bugs via LLM analysis."""
    def __init__(self, llm: AbstractLLMClient):
        self.llm = llm

    def analyze(self, project_dir: str) -> dict[str, Any]:
        system = "You are an expert Python developer. Analyze the code for bugs."
        user = f"Find bugs in the project at {project_dir}"
        resp = self.llm.call(system, user)
        try:
            return json.loads(resp.content)
        except json.JSONDecodeError:
            return {"raw": resp.content}


class PatchGenerator:
    """Component responsible for proposing fixes via LLM."""
    def __init__(self, llm: AbstractLLMClient):
        self.llm = llm

    def generate_patch(self, analysis: dict[str, Any]) -> dict[str, Any]:
        system = "You are an expert Python developer. Generate a patch to fix the bugs."
        user = f"Fix these bugs: {json.dumps(analysis)}"
        resp = self.llm.call(system, user)
        try:
            return json.loads(resp.content)
        except json.JSONDecodeError:
            return {"raw": resp.content}


class PatchVerifier:
    """Component responsible for verifying patches against tests and self-correcting."""
    def __init__(self, llm: AbstractLLMClient, runner: SandboxRunner, store: SQLiteStateStore):
        self.llm = llm
        self.runner = runner
        self.store = store

    def verify_and_correct(self, project_dir: str, patch: dict[str, Any], run_id: str, max_corrections: int = 3) -> dict[str, Any]:
        if "old_code" in patch and "new_code" in patch and "file" in patch:
            target = f"{project_dir}/{patch['file']}"
            PatchApplier.apply_simple_patch(target, patch["old_code"], patch["new_code"])

        for attempt in range(1, max_corrections + 1):
            test_res = self.runner.run_tests(project_dir)
            
            step_name = "Initial patch" if attempt == 1 else f"Correction {attempt-1}"

            if test_res.exit_code == 0:
                self.store.append_event(
                    events.correction_attempted(
                        run_id, "verify_and_correct", attempt, step_name, "SUCCESS: All tests passed"
                    )
                )
                return {"status": "success", "attempts": attempt, "test_output": test_res.output}

            self.store.append_event(
                events.correction_attempted(
                    run_id, "verify_and_correct", attempt, step_name,
                    f"FAILED: Exit code {test_res.exit_code}. {test_res.failed} tests failed."
                )
            )

            if attempt == max_corrections:
                break

            system = "You are an expert Python developer. Your previous fix failed the tests. Provide a new fix."
            user = f"The tests failed with output:\n{test_res.output[-1000:]}\n\nProvide a corrected patch."
            resp = self.llm.call(system, user)

            try:
                new_patch = json.loads(resp.content)
                if "old_code" in new_patch and "new_code" in new_patch and "file" in new_patch:
                    target = f"{project_dir}/{new_patch['file']}"
                    PatchApplier.apply_simple_patch(target, new_patch["old_code"], new_patch["new_code"])
            except json.JSONDecodeError:
                pass

        return {"status": "failed", "attempts": max_corrections, "test_output": "Tests still failing after max corrections"}


class Agent:
    """
    Self-correcting code review and repair agent.
    Composed of CodeAnalyzer, PatchGenerator, and PatchVerifier components.
    """

    def __init__(
        self,
        store: SQLiteStateStore,
        llm: AbstractLLMClient | None = None,
        runner: SandboxRunner | None = None,
    ):
        self.store = store
        self.llm = llm or get_llm_client()
        self.runner = runner or SandboxRunner()
        
        self.analyzer = CodeAnalyzer(self.llm)
        self.generator = PatchGenerator(self.llm)
        self.verifier = PatchVerifier(self.llm, self.runner, self.store)

    def review_and_fix(self, project_dir: str, run_id: str | None = None) -> dict[str, Any]:
        """Run the full review and repair loop on a project directory."""
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
        project_dir = input_data["project_dir"]
        analysis = self.analyzer.analyze(project_dir)
        return {"project_dir": project_dir, "run_id": input_data.get("run_id"), "analysis": analysis}

    def _step_generate_patch(self, input_data: dict[str, Any]) -> dict[str, Any]:
        project_dir = input_data["project_dir"]
        analysis = input_data.get("analysis", {})
        run_id = input_data.get("run_id")

        patch_data = self.generator.generate_patch(analysis)
            
        from duraagent.autonomy import HeuristicScorer
        from duraagent.types import AutonomyLevel
        from duraagent.workflow import WorkflowPaused
        
        scorer = HeuristicScorer()
        # Assume max_level is L3 for this agent step
        autonomy_result = scorer.evaluate(patch_data, AutonomyLevel.L3_AUTONOMOUS)
        
        if autonomy_result.should_escalate:
            self.store.append_event(
                events.Event(
                    run_id=run_id,
                    event_type="workflow_paused",
                    payload={"reason": "Autonomy threshold exceeded", "details": autonomy_result.reasons}
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
        project_dir = input_data["project_dir"]
        patch = input_data.get("patch", {})
        run_id = input_data.get("run_id", "unknown")
        
        return self.verifier.verify_and_correct(project_dir, patch, run_id)
