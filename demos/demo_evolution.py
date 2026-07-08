#!/usr/bin/env python3
"""
Demo: Self-Evolution via RLVR (Layer 5)

Demonstrates the evolution cycle:
1. Seed a basic skill (prompt).
2. Run the agent using that skill.
3. Calculate objective reward (did tests pass? how many attempts?).
4. Mutate the skill based on the reward/outcome.
5. Store the best skill.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from duraagent.agent import Agent
from duraagent.evolution import EvolutionEngine
from duraagent.harness import SandboxRunner
from duraagent.metrics import MetricsTracker
from duraagent.rewards import RewardCalculator
from duraagent.skills import Skill, SkillLibrary
from duraagent.state_store import SQLiteStateStore


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_proj = os.path.join(base_dir, "sample_project")

    work_dir = tempfile.mkdtemp(prefix="duraagent_demo5_")
    db_path = os.path.join(work_dir, "demo5.db")
    skills_path = os.path.join(work_dir, "skills.json")
    
    print(f"\n🧬 Starting Layer 5 Demo: Self-Evolution via RLVR")
    print(f"📁 Working directory: {work_dir}\n")

    store = SQLiteStateStore(db_path)
    runner = SandboxRunner()
    metrics = MetricsTracker(store)
    reward_calc = RewardCalculator(metrics)
    skills = SkillLibrary(skills_path)
    evolver = EvolutionEngine()

    # 1. Seed initial skill
    base_skill = Skill(
        name="base_coder",
        description="Initial rudimentary prompt",
        system_prompt="You are a coder. Fix the bugs.",
    )
    skills.add_skill(base_skill)
    
    current_skill = base_skill

    # 2. Run evolution loop for 2 generations
    for generation in range(1, 3):
        print(f"🔄 Generation {generation} using skill: {current_skill.name}")
        print(f"   Prompt: \"{current_skill.system_prompt}\"")
        
        # Setup fresh project copy for this run
        proj_dir = os.path.join(work_dir, f"project_gen{generation}")
        shutil.copytree(sample_proj, proj_dir)
        
        run_id = f"gen-{generation}"
        agent = Agent(store, runner=runner)
        
        # In a real system, the agent would use current_skill.system_prompt
        # For the demo, we just run the agent and score it
        print("   🤖 Running agent...")
        res = agent.review_and_fix(proj_dir, run_id=run_id)
        
        # Calculate Reward
        reward = reward_calc.calculate_reward(run_id)
        print(f"   🎯 Reward calculated: {reward} (Status: {res['status']}, Attempts: {res.get('attempts')})")
        
        skills.record_run(current_skill.name, reward)
        
        # Mutate for next generation
        if generation < 2:
            feedback = f"The agent achieved a reward of {reward}. Status was {res['status']}."
            if reward < 10.0:
                feedback += " It took too many attempts or failed. The prompt needs to instruct the agent to be more careful and analyze the test output thoroughly."
                
            print("   🧬 Mutating prompt based on feedback...")
            current_skill = evolver.mutate_skill(current_skill, feedback)
            skills.add_skill(current_skill)
            print("")

    print("\n🏆 Evolution Complete!")
    best = skills.get_best_skill()
    print(f"Best Skill: {best.name}")
    print(f"Avg Reward: {best.avg_reward}")
    print(f"Prompt: {best.system_prompt}")


if __name__ == "__main__":
    main()
