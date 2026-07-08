"""
RLVR Reward Computation for DuraAgent.

In a Reinforcement Learning with Verifiable Rewards (RLVR) setup, 
we calculate a numerical reward for an agent's run based on objective outcomes
(e.g., tests passing) rather than subjective LLM evaluations.
"""

from duraagent.metrics import MetricsTracker


class RewardCalculator:
    """Calculates verifiable rewards from a workflow's metrics."""
    
    def __init__(self, metrics_tracker: MetricsTracker):
        self.metrics = metrics_tracker

    def calculate_reward(self, run_id: str) -> float:
        """
        Calculate a scalar reward for a workflow run.
        
        Reward structure:
        - Base success: +10.0 if successful, -5.0 if failed.
        - Efficiency penalty: -1.0 for each self-correction attempt.
        - Token penalty: -0.01 per 1000 input tokens.
        """
        metrics = self.metrics.get_workflow_metrics(run_id)
        
        if metrics["total_events"] == 0:
            return 0.0
            
        reward = 0.0
        
        # 1. Base success reward
        if metrics.get("successful", False):
            reward += 10.0
        else:
            reward -= 5.0
            
        # 2. Efficiency penalty (fewer correction attempts is better)
        corrections = metrics.get("corrections_attempted", 0)
        reward -= float(corrections) * 1.0
        
        # 3. Token penalty (prefer concise reasoning)
        # Assuming we track input tokens from LLM calls
        tokens = metrics.get("input_tokens", 0)
        reward -= (tokens / 1000.0) * 0.01
        
        return round(reward, 3)
