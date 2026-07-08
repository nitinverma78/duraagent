#!/usr/bin/env python3
"""
Demo: Agent Loop with Self-Correction (Layer 3)

Shows the core agentic loop:
1. Agent analyzes the buggy sample project
2. Agent generates a patch
3. Agent runs tests (VERIFIABLE REWARD)
4. If tests fail, agent feeds the error back to the LLM for self-correction
"""

import os
import shutil
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from duraagent.agent import Agent
from duraagent.state_store import SQLiteStateStore
from duraagent.harness import SandboxRunner


def main():
    # 1. Setup workspace
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_proj = os.path.join(base_dir, "sample_project")

    # Create a temporary working copy so we don't modify the original
    work_dir = tempfile.mkdtemp(prefix="duraagent_demo3_")
    proj_dir = os.path.join(work_dir, "project")
    shutil.copytree(sample_proj, proj_dir)
    
    db_path = os.path.join(work_dir, "demo3.db")
    
    print(f"\n🚀 Starting Layer 3 Demo: Agent Loop + Self-Correction")
    print(f"📁 Working directory: {proj_dir}")
    print(f"📊 State store: {db_path}\n")

    # 2. Run initial tests to show they fail
    runner = SandboxRunner()
    print("🏃 Running initial test suite...")
    initial_res = runner.run_tests(proj_dir)
    print(f"   Result: {initial_res.passed} passed, {initial_res.failed} failed\n")
    
    # 3. Initialize Agent
    store = SQLiteStateStore(db_path)
    agent = Agent(store=store, runner=runner)

    # 4. Run the Agent Loop
    run_id = "demo-loop-001"
    print("🤖 Agent beginning review and repair cycle...")
    result = agent.review_and_fix(proj_dir, run_id=run_id)

    print("\n🏁 Agent workflow completed!")
    print(f"   Final Status: {result['status']}")
    print(f"   Correction Attempts: {result['attempts']}")
    
    # 5. Show events related to self-correction
    print("\n📋 Self-Correction Event Log:")
    events = store.get_events(run_id)
    correction_events = [e for e in events if e.event_type == "correction_attempted" or getattr(e.event_type, "value", "") == "correction_attempted"]
    
    for e in correction_events:
        attempt = e.payload.get("attempt", "?")
        res = e.payload.get("result", "")
        print(f"   Attempt {attempt}: {res}")

    print(f"\n(You can inspect the full event log at {db_path})")


if __name__ == "__main__":
    main()
