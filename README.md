# DuraAgent: Foundation Agentic Engineering

DuraAgent is a production-grade agentic architecture demonstrating robust execution, 
observability, and continuous self-evolution. It is built using the principles of 
Durable Execution and Reinforcement Learning with Verifiable Rewards (RLVR).

## The 6 Layers of Autonomy

1. **Layer 1: Event-Sourced State Store + Durable Workflow Engine**
   - **`events.py`**: Immutable event structures (started, completed, paused, skipped).
   - **`state_store.py`**: SQLite-backed append-only log. Rebuilds state dynamically.
   - **`workflow.py`**: Idempotent executor with exponential backoff. Resumes perfectly after crashes.

2. **Layer 2: Execution Harness + Tool Contracts**
   - **`harness.py`**: Safe subprocess execution sandbox with configurable timeouts.
   - **`contracts.py`**: Strict typed I/O interfaces for tools.

3. **Layer 3: Agent Loop + Self-Correction**
   - **`agent.py`**: The core loop (Analyze -> Patch -> Verify).
   - Feeds test failures back into the LLM context automatically to self-correct.

4. **Layer 4: Observability**
   - **`metrics.py`**: Extracts runtime telemetry (durations, token usage, retry rates).
   - **`inspector.py`**: A CLI tool to "time travel" through the event log for any run.

5. **Layer 5: Self-Evolution via RLVR**
   - **`rewards.py`**: Computes objective scores (+10 for passing tests, -1 per correction attempt).
   - **`evolution.py`**: Uses the LLM to mutate and improve instructions that yield poor rewards.
   - **`skills.py`**: The database of evolved prompt instructions.

6. **Layer 6: Durable Autonomy**
   - **`autonomy.py`**: Heuristics for Novelty and Uncertainty.
   - Seamlessly pauses the workflow engine when confidence is low, escalating to a human, 
     then resumes right where it left off once approved.

## How to Run

1. **Durability Demo (Layer 1)**: `python3 demos/demo_durability.py`
2. **Self-Correction Demo (Layer 3)**: `python3 demos/demo_agent_loop.py`
3. **Observability CLI (Layer 4)**: `python3 duraagent/inspector.py`
4. **Evolution / RLVR Demo (Layer 5)**: `python3 demos/demo_evolution.py`
5. **End-to-End Escalation Demo (Layer 6)**: `python3 demos/demo_full.py`
6. **Tests**: `pytest tests/`

Built with Python 3.9+ and no complex external orchestrator dependencies — just standard library and an SQLite log.
