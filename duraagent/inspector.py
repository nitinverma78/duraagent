#!/usr/bin/env python3
"""
CLI Event Inspector for DuraAgent.

Allows you to query and inspect the immutable event log, showing exactly
what the agent did. This is a crucial observability tool for debugging.
"""

import argparse
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from duraagent.state_store import StateStore
from duraagent.metrics import MetricsTracker


def print_run_list(store: StateStore):
    runs = store.get_all_runs()
    if not runs:
        print("No runs found in database.")
        return
        
    print(f"\n{'ID':<25} | {'Workflow':<15} | {'Status':<10} | {'Created At'}")
    print("-" * 80)
    for r in runs:
        print(f"{r['run_id']:<25} | {r['workflow_name']:<15} | {r['status']:<10} | {r['created_at']}")


def print_run_details(store: StateStore, run_id: str):
    state = store.get_workflow_state(run_id)
    if not state:
        print(f"Run {run_id} not found.")
        return
        
    print(f"\n=== Run: {run_id} ===")
    print(f"Workflow: {state['workflow_name']}")
    print(f"Status:   {state['status']}")
    
    print("\n--- Materialized Step State ---")
    steps = store.get_all_step_states(run_id)
    for s in steps:
        status_icon = {"completed": "✅", "failed": "❌", "skipped": "⏭️ ", "running": "▶️"}.get(s["status"], "?")
        print(f"  {status_icon} Step {s['step_index']}: {s['step_name']} ({s['status']})")
        if s["error"]:
            print(f"      Error: {s['error']}")
            
    print("\n--- Event Log (Source of Truth) ---")
    events = store.get_events(run_id)
    for i, e in enumerate(events):
        et = getattr(e.event_type, "value", e.event_type)
        print(f"  {i+1:02d}. [{e.timestamp[11:19]}] {et}")
        
    print("\n--- Metrics ---")
    metrics = MetricsTracker(store).get_workflow_metrics(run_id)
    print(json.dumps(metrics, indent=2))


def main():
    parser = argparse.ArgumentParser(description="DuraAgent Event Inspector")
    parser.add_argument("--db", default="duraagent.db", help="Path to SQLite database")
    parser.add_argument("run_id", nargs="?", help="Specific run ID to inspect")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.db):
        print(f"Database {args.db} not found.")
        sys.exit(1)
        
    store = StateStore(args.db)
    
    if args.run_id:
        print_run_details(store, args.run_id)
    else:
        print_run_list(store)


if __name__ == "__main__":
    main()
