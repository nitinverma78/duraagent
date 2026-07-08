"""
Event-sourced state store for DuraAgent.

This module implements the core durability guarantee:
- Events are appended to an immutable log (SQLite `events` table)
- Materialized views (`workflow_state`, `step_state`) are derived projections
- Views can be rebuilt at any time by replaying the event log
- The event log is the ONLY source of truth

Design decisions:
- SQLite over Postgres: zero-dependency, single inspectable file, perfect for demos.
  In production, swap to Postgres with the same interface.
- Materialized views over event replay: we maintain views for fast reads,
  but can always rebuild them from the log (proving the log is authoritative).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from duraagent.events import (
    Event,
    EventType,
    StepStatus,
    WorkflowStatus,
)


from abc import ABC, abstractmethod

class AbstractStateStore(ABC):
    """Abstract Base Class for the event-sourced state store."""
    
    @abstractmethod
    def append_event(self, event: Event) -> None:
        pass

    @abstractmethod
    def get_events(self, run_id: str) -> list[Event]:
        pass

    @abstractmethod
    def get_workflow_state(self, run_id: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def get_step_state(self, run_id: str, step_name: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def get_last_completed_step_index(self, run_id: str) -> int:
        pass


class SQLiteStateStore(AbstractStateStore):
    """
    SQLite-backed event-sourced state store.

    Three tables:
    - `events`:          Append-only immutable event log (source of truth)
    - `workflow_state`:  Materialized view of workflow status (derived)
    - `step_state`:      Materialized view of step status (derived)
    """

    def __init__(self, db_path: str | Path = "duraagent.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript(
                """
                -- The immutable event log. NEVER UPDATE or DELETE rows here.
                CREATE TABLE IF NOT EXISTS events (
                    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id    TEXT UNIQUE NOT NULL,
                    run_id      TEXT NOT NULL,
                    event_type  TEXT NOT NULL,
                    timestamp   TEXT NOT NULL,
                    payload     TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

                -- Materialized view: current workflow status.
                -- Rebuilt by replaying events.
                CREATE TABLE IF NOT EXISTS workflow_state (
                    run_id          TEXT PRIMARY KEY,
                    workflow_name   TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'running',
                    config          TEXT NOT NULL DEFAULT '{}',
                    created_at      TEXT NOT NULL DEFAULT '',
                    updated_at      TEXT NOT NULL DEFAULT '',
                    last_step_index INTEGER NOT NULL DEFAULT -1
                );

                -- Materialized view: current step status.
                -- Rebuilt by replaying events.
                CREATE TABLE IF NOT EXISTS step_state (
                    run_id      TEXT NOT NULL,
                    step_name   TEXT NOT NULL,
                    step_index  INTEGER NOT NULL DEFAULT 0,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    input_data  TEXT NOT NULL DEFAULT '{}',
                    output_data TEXT NOT NULL DEFAULT '{}',
                    error       TEXT NOT NULL DEFAULT '',
                    attempt     INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0.0,
                    started_at  TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (run_id, step_name)
                );

                -- Cross-run memory (persistent knowledge).
                CREATE TABLE IF NOT EXISTS memory (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_key    TEXT NOT NULL,
                    fact        TEXT NOT NULL,
                    source_run  TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL DEFAULT '',
                    UNIQUE(repo_key, fact)
                );

                -- Signals for external intervention in running/paused workflows.
                CREATE TABLE IF NOT EXISTS signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT NOT NULL,
                    signal_name TEXT NOT NULL,
                    payload     TEXT NOT NULL DEFAULT '{}',
                    status      TEXT NOT NULL DEFAULT 'pending',
                    created_at  TEXT NOT NULL DEFAULT '',
                    processed_at TEXT
                );
                """
            )

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Event log operations (append-only) ─────────────────────────────

    def append_event(self, event: Event) -> None:
        """
        Append an event to the immutable log AND update materialized views.

        This is the ONLY write path. All state changes go through events.
        """
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (event_id, run_id, event_type, timestamp, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.run_id,
                    event.event_type if isinstance(event.event_type, str) else event.event_type.value,
                    event.timestamp,
                    json.dumps(event.payload, default=str),
                ),
            )
            # Apply event to materialized views
            self._apply_event_to_views(conn, event)

    def get_events(self, run_id: str) -> list[Event]:
        """Replay all events for a run in order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event_id, run_id, event_type, timestamp, payload "
                "FROM events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        return [
            Event(
                event_id=row["event_id"],
                run_id=row["run_id"],
                event_type=row["event_type"],
                timestamp=row["timestamp"],
                payload=json.loads(row["payload"]),
            )
            for row in rows
        ]

    def get_all_runs(self) -> list[dict[str, Any]]:
        """List all workflow runs with their status."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT run_id, workflow_name, status, config, created_at, updated_at, last_step_index "
                "FROM workflow_state ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Materialized view queries (derived state) ──────────────────────

    def get_workflow_state(self, run_id: str) -> dict[str, Any] | None:
        """Get the current materialized state of a workflow run."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT run_id, workflow_name, status, config, created_at, updated_at, last_step_index "
                "FROM workflow_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_step_state(self, run_id: str, step_name: str) -> dict[str, Any] | None:
        """Get the current materialized state of a specific step."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT run_id, step_name, step_index, status, input_data, output_data, "
                "error, attempt, duration_ms, started_at, completed_at "
                "FROM step_state WHERE run_id = ? AND step_name = ?",
                (run_id, step_name),
            ).fetchone()
        return dict(row) if row else None

    def get_all_step_states(self, run_id: str) -> list[dict[str, Any]]:
        """Get all steps for a run, ordered by step index."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT run_id, step_name, step_index, status, input_data, output_data, "
                "error, attempt, duration_ms, started_at, completed_at "
                "FROM step_state WHERE run_id = ? ORDER BY step_index",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_last_completed_step_index(self, run_id: str) -> int:
        """Get the index of the last successfully completed step."""
        state = self.get_workflow_state(run_id)
        return state["last_step_index"] if state else -1

    # ── Memory operations (cross-run knowledge) ───────────────────────

    def store_memory(self, repo_key: str, fact: str, source_run: str = "") -> None:
        """Store a learned fact for a repo. Idempotent (upsert)."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memory (repo_key, fact, source_run, created_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                (repo_key, fact, source_run),
            )

    def get_memories(self, repo_key: str) -> list[dict[str, Any]]:
        """Retrieve all learned facts for a repo."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, repo_key, fact, source_run, created_at FROM memory "
                "WHERE repo_key = ? ORDER BY created_at DESC",
                (repo_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Signal operations (external intervention) ─────────────────────────

    def send_signal(self, run_id: str, signal_name: str, payload: dict[str, Any] | None = None) -> None:
        """Send a signal to a workflow."""
        payload_str = json.dumps(payload or {})
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO signals (run_id, signal_name, payload, created_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                (run_id, signal_name, payload_str),
            )

    def get_pending_signals(self, run_id: str) -> list[dict[str, Any]]:
        """Retrieve and immediately mark signals as processed for a run."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, signal_name, payload FROM signals "
                "WHERE run_id = ? AND status = 'pending' ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            
            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE signals SET status = 'processed', processed_at = datetime('now') "
                    f"WHERE id IN ({placeholders})",
                    ids,
                )
                
        return [
            {"signal_name": row["signal_name"], "payload": json.loads(row["payload"])}
            for row in rows
        ]

    # ── Replay & rebuild (proves events are the source of truth) ──────

    def rebuild_materialized_views(self, run_id: str) -> None:
        """
        Delete and rebuild materialized views by replaying all events.

        This is the key proof that the event log is the source of truth.
        You can call this at any time and get the exact same state.
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM workflow_state WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM step_state WHERE run_id = ?", (run_id,))

        events = self.get_events(run_id)
        for event in events:
            with self._conn() as conn:
                self._apply_event_to_views(conn, event)

    # ── Internal: apply events to materialized views ──────────────────

    def _apply_event_to_views(self, conn: sqlite3.Connection, event: Event) -> None:
        """Apply a single event to materialized views. Called on append."""
        et = event.event_type
        if isinstance(et, EventType):
            et = et.value

        payload = event.payload

        if et == EventType.WORKFLOW_STARTED.value:
            conn.execute(
                "INSERT OR REPLACE INTO workflow_state "
                "(run_id, workflow_name, status, config, created_at, updated_at, last_step_index) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.run_id,
                    payload.get("workflow_name", ""),
                    WorkflowStatus.RUNNING.value,
                    json.dumps(payload.get("config", {})),
                    event.timestamp,
                    event.timestamp,
                    -1,
                ),
            )

        elif et == EventType.WORKFLOW_COMPLETED.value:
            conn.execute(
                "UPDATE workflow_state SET status = ?, updated_at = ? WHERE run_id = ?",
                (WorkflowStatus.COMPLETED.value, event.timestamp, event.run_id),
            )

        elif et == EventType.WORKFLOW_FAILED.value:
            conn.execute(
                "UPDATE workflow_state SET status = ?, updated_at = ? WHERE run_id = ?",
                (WorkflowStatus.FAILED.value, event.timestamp, event.run_id),
            )

        elif et == EventType.WORKFLOW_PAUSED.value:
            conn.execute(
                "UPDATE workflow_state SET status = ?, updated_at = ? WHERE run_id = ?",
                (WorkflowStatus.PAUSED.value, event.timestamp, event.run_id),
            )

        elif et == EventType.WORKFLOW_RESUMED.value:
            conn.execute(
                "UPDATE workflow_state SET status = ?, updated_at = ? WHERE run_id = ?",
                (WorkflowStatus.RUNNING.value, event.timestamp, event.run_id),
            )

        elif et == EventType.STEP_STARTED.value:
            conn.execute(
                "INSERT OR REPLACE INTO step_state "
                "(run_id, step_name, step_index, status, input_data, output_data, "
                "error, attempt, duration_ms, started_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, '{}', '', 0, 0.0, ?, '')",
                (
                    event.run_id,
                    payload["step_name"],
                    payload.get("step_index", 0),
                    StepStatus.RUNNING.value,
                    json.dumps(payload.get("input_data", {})),
                    event.timestamp,
                ),
            )

        elif et == EventType.STEP_COMPLETED.value:
            conn.execute(
                "UPDATE step_state SET status = ?, output_data = ?, duration_ms = ?, "
                "completed_at = ? WHERE run_id = ? AND step_name = ?",
                (
                    StepStatus.COMPLETED.value,
                    json.dumps(payload.get("output_data", {})),
                    payload.get("duration_ms", 0.0),
                    event.timestamp,
                    event.run_id,
                    payload["step_name"],
                ),
            )
            # Update last completed step index
            step_index = payload.get("step_index", 0)
            conn.execute(
                "UPDATE workflow_state SET last_step_index = MAX(last_step_index, ?), "
                "updated_at = ? WHERE run_id = ?",
                (step_index, event.timestamp, event.run_id),
            )

        elif et == EventType.STEP_FAILED.value:
            conn.execute(
                "UPDATE step_state SET status = ?, error = ?, attempt = ? "
                "WHERE run_id = ? AND step_name = ?",
                (
                    StepStatus.FAILED.value,
                    payload.get("error", ""),
                    payload.get("attempt", 0),
                    event.run_id,
                    payload["step_name"],
                ),
            )

        elif et == EventType.STEP_SKIPPED.value:
            conn.execute(
                "INSERT OR REPLACE INTO step_state "
                "(run_id, step_name, step_index, status, input_data, output_data, "
                "error, attempt, duration_ms, started_at, completed_at) "
                "VALUES (?, ?, ?, ?, '{}', '{}', '', 0, 0.0, ?, ?)",
                (
                    event.run_id,
                    payload["step_name"],
                    payload.get("step_index", 0),
                    StepStatus.SKIPPED.value,
                    event.timestamp,
                    event.timestamp,
                ),
            )

        elif et == EventType.MEMORY_STORED.value:
            self.store_memory(
                repo_key=payload.get("key", ""),
                fact=payload.get("fact", ""),
                source_run=event.run_id,
            )
