"""
Skill Library for DuraAgent.

Layer: AI Engineering
Role:  Stores and retrieves learned instructions (prompts) based on reward signals.
       This allows the agent to 'evolve' by remembering instructions that yielded
       high rewards and discarding poor ones.
"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Skill(BaseModel):
    """A learned prompt or procedural rule."""
    model_config = ConfigDict(frozen=False)

    name: str
    description: str
    system_prompt: str
    avg_reward: float = 0.0
    runs: int = 0
    ema_alpha: float = Field(default=0.1, description="Exponential moving average decay factor")

    def update_reward(self, reward: float) -> None:
        """Update the running average reward using EMA to decay old signals."""
        self.runs += 1
        if self.runs == 1:
            self.avg_reward = reward
        else:
            self.avg_reward = (self.ema_alpha * reward) + ((1.0 - self.ema_alpha) * self.avg_reward)


class SkillLibrary:
    """Persistent storage for evolved skills."""
    
    def __init__(self, db_path: str = "skills.json"):
        self.db_path = db_path
        self.skills: dict[str, Skill] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self.skills[k] = Skill.model_validate(v)
            except (json.JSONDecodeError, OSError):
                self.skills = {}

    def _save(self) -> None:
        with open(self.db_path, "w") as f:
            data = {k: v.model_dump() for k, v in self.skills.items()}
            json.dump(data, f, indent=2)

    def get_skill(self, name: str) -> Skill | None:
        return self.skills.get(name)
        
    def add_skill(self, skill: Skill) -> None:
        """Add a new skill variant."""
        self.skills[skill.name] = skill
        self._save()

    def record_run(self, name: str, reward: float) -> None:
        """Update the running average reward for a skill."""
        if name in self.skills:
            self.skills[name].update_reward(reward)
            self._save()

    def get_best_skill(self) -> Skill | None:
        """Retrieve the skill with the highest average reward."""
        if not self.skills:
            return None
        return max(self.skills.values(), key=lambda s: s.avg_reward)

