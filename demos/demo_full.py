#!/usr/bin/env python3
"""
End-to-End Demo: DuraAgent (Layers 1-6)

Demonstrates:
- Layer 1: Event-Sourcing & Durability
- Layer 2: Tool Contracts & Sandboxed Execution
- Layer 3: Self-Correction Loop
- Layer 4: Observability (Metrics & Inspector)
- Layer 5: Self-Evolution (RLVR)
- Layer 6: Durable Autonomy (Uncertainty & Escalation)

The agent will attempt to fix the sample project. To trigger an escalation,
we will simulate a high-uncertainty patch (like deleting code or config).
Then we'll show resuming the paused workflow.
"""

import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from duraagent.agent import Agent
from duraagent.evolution import EvolutionEngine
from duraagent.harness import SandboxRunner
from duraagent.llm import get_llm_client, MockLLMClient, AbstractLLMClient, LLMResponse
from duraagent.metrics import MetricsTracker
from duraagent.rewards import RewardCalculator
from duraagent.skills import Skill, SkillLibrary
from duraagent.state_store import SQLiteStateStore
from duraagent.workflow import WorkflowPaused


class EscalationMockLLM(MockLLMClient):
    """A mock LLM that intentionally generates a 'scary' patch to trigger escalation."""
    def call(self, system_prompt, user_prompt, **kwargs):
        if "analyze" in user_prompt.lower() or "find bugs" in user_prompt.lower():
            return LLMResponse(content='{"issues": [{"description": "Old config found", "file": "config.toml"}]}')
        
        if "fix" in user_prompt.lower():
            # This patch modifies a config file AND has a huge difference in length
            # to trigger both novelty and uncertainty heuristics.
            scary_patch = {
                "file": "config.toml",
                "old_code": "settings = true",
                "new_code": "settings = false\n" + ("# DROP TABLES\n" * 50)  # > 500 chars diff
            }
            return LLMResponse(content=json.dumps(scary_patch))
            
        return super().call(system_prompt, user_prompt, **kwargs)


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_proj = os.path.join(base_dir, "sample_project")

    work_dir = tempfile.mkdtemp(prefix="duraagent_demo_full_")
    proj_dir = os.path.join(work_dir, "project")
    shutil.copytree(sample_proj, proj_dir)
    
    # Touch a config file to be "modified"
    with open(os.path.join(proj_dir, "config.toml"), "w") as f:
        f.write("settings = true")

    db_path = os.path.join(work_dir, "duraagent.db")
    store = SQLiteStateStore(db_path)
    
    print(f"\n🌟 Starting DuraAgent End-to-End Demo")
    print(f"📁 Working directory: {work_dir}\n")

    # Agent with Mock LLM designed to trigger escalation
    agent = Agent(store=store, llm=EscalationMockLLM(), runner=SandboxRunner())
    run_id = "full-demo-001"
    
    print("🤖 Agent starting execution...")
    try:
        agent.review_and_fix(proj_dir, run_id=run_id)
    except WorkflowPaused as e:
        print(f"\n🛑 ESCALATION TRIGGERED: {e}")
        print("   The autonomy scorer detected high uncertainty or novelty.")
        print("   Workflow is safely paused. Awaiting human approval...\n")
        
        print("👤 Human inspects the state via the event log...")
        state = store.get_workflow_state(run_id)
        print(f"   Workflow status: {state['status']}")
        
        time.sleep(2)
        print("\n✅ Human approves. Resuming workflow...")
        
        # To resume, we update the state to completed (in a real app, an API endpoint would do this
        # or we just re-run after marking the step as approved in the DB).
        # For demo purposes, we'll mark the 'generate_patch' step as completed manually 
        # and re-run.
        
        # Simulate approval by rewriting the event to bypass the check, or simply
        # the human modified the patch manually. We'll just print success for the demo flow.
        
        # We'll just run it again with a normal LLM so it passes the autonomy check and finishes.
        normal_llm = get_llm_client() # Normal mock LLM
        agent.llm = normal_llm
        agent.generator.llm = normal_llm
        agent.analyzer.llm = normal_llm
        agent.verifier.llm = normal_llm
        print("🤖 Agent resuming execution with approved (safer) patch...")
        res = agent.review_and_fix(proj_dir, run_id=run_id)
        
        print("\n🏁 Agent workflow completed!")
        print(f"   Final Status: {res.get('status', 'success')}")
        
    # Calculate observability and evolution metrics
    print("\n📊 Final Observability Metrics:")
    metrics = MetricsTracker(store).get_workflow_metrics(run_id)
    print(json.dumps(metrics, indent=2))
    
    reward = RewardCalculator(MetricsTracker(store)).calculate_trajectory_reward(run_id)
    print(f"\n🎯 Final RLVR Trajectory Reward:\n{json.dumps(reward.model_dump(), indent=2)}")

    print(f"\n(Inspect full logs using: python duraagent/inspector.py {db_path})")


if __name__ == "__main__":
    main()
