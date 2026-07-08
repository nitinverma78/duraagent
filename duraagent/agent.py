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
import re
from typing import Any

from duraagent import events
from duraagent.contracts import LLM_CALL, PATCH_APPLY, RUN_TESTS
from duraagent.harness import PatchApplier, SandboxRunner
from duraagent.llm import AbstractLLMClient, get_llm_client
from duraagent.state_store import SQLiteStateStore
from duraagent.workflow import DurableWorkflow, RetryPolicy, Step
from duraagent.tracing import Tracer, traced, set_tracer
from duraagent.guardrails import GuardrailPipeline, PatchSafetyGuardrail, RepetitionGuardrail
from duraagent.memory import WorkingMemory, EpisodicMemory


def extract_json(text: str) -> str:
    """Extract JSON from markdown code blocks if present."""
    match = re.search(r'```(?:json)?\s*(\{.*\}|\[.*\])\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    return text


class CodeAnalyzer:
    """Component responsible for finding bugs via LLM analysis."""
    def __init__(self, llm: AbstractLLMClient):
        self.llm = llm

    def analyze(self, project_dir: str, store: SQLiteStateStore, run_id: str) -> dict[str, Any]:
        system = "You are an expert Python developer. Analyze the code for bugs."
        user = f"Find bugs in the project at {project_dir}"
        resp = self.llm.call(system, user)
        
        store.append_event(
            events.llm_call_recorded(
                run_id=run_id,
                step_name="analyze_code",
                model=resp.model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                latency_ms=resp.latency_ms,
                prompt_hash=resp.prompt_hash,
                cached=resp.cached
            )
        )
        
        try:
            return json.loads(extract_json(resp.content))
        except json.JSONDecodeError:
            return {"raw": resp.content}


class PatchGenerator:
    """Component responsible for proposing fixes via LLM."""
    def __init__(self, llm: AbstractLLMClient):
        self.llm = llm

    def generate_patch(self, analysis: dict[str, Any], project_dir: str, store: SQLiteStateStore, run_id: str) -> dict[str, Any]:
        system = (
            "You are an expert Python developer. Fix the bugs and return the fix as a STRICT JSON array of patches.\n"
            "Each object in the array MUST have this exact structure:\n"
            "{\n"
            '  "file": "path/to/file.py",\n'
            '  "full_code": "the COMPLETE file content with the fixes applied"\n'
            "}\n"
            "DO NOT wrap your response in markdown blocks. Output raw JSON only."
        )
        
        # Read the files mentioned in the analysis
        files_content = ""
        try:
            import os
            files_to_read = set()
            for issue in analysis.get("issues", []):
                files_to_read.add(issue.get("file"))
            for f in files_to_read:
                if f:
                    path = os.path.join(project_dir, f)
                    if os.path.exists(path):
                        with open(path, 'r') as fp:
                            files_content += f"\n--- {f} ---\n{fp.read()}"
        except Exception:
            pass
            
        user = f"Fix these bugs: {json.dumps(analysis)}\n\nHere are the files:\n{files_content}"
        resp = self.llm.call(system, user)
        
        store.append_event(
            events.llm_call_recorded(
                run_id=run_id,
                step_name="generate_patch",
                model=resp.model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                latency_ms=resp.latency_ms,
                prompt_hash=resp.prompt_hash,
                cached=resp.cached
            )
        )
        
        try:
            return json.loads(extract_json(resp.content))
        except json.JSONDecodeError:
            return {"raw": resp.content}


class PatchVerifier:
    """Component responsible for verifying patches against tests and self-correcting."""
    def __init__(self, llm: AbstractLLMClient, runner: SandboxRunner, store: SQLiteStateStore):
        self.llm = llm
        self.runner = runner
        self.store = store

    def _apply_patches(self, project_dir: str, patch_data: Any) -> None:
        patches = []
        if isinstance(patch_data, list):
            patches = patch_data
        elif isinstance(patch_data, dict):
            if "patches" in patch_data:
                patches = patch_data["patches"]
            elif "old_code" in patch_data:
                patches = [patch_data]
                
        for p in patches:
            if isinstance(p, dict):
                target = f"{project_dir}/{p.get('file', '')}"
                
                # Support full_code replacement (most robust)
                if "full_code" in p:
                    try:
                        with open(target, 'w') as f:
                            f.write(p["full_code"])
                    except Exception as e:
                        print("Failed to write full_code:", e)
                    continue
                
                # Fallback to old_code / new_code replacement
                if "old_code" in p and "new_code" in p and "file" in p:
                    res = PatchApplier.apply_simple_patch(target, p["old_code"], p["new_code"])
                    if not res.success:
                        # fallback for slight indentation mismatches or missing newlines
                        stripped_old = p["old_code"].strip()
                        if stripped_old:
                            try:
                                with open(target, 'r') as f:
                                    content = f.read()
                                if stripped_old in content:
                                    content = content.replace(stripped_old, p["new_code"].strip(), 1)
                                    with open(target, 'w') as f:
                                        f.write(content)
                            except Exception:
                                pass

    def verify_and_correct(self, project_dir: str, patch: dict[str, Any], run_id: str, max_corrections: int = 3) -> dict[str, Any]:
        self._apply_patches(project_dir, patch)

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

            system = (
                "You are an expert Python developer. Your previous fix failed the tests. Provide a new fix as a STRICT JSON array of patches.\n"
                "Each object MUST have this exact structure:\n"
                "{\n"
                '  "file": "path/to/file.py",\n'
                '  "full_code": "the COMPLETE file content with the fixes applied"\n'
                "}\n"
                "DO NOT wrap your response in markdown blocks. Output raw JSON only."
            )
            
            # Re-read files that were just patched so it knows the current state
            files_content = ""
            try:
                import os
                patches = patch if isinstance(patch, list) else [patch]
                files_to_read = {p.get("file") for p in patches if isinstance(p, dict) and p.get("file")}
                for f in files_to_read:
                    if f:
                        path = os.path.join(project_dir, f)
                        if os.path.exists(path):
                            with open(path, 'r') as fp:
                                files_content += f"\n--- {f} ---\n{fp.read()}"
            except Exception:
                pass
                
            user = f"Fix these bugs: {test_res.output}. Here was the previous patch: {json.dumps(patch)}\n\nCurrent file contents:\n{files_content}"
            resp = self.llm.call(system, user)
            
            self.store.append_event(
                events.llm_call_recorded(
                    run_id=run_id,
                    step_name="verify_and_correct",
                    model=resp.model,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    latency_ms=resp.latency_ms,
                    prompt_hash=resp.prompt_hash,
                    cached=resp.cached
                )
            )

            try:
                new_patch = json.loads(extract_json(resp.content))
                self._apply_patches(project_dir, new_patch)
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
        
        # New components
        self.guardrails = GuardrailPipeline([PatchSafetyGuardrail(), RepetitionGuardrail()])
        self.working_memory = WorkingMemory(capacity=5)
        self.episodic_memory = EpisodicMemory(store=self.store)

    def review_and_fix(self, project_dir: str, run_id: str | None = None) -> dict[str, Any]:
        """Run the full review and repair loop on a project directory."""
        steps = [
            Step("analyze_code", self._step_analyze_code),
            Step("generate_patch", self._step_generate_patch),
            Step("verify_and_correct", self._step_verify_and_correct),
        ]

        workflow = DurableWorkflow("agent_loop", steps, self.store, run_id)
        
        # Setup Tracing
        tracer = Tracer(run_id=workflow.run_id)
        set_tracer(tracer)
        span = tracer.start_span("agent.review_and_fix")
        
        try:
            result = workflow.run({
                "project_dir": project_dir,
                "run_id": workflow.run_id,
            })
            tracer.end_span(span)
            return result
        except Exception as e:
            tracer.end_span(span, error=e)
            raise

    @traced("analyze_code")
    def _step_analyze_code(self, input_data: dict[str, Any]) -> dict[str, Any]:
        project_dir = input_data["project_dir"]
        run_id = input_data.get("run_id")
        analysis = self.analyzer.analyze(project_dir, self.store, run_id)
        self.working_memory.add(f"Analysis: {analysis}")
        return {"project_dir": project_dir, "run_id": run_id, "analysis": analysis}

    @traced("generate_patch")
    def _step_generate_patch(self, input_data: dict[str, Any]) -> dict[str, Any]:
        project_dir = input_data["project_dir"]
        analysis = input_data.get("analysis", {})
        run_id = input_data.get("run_id")

        patch_data = self.generator.generate_patch(analysis, project_dir, self.store, run_id)
        self.working_memory.add(f"Proposed patch: {patch_data}")
        
        # 1. Guardrail Check
        guardrail_result = self.guardrails.check_all(patch_data)
        if not guardrail_result.passed:
            self.store.append_event(
                events.Event(
                    run_id=run_id,
                    event_type="workflow_paused",
                    payload={"reason": "Guardrail violation", "details": guardrail_result.reason}
                )
            )
            from duraagent.workflow import WorkflowPaused
            raise WorkflowPaused(f"Guardrail failed: {guardrail_result.reason}")
            
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

    @traced("verify_and_correct")
    def _step_verify_and_correct(self, input_data: dict[str, Any]) -> dict[str, Any]:
        project_dir = input_data["project_dir"]
        patch = input_data.get("patch", {})
        run_id = input_data.get("run_id", "unknown")
        
        return self.verifier.verify_and_correct(project_dir, patch, run_id)
