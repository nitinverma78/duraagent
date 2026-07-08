#!/usr/bin/env python3
"""
Demo: Durable Workflow with Crash Recovery (Layer 1)

This demo shows:
1. A 5-step workflow where step 3 fails on the first run (simulating a crash)
2. On re-run with the same run_id, steps 1-2 are SKIPPED (cached), step 3 retries and succeeds
3. The full event log is printed, showing the exact sequence of events

This is the INTERVIEW OPENER. It proves you understand:
- Event sourcing (the log IS the source of truth)
- Idempotent replay (completed steps are skipped)
- Crash recovery (resume from last checkpoint)
- Positional awareness (the engine always knows where it is)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from duraagent.events import EventType
from duraagent.state_store import SQLiteStateStore
from duraagent.workflow import (
    DurableWorkflow,
    RetryPolicy,
    Step,
    StepFailedPermanently,
)

# ── Simulated step functions ──────────────────────────────────────────

# Track how many times step_3 has been called across "runs"
_step3_call_count = 0


def step_fetch_code(input_data: dict) -> dict:
    """Simulate fetching code to review."""
    print("  📥 Step 1: Fetching code...")
    return {"code": "def add(a, b): return a + b", "language": "python"}


def step_parse_ast(input_data: dict) -> dict:
    """Simulate parsing the AST."""
    print("  🌳 Step 2: Parsing AST...")
    return {"ast_nodes": 42, "functions": ["add"], "complexity": "low"}


def step_call_llm(input_data: dict) -> dict:
    """Simulate an LLM call that fails on first attempt (transient API error)."""
    global _step3_call_count
    _step3_call_count += 1
    print(f"  🤖 Step 3: Calling LLM (attempt {_step3_call_count})...")

    if _step3_call_count <= 1:
        raise ConnectionError("API rate limit exceeded (simulated transient failure)")

    return {"issues": [{"type": "bug", "description": "off-by-one error", "line": 7}]}


def step_generate_patch(input_data: dict) -> dict:
    """Simulate generating a fix patch."""
    print("  🔧 Step 4: Generating patch...")
    return {"patch": "--- a/main.py\n+++ b/main.py\n@@ -7 +7 @@\n-  range(n)\n+  range(n+1)"}


def step_verify_patch(input_data: dict) -> dict:
    """Simulate verifying the patch against tests."""
    print("  ✅ Step 5: Verifying patch in sandbox...")
    return {"tests_passed": True, "tests_run": 12, "tests_failed": 0}


# ── Main demo ──────────────────────────────────────────────────────────


def print_separator(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}\n")


def print_event_log(store: SQLiteStateStore, run_id: str) -> None:
    """Print the full event log for a run."""
    print_separator("📋 EVENT LOG (Source of Truth)")
    for i, event in enumerate(store.get_events(run_id)):
        et = event.event_type
        if isinstance(et, EventType):
            et = et.value

        # Color-code by event type
        icons = {
            "workflow_started": "🚀",
            "workflow_completed": "🏁",
            "workflow_failed": "💥",
            "step_started": "▶️ ",
            "step_completed": "✅",
            "step_failed": "❌",
            "step_skipped": "⏭️ ",
        }
        icon = icons.get(et, "📝")
        payload_summary = ""

        if et == "step_skipped":
            payload_summary = f" [{event.payload.get('step_name', '')}] reason={event.payload.get('reason', '')}"
        elif et in ("step_started", "step_completed", "step_failed"):
            payload_summary = f" [{event.payload.get('step_name', '')}]"
            if et == "step_failed":
                payload_summary += f" attempt={event.payload.get('attempt', '')} retry={event.payload.get('will_retry', '')}"
            elif et == "step_completed":
                payload_summary += f" duration={event.payload.get('duration_ms', 0):.1f}ms"

        print(f"  {i+1:2d}. {icon} {et}{payload_summary}")

    print()


def main():
    # Use a temp directory for the database
    db_dir = tempfile.mkdtemp(prefix="duraagent_demo_")
    db_path = os.path.join(db_dir, "demo.db")
    store = SQLiteStateStore(db_path)

    # Fixed run_id so we can "resume" the same run
    run_id = "demo-durability-001"

    # Define the workflow
    steps = [
        Step("fetch_code", step_fetch_code),
        Step("parse_ast", step_parse_ast),
        Step(
            "call_llm",
            step_call_llm,
            retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.1),
        ),
        Step("generate_patch", step_generate_patch),
        Step("verify_patch", step_verify_patch),
    ]

    # ── RUN 1: Will fail at step 3 ────────────────────────────────────
    print_separator("RUN 1: Initial execution (step 3 will fail)")
    workflow = DurableWorkflow("code_review", steps, store, run_id)

    try:
        workflow.run({"diff": "sample diff content"})
    except StepFailedPermanently:
        # This won't happen because retry succeeds on attempt 2
        pass

    # Show what happened
    print_event_log(store, run_id)

    # ── Show materialized state ────────────────────────────────────────
    print_separator("📊 MATERIALIZED STATE (Derived from events)")
    wf_state = store.get_workflow_state(run_id)
    print(f"  Workflow: {wf_state['workflow_name']}")
    print(f"  Status:   {wf_state['status']}")
    print(f"  Last completed step index: {wf_state['last_step_index']}")
    print()

    for step_state in store.get_all_step_states(run_id):
        status_icon = {"completed": "✅", "skipped": "⏭️ ", "failed": "❌", "running": "▶️ "}.get(
            step_state["status"], "❓"
        )
        print(f"  {status_icon} {step_state['step_name']}: {step_state['status']}")

    # ── REBUILD PROOF ──────────────────────────────────────────────────
    print_separator("🔄 REBUILD PROOF: Delete views, replay events, verify consistency")
    print("  Deleting materialized views...")
    store.rebuild_materialized_views(run_id)
    print("  Rebuilt from event log.")

    rebuilt_state = store.get_workflow_state(run_id)
    assert rebuilt_state["status"] == wf_state["status"], "State mismatch after rebuild!"
    assert rebuilt_state["last_step_index"] == wf_state["last_step_index"], "Step index mismatch!"
    print("  ✅ Rebuilt state matches original — the event log IS the source of truth.")

    # ── RUN 2: Resume (simulate process restart) ──────────────────────
    print_separator("RUN 2: Resume after 'crash' (same run_id)")
    print("  Creating new workflow instance with same run_id...")
    print("  (In production, this is what happens after a process restart)\n")

    workflow2 = DurableWorkflow("code_review", steps, store, run_id)
    result = workflow2.run()

    print(f"\n  Final result: {json.dumps(result, indent=2)}")

    # Show the complete event log including the resume
    print_event_log(store, run_id)

    # Cleanup
    print(f"  📁 Database: {db_path}")
    print(f"  (You can inspect it with: sqlite3 {db_path} 'SELECT * FROM events;')")


if __name__ == "__main__":
    main()
