"""
Skill Library for DuraAgent.

Stores and retrieves learned instructions (prompts) based on reward signals.
This allows the agent to 'evolve' by remembering instructions that yielded
high rewards and discarding poor ones.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class Skill:
    name: str
    description: str
    system_prompt: str
    avg_reward: float = 0.0
    runs: int = 0


class SkillLibrary:
    """Persistent storage for evolved skills."""
    
    def __init__(self, db_path: str = "skills.json"):
        self.db_path = db_path
        self.skills: dict[str, Skill] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "r") as f:
                data = json.load(f)
                for k, v in data.items():
                    self.skills[k] = Skill(**v)

    def _save(self):
        with open(self.db_path, "w") as f:
            data = {k: asdict(v) for k, v in self.skills.items()}
            json.dump(data, f, indent=2)

    def get_skill(self, name: str) -> Skill | None:
        return self.skills.get(name)
        
    def add_skill(self, skill: Skill):
        """Add a new skill variant."""
        self.skills[skill.name] = skill
        self._save()

    def record_run(self, name: str, reward: float):
        """Update the running average reward for a skill."""
        if name in self.skills:
            skill = self.skills[name]
            total = skill.avg_reward * skill.runs
            skill.runs += 1
            skill.avg_reward = (total + reward) / skill.runs
            self._save()

    def get_best_skill(self) -> Skill | None:
        """Retrieve the skill with the highest average reward."""
        if not self.skills:
            return None
        return max(self.skills.values(), key=lambda s: s.avg_reward)
