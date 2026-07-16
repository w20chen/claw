from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent_scheduler.contracts.models import ModelEvent, ToolBeforeRequest, ToolCompletedEvent, ToolDecision
from agent_scheduler.monitoring.tool_runtime import ToolRuntimeSample


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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_runtime_samples (
                event_id TEXT PRIMARY KEY,
                tool_call_id TEXT,
                tool_name TEXT NOT NULL,
                operation TEXT,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL,
                duration_ms INTEGER NOT NULL,
                monitor_duration_ms INTEGER NOT NULL,
                cpu_time_delta_s REAL,
                rss_bytes_before INTEGER,
                rss_bytes_after INTEGER,
                read_bytes_delta INTEGER,
                write_bytes_delta INTEGER,
                ctx_switches_delta INTEGER,
                resource_class TEXT NOT NULL,
                target_pid INTEGER,
                process_count_before INTEGER,
                process_count_after INTEGER,
                attribution_status TEXT NOT NULL DEFAULT 'unattributed',
                monitor_source TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._ensure_columns(
            "tool_runtime_samples",
            {
                "target_pid": "INTEGER",
                "process_count_before": "INTEGER",
                "process_count_after": "INTEGER",
                "attribution_status": "TEXT NOT NULL DEFAULT 'unattributed'",
            },
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

    def save_tool_runtime_sample(self, sample: ToolRuntimeSample) -> bool:
        payload_json = self.dump_json(sample.__dict__)
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO tool_runtime_samples(
                event_id, tool_call_id, tool_name, operation, started_at, ended_at,
                duration_ms, monitor_duration_ms, cpu_time_delta_s,
                rss_bytes_before, rss_bytes_after, read_bytes_delta, write_bytes_delta,
                ctx_switches_delta, resource_class, target_pid, process_count_before,
                process_count_after, attribution_status, monitor_source, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample.event_id,
                sample.tool_call_id,
                sample.tool_name,
                sample.operation,
                sample.started_at,
                sample.ended_at,
                sample.duration_ms,
                sample.monitor_duration_ms,
                sample.cpu_time_delta_s,
                sample.rss_bytes_before,
                sample.rss_bytes_after,
                sample.read_bytes_delta,
                sample.write_bytes_delta,
                sample.ctx_switches_delta,
                sample.resource_class,
                sample.target_pid,
                sample.process_count_before,
                sample.process_count_after,
                sample.attribution_status,
                sample.monitor_source,
                payload_json,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def recent_tool_runtime_samples(self, limit: int = 20) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 200))
        rows = self.conn.execute(
            """
            SELECT payload_json
            FROM tool_runtime_samples
            ORDER BY ended_at DESC
            LIMIT ?
            """,
            (capped,),
        ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

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
        tables = [
            "tool_requests",
            "tool_decisions",
            "tool_completions",
            "model_events",
            "tool_runtime_samples",
        ]
        out: dict[str, int] = {}
        for table in tables:
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"])
        return out

    def dump_json(self, value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {
            str(row["name"])
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
