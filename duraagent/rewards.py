"""
RLVR Reward Computation for DuraAgent.

Layer: AI Engineering
Role:  In a Reinforcement Learning with Verifiable Rewards (RLVR) setup, 
       we calculate a numerical reward for an agent's run based on objective outcomes
       (e.g., tests passing) rather than subjective LLM evaluations.
       This enables continual learning and self-evolution over trajectories.
"""

from pydantic import BaseModel, ConfigDict

from duraagent.metrics import MetricsTracker


class TrajectoryReward(BaseModel):
    """Multi-signal reward decomposition for a full run trajectory."""
    model_config = ConfigDict(frozen=True)

    run_id: str
    base_success_score: float
    efficiency_penalty: float
    token_penalty: float
    total_reward: float


class RewardCalculator:
    """Calculates verifiable rewards from a workflow's metrics over a trajectory."""
    
    def __init__(self, metrics_tracker: MetricsTracker):
        self.metrics = metrics_tracker

    def calculate_reward(self, run_id: str) -> float:
        """Convenience method returning just the scalar total."""
        return self.calculate_trajectory_reward(run_id).total_reward

    def calculate_trajectory_reward(self, run_id: str) -> TrajectoryReward:
        """
        Calculate a multi-signal reward for a workflow run trajectory.
        
        Reward structure:
        - Base success: +10.0 if successful, -5.0 if failed.
        - Efficiency penalty: -1.0 for each self-correction attempt.
        - Token penalty: -0.01 per 1000 input tokens.
        """
        metrics = self.metrics.get_workflow_metrics(run_id)
        
        if metrics["total_events"] == 0:
            return TrajectoryReward(
                run_id=run_id,
                base_success_score=0.0,
                efficiency_penalty=0.0,
                token_penalty=0.0,
                total_reward=0.0
            )
            
        # 1. Base success reward
        base_score = 10.0 if metrics.get("successful", False) else -5.0
            
        # 2. Efficiency penalty (fewer correction attempts is better)
        corrections = metrics.get("corrections_attempted", 0)
        eff_penalty = float(corrections) * -1.0
        
        # 3. Token penalty (prefer concise reasoning)
        tokens = metrics.get("input_tokens", 0)
        tok_penalty = (tokens / 1000.0) * -0.01
        
        total = base_score + eff_penalty + tok_penalty
        
        return TrajectoryReward(
            run_id=run_id,
            base_success_score=base_score,
            efficiency_penalty=eff_penalty,
            token_penalty=tok_penalty,
            total_reward=round(total, 3)
        )

