from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent_scheduler.contracts.models import ModelEvent, ToolBeforeRequest, ToolCompletedEvent, ToolDecision


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_requests (
                event_id TEXT PRIMARY KEY,
                tool_call_id TEXT,
                tool_name TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_decisions (
                decision_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                tool_call_id TEXT,
                lease_id TEXT,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_completions (
                event_id TEXT PRIMARY KEY,
                tool_call_id TEXT,
                decision_id TEXT,
                lease_id TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS model_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration_state (
                key TEXT PRIMARY KEY,
                scale REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def save_request(self, request: ToolBeforeRequest) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO tool_requests(event_id, tool_call_id, tool_name, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (request.event_id, request.tool_call_id, request.tool_name, request.model_dump_json()),
        )
        self.conn.commit()

    def save_decision(self, event_id: str, tool_call_id: str | None, decision: ToolDecision) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO tool_decisions(decision_id, event_id, tool_call_id, lease_id, action, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                event_id,
                tool_call_id,
                decision.lease_id,
                decision.action,
                decision.model_dump_json(),
            ),
        )
        self.conn.commit()

    def save_completion(self, completion: ToolCompletedEvent) -> bool:
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO tool_completions(event_id, tool_call_id, decision_id, lease_id, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                completion.event_id,
                completion.tool_call_id,
                completion.decision_id,
                completion.lease_id,
                completion.model_dump_json(),
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def save_model_event(self, event: ModelEvent) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO model_events(event_id, event_type, payload_json)
            VALUES (?, ?, ?)
            """,
            (event.event_id, event.event_type, event.model_dump_json()),
        )
        self.conn.commit()

    def update_calibration(self, key: str, scale: float, updated_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO calibration_state(key, scale, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET scale = excluded.scale, updated_at = excluded.updated_at
            """,
            (key, scale, updated_at),
        )
        self.conn.commit()

    def get_calibration(self, key: str) -> float | None:
        row = self.conn.execute("SELECT scale FROM calibration_state WHERE key = ?", (key,)).fetchone()
        return float(row["scale"]) if row else None

    def counts(self) -> dict[str, int]:
        tables = ["tool_requests", "tool_decisions", "tool_completions", "model_events"]
        out: dict[str, int] = {}
        for table in tables:
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"])
        return out

    def dump_json(self, value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
