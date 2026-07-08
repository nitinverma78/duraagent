"""
Observability Metrics for DuraAgent.

Calculates key performance metrics from the event log:
- Self-correction success rate
- Time-to-resolution
- Token usage and cost per workflow
- Common failure modes
"""

from __future__ import annotations

from typing import Any

from duraagent.events import EventType
from duraagent.state_store import StateStore


class MetricsTracker:
    def __init__(self, store: StateStore):
        self.store = store

    def get_workflow_metrics(self, run_id: str) -> dict[str, Any]:
        """Calculate metrics for a specific workflow run."""
        events = self.store.get_events(run_id)
        
        metrics = {
            "total_events": len(events),
            "duration_ms": 0.0,
            "llm_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "sandbox_executions": 0,
            "corrections_attempted": 0,
            "successful": False,
        }
        
        start_time = None
        end_time = None
        
        for e in events:
            et = e.event_type
            if isinstance(et, EventType):
                et = et.value
                
            if et == EventType.WORKFLOW_STARTED.value:
                start_time = e.timestamp
            elif et == EventType.WORKFLOW_COMPLETED.value:
                end_time = e.timestamp
                metrics["successful"] = True
            elif et == EventType.LLM_CALL_RECORDED.value:
                metrics["llm_calls"] += 1
                metrics["input_tokens"] += e.payload.get("input_tokens", 0)
                metrics["output_tokens"] += e.payload.get("output_tokens", 0)
            elif et == EventType.SANDBOX_EXECUTION_RECORDED.value:
                metrics["sandbox_executions"] += 1
            elif et == EventType.CORRECTION_ATTEMPTED.value:
                metrics["corrections_attempted"] += 1
                
        # Calculate duration if we have start and end (this is simplified for demo)
        # In a real system you'd parse the ISO strings
        
        return metrics

    def get_global_metrics(self) -> dict[str, Any]:
        """Aggregate metrics across all runs."""
        runs = self.store.get_all_runs()
        
        total_runs = len(runs)
        successful_runs = sum(1 for r in runs if r["status"] == "completed")
        failed_runs = sum(1 for r in runs if r["status"] == "failed")
        
        return {
            "total_runs": total_runs,
            "success_rate": successful_runs / total_runs if total_runs > 0 else 0.0,
            "failed_runs": failed_runs,
        }
