"""
Observability Metrics for DuraAgent.

Calculates key performance metrics from the event log:
- Self-correction success rate
- Time-to-resolution
- Token usage and cost per workflow
- Common failure modes
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from duraagent.events import EventType
from duraagent.state_store import SQLiteStateStore


class MetricsSnapshot(BaseModel):
    """Point-in-time capture of aggregated system metrics."""
    model_config = ConfigDict(frozen=True)

    total_runs: int
    success_rate: float
    avg_duration_s: float
    avg_tokens_per_run: float
    avg_corrections_per_run: float
    p95_duration_s: float


class MetricsTracker:
    def __init__(self, store: SQLiteStateStore):
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
            elif et == EventType.WORKFLOW_FAILED.value:
                end_time = e.timestamp
                metrics["successful"] = False
            elif et == EventType.LLM_CALL_RECORDED.value:
                metrics["llm_calls"] += 1
                metrics["input_tokens"] += e.payload.get("input_tokens", 0)
                metrics["output_tokens"] += e.payload.get("output_tokens", 0)
            elif et == EventType.SANDBOX_EXECUTION_RECORDED.value:
                metrics["sandbox_executions"] += 1
            elif et == EventType.CORRECTION_ATTEMPTED.value:
                metrics["corrections_attempted"] += 1
                
        if start_time and end_time:
            # Parse ISO strings: "2023-10-25T12:34:56.789123+00:00"
            fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
            try:
                dt_start = datetime.strptime(start_time, fmt)
                dt_end = datetime.strptime(end_time, fmt)
                metrics["duration_ms"] = (dt_end - dt_start).total_seconds() * 1000
            except ValueError:
                pass # Fallback to 0.0 if format changes
        
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


class MetricsDashboard:
    """Computes advanced aggregations and percentiles across runs."""

    def __init__(self, tracker: MetricsTracker):
        self.tracker = tracker

    def generate_snapshot(self) -> MetricsSnapshot:
        runs = self.tracker.store.get_all_runs()
        if not runs:
            return MetricsSnapshot(
                total_runs=0, success_rate=0.0, avg_duration_s=0.0,
                avg_tokens_per_run=0.0, avg_corrections_per_run=0.0, p95_duration_s=0.0
            )

        success_count = 0
        durations = []
        tokens = []
        corrections = []

        for run in runs:
            run_id = run["run_id"]
            if run["status"] == "completed":
                success_count += 1
                
            metrics = self.tracker.get_workflow_metrics(run_id)
            if metrics["duration_ms"] > 0:
                durations.append(metrics["duration_ms"] / 1000.0)
            tokens.append(metrics["input_tokens"] + metrics["output_tokens"])
            corrections.append(metrics["corrections_attempted"])

        success_rate = success_count / len(runs)
        avg_dur = statistics.mean(durations) if durations else 0.0
        p95_dur = statistics.quantiles(durations, n=20)[18] if len(durations) >= 2 else avg_dur
        avg_tok = statistics.mean(tokens) if tokens else 0.0
        avg_cor = statistics.mean(corrections) if corrections else 0.0

        return MetricsSnapshot(
            total_runs=len(runs),
            success_rate=round(success_rate, 3),
            avg_duration_s=round(avg_dur, 1),
            avg_tokens_per_run=round(avg_tok, 1),
            avg_corrections_per_run=round(avg_cor, 1),
            p95_duration_s=round(p95_dur, 1),
        )
