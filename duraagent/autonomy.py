"""
Autonomy Scoring for DuraAgent.

Determines whether an agent should proceed autonomously or escalate to a human.
Calculates uncertainty and novelty scores based on the generated plan/patch.
"""

import json


class AutonomyScorer:
    def __init__(self, uncertainty_threshold: float = 0.7, novelty_threshold: float = 0.8):
        self.uncertainty_threshold = uncertainty_threshold
        self.novelty_threshold = novelty_threshold

    def evaluate_patch(self, patch_data: dict) -> dict:
        """
        Evaluate a patch for uncertainty and novelty.
        Returns a dict with scores and a boolean `should_escalate`.
        """
        # In a real system, you might use an LLM call or heuristics here.
        # For demonstration, we'll use a simple heuristic:
        # - High uncertainty if the patch deletes a lot of code.
        # - High novelty if the patch modifies files outside common directories.
        
        uncertainty = 0.1
        novelty = 0.1
        reasons = []

        # Heuristic 1: Large diffs increase uncertainty
        old_code = patch_data.get("old_code", "")
        new_code = patch_data.get("new_code", "")
        
        if abs(len(new_code) - len(old_code)) > 500:
            uncertainty += 0.5
            reasons.append("Large code modification detected.")
            
        if patch_data.get("requires_db_migration", False):
            uncertainty += 0.8
            reasons.append("Database migration detected.")
            
        # Heuristic 2: Touching core configuration increases novelty
        file_path = patch_data.get("file", "")
        if "config" in file_path or "settings" in file_path or file_path.endswith(".toml"):
            novelty += 0.7
            reasons.append("Core configuration modification detected.")

        uncertainty = round(min(1.0, uncertainty), 3)
        novelty = round(min(1.0, novelty), 3)
        
        should_escalate = (
            uncertainty >= self.uncertainty_threshold or 
            novelty >= self.novelty_threshold
        )
        
        return {
            "uncertainty": uncertainty,
            "novelty": novelty,
            "should_escalate": should_escalate,
            "reasons": reasons
        }
