"""Tests for the agent loop."""

import os
from pathlib import Path

import pytest

from duraagent.agent import Agent
from duraagent.harness import SandboxRunner, TestResult
from duraagent.llm import LLMClient, LLMResponse
from duraagent.state_store import SQLiteStateStore


class MockLLM(LLMClient):
    """Mock LLM that returns deterministic responses for testing."""
    def __init__(self, responses):
        super().__init__()
        self.responses = responses
        self.call_idx = 0

    def call(self, system_prompt, user_prompt, **kwargs):
        resp = self.responses[self.call_idx]
        self.call_idx = min(self.call_idx + 1, len(self.responses) - 1)
        return LLMResponse(content=resp)


class MockRunner(SandboxRunner):
    """Mock runner that returns deterministic test results."""
    def __init__(self, test_results):
        super().__init__()
        self.test_results = test_results
        self.call_idx = 0

    def run_tests(self, project_dir, **kwargs):
        res = self.test_results[self.call_idx]
        self.call_idx = min(self.call_idx + 1, len(self.test_results) - 1)
        return res


def test_agent_successful_first_try(tmp_path):
    """Test agent succeeds without needing self-correction."""
    store = SQLiteStateStore(tmp_path / "db")
    
    llm = MockLLM([
        '{"issues": []}',  # Analysis
        '{"file": "main.py", "old_code": "a", "new_code": "b"}'  # Patch
    ])
    
    runner = MockRunner([
        TestResult(passed=5, failed=0, exit_code=0, output="All passed")
    ])
    
    agent = Agent(store, llm, runner)
    
    # Create dummy file to patch
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("a")
    
    res = agent.review_and_fix(str(proj), "run-1")
    
    assert res["status"] == "success"
    assert res["attempts"] == 1


def test_agent_self_correction_loop(tmp_path):
    """Test agent fails first time, corrects itself on second try."""
    store = SQLiteStateStore(tmp_path / "db")
    
    llm = MockLLM([
        '{"issues": []}',  # Analysis
        '{"file": "main.py", "old_code": "a", "new_code": "b"}',  # Initial bad patch
        '{"file": "main.py", "old_code": "b", "new_code": "c"}',  # Corrected patch
    ])
    
    runner = MockRunner([
        TestResult(passed=4, failed=1, exit_code=1, output="Test failed"),  # Attempt 1 fails
        TestResult(passed=5, failed=0, exit_code=0, output="All passed")    # Attempt 2 passes
    ])
    
    agent = Agent(store, llm, runner)
    
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("a")
    
    res = agent.review_and_fix(str(proj), "run-1")
    
    assert res["status"] == "success"
    assert res["attempts"] == 2
    
    # Check that events recorded the correction
    events = store.get_events("run-1")
    correction_events = [e for e in events if getattr(e.event_type, "value", e.event_type) == "correction_attempted"]
    assert len(correction_events) == 2
    assert "FAILED" in correction_events[0].payload["result"]
    assert "SUCCESS" in correction_events[1].payload["result"]
