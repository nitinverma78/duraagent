"""
Prompt Mutation Engine for DuraAgent.

Uses an LLM to mutate (evolve) agent system prompts. By generating
variations, testing them in the sandbox (via the agent loop), and scoring
them with RLVR rewards, the system discovers the most effective prompts.
"""
from __future__ import annotations

from duraagent.llm import get_llm_client, AbstractLLMClient
from duraagent.metrics import MetricsTracker
from duraagent.skills import SkillLibrary, Skill


class EvolutionEngine:
    def __init__(self, llm: AbstractLLMClient | None = None):
        self.llm = llm or get_llm_client()

    def mutate_skill(self, parent_skill: Skill, feedback: str) -> Skill:
        """
        Create a new variant of a skill based on feedback.
        """
        system = (
            "You are an AI evolution engine. Your task is to improve an agent's system prompt "
            "based on empirical feedback from a test run."
        )
        
        user = (
            f"Current Prompt:\n{parent_skill.system_prompt}\n\n"
            f"Feedback from last run:\n{feedback}\n\n"
            "Output ONLY the new, improved system prompt. Do not wrap in quotes or code blocks."
        )
        
        resp = self.llm.call(system, user)
        
        # Clean up output
        new_prompt = resp.content.strip()
        if new_prompt.startswith("```") and new_prompt.endswith("```"):
            lines = new_prompt.split("\n")
            new_prompt = "\n".join(lines[1:-1])
            
        variant_name = f"{parent_skill.name}_v{parent_skill.runs + 1}"
        
        return Skill(
            name=variant_name,
            description=f"Evolved from {parent_skill.name}",
            system_prompt=new_prompt,
        )
