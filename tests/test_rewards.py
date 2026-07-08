"""Tests for rewards and skills."""

import os

from duraagent.rewards import RewardCalculator
from duraagent.skills import Skill, SkillLibrary


class MockMetricsTracker:
    def __init__(self, metrics_data):
        self.metrics_data = metrics_data

    def get_workflow_metrics(self, run_id):
        return self.metrics_data


def test_reward_successful_run():
    metrics = {
        "total_events": 10,
        "successful": True,
        "corrections_attempted": 1,
        "input_tokens": 1000
    }
    calc = RewardCalculator(MockMetricsTracker(metrics))
    reward = calc.calculate_reward("run-1")
    
    # Base success (+10), 1 correction (-1), 1000 tokens (-0.01) = 8.99
    assert reward == 8.99


def test_reward_failed_run():
    metrics = {
        "total_events": 10,
        "successful": False,
        "corrections_attempted": 3,
        "input_tokens": 2000
    }
    calc = RewardCalculator(MockMetricsTracker(metrics))
    reward = calc.calculate_reward("run-2")
    
    # Base fail (-5), 3 corrections (-3), 2000 tokens (-0.02) = -8.02
    assert reward == -8.02


def test_skill_library(tmp_path):
    db = tmp_path / "skills.json"
    lib = SkillLibrary(str(db))
    
    s1 = Skill("s1", "desc", "prompt1")
    lib.add_skill(s1)
    
    lib.record_run("s1", 10.0)
    lib.record_run("s1", 5.0)
    
    # Reload to test persistence
    lib2 = SkillLibrary(str(db))
    loaded = lib2.get_skill("s1")
    
    assert loaded.runs == 2
    assert loaded.avg_reward == 7.5
    assert lib2.get_best_skill().name == "s1"
