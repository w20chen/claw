from __future__ import annotations

import json
import re
import threading
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_scheduler.contracts.models import ModelEvent, ToolBeforeRequest, ToolCompletedEvent
from agent_scheduler.monitoring.tool_runtime import ToolRuntimeSample


def _safe_filename(segment: str | None) -> str:
    if not segment:
        return "unknown"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", segment)[:64]


class AgentTestBenchTraceWriter:
    """Per-run trace writer. Creates one JSONL file per run under trace_dir.

    Files are named: {agent_id}_{session_id}_{run_id}.jsonl
    """

    def __init__(self, trace_dir: Path, *, scaffold: str = "openclaw") -> None:
        self.trace_dir = trace_dir
        self.scaffold = scaffold
        self._instance_id = str(uuid4())
        self._lock = threading.Lock()
        self._model_starts: dict[str, ModelEvent] = {}
        self._tool_starts: dict[str, ToolBeforeRequest] = {}
        self._recent_proxy_calls: list[dict[str, Any]] = []
        self._seq_counters: dict[str, int] = {}
        self._files: dict[str, Path] = {}
        self._metadata_written: set[str] = set()  # track files that already have metadata
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def _file_for_run(self, run_id: str | None, session_id: str | None, agent_id: str | None) -> Path | None:
        """Return the trace file for a run.

        Keys writers by run_id (primary) or session_id (fallback).
        Uses instance_id only as a last-resort key to prevent data loss,
        but logs a warning since it can cause cross-run accumulation.

        Returns None when no identifiable key is available at all.
        """
        key = run_id or session_id
        if not key:
            # Last resort: instance_id. Log a warning so operators
            # can detect when the plugin isn't sending run_id/session_id.
            import logging
            _log = logging.getLogger(__name__)
            _log.warning(
                "trace: no run_id or session_id, falling back to instance_id "
                "(may cause cross-run accumulation). run_id=%s session_id=%s agent_id=%s",
                run_id, session_id, agent_id,
            )
            key = self._instance_id
        if key in self._files:
            return self._files[key]
        agent = _safe_filename(agent_id)
        session = _safe_filename(session_id)
        run = _safe_filename(run_id)
        filename = f"{agent}_{session}_{run}.jsonl"
        filepath = self.trace_dir / filename
        self._files[key] = filepath
        return filepath

    def _next_seq(self, run_id: str | None) -> int:
        key = run_id or self._instance_id
        current = self._seq_counters.get(key, 0)
        current += 1
        self._seq_counters[key] = current
        return current

    def record_tool_started(self, event: ToolBeforeRequest) -> None:
        self._tool_starts[_tool_key(event.tool_call_id, event.event_id)] = event

    def record_tool(self, event: ToolCompletedEvent, sample: ToolRuntimeSample) -> None:
        start = self._pop_tool_start(event)
        tool_args = None if start is None else start.raw_params
        ts_start, ts_end = _tool_timestamps(sample, event.duration_ms)
        self._record_tool_v6(event, sample, start, tool_args, ts_start, ts_end)

    def _record_tool_v6(
        self,
        event: ToolCompletedEvent,
        sample: ToolRuntimeSample,
        start: ToolBeforeRequest | None,
        tool_args: Any,
        ts_start: float,
        ts_end: float,
    ) -> None:
        trace_id = event.run_id or self._instance_id
        span_id = event.tool_call_id or event.event_id
        parent_span_id = None
        run_id = event.run_id
        session_id = event.session_id
        agent_id = event.agent_id or _agent_id_from_session_key(event.session_key)

        seq_no = self._next_seq(run_id)

        wall_start_ns = str(int(ts_start * 1_000_000_000))
        wall_end_ns = str(int(ts_end * 1_000_000_000))
        mono_start_ns = wall_start_ns
        mono_end_ns = wall_end_ns
        duration_ns = str(int(max(0, event.duration_ms) * 1_000_000))

        status_code = "ok" if event.succeeded else ("error" if event.error_type else "unknown")

        scope = start.resource_scope if start is not None else None
        has_pid = scope is not None and scope.pid is not None

        filepath = self._file_for_run(run_id, session_id, agent_id)
        self._ensure_metadata(filepath)

        # span_start
        self._append(filepath, {
            "schema_version": 6,
            "record_type": "span_start",
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "session_id": session_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "sequence_no": seq_no,
            "kind": "tool",
            "name": event.tool_name,
            "wall_time_ns": wall_start_ns,
            "monotonic_time_ns": mono_start_ns,
            "input": {"requested_args": tool_args},
            "execution": {
                "mode": "launcher" if event.execution_id else "in_process_or_runtime_managed",
                "execution_id": event.execution_id,
            },
        })

        # span_end
        self._append(filepath, {
            "schema_version": 6,
            "record_type": "span_end",
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "session_id": session_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "sequence_no": seq_no,
            "kind": "tool",
            "name": event.tool_name,
            "wall_time_ns": wall_end_ns,
            "monotonic_time_ns": mono_end_ns,
            "duration_ns": duration_ns,
            "status": {"code": status_code, "message": event.error_type},
            "output": {"exit_code": 0 if event.succeeded else None, "result": event.raw_result},
            "execution": {
                "mode": "launcher" if event.execution_id else "in_process_or_runtime_managed",
                "execution_id": event.execution_id,
                "payload_pid": scope.pid if scope is not None else None,
                "payload_pid_start_time_ticks": scope.root_starttime_ticks if scope is not None else None,
                "cgroup_path": scope.cgroup_path if scope is not None else None,
                "pid_role": "payload_root" if has_pid else None,
            },
            "resources": {
                "attribution_status": _v6_attribution(sample),
                "scope": "cgroup" if (scope is not None and scope.cgroup_path) else ("process_tree" if has_pid else "none"),
                "quality": "unknown" if sample.sampling_quality == "unknown" else "partial",
                "monitor_start_wall_time_ns": None,
                "monitor_end_wall_time_ns": None,
                "monitor_start_monotonic_ns": None,
                "monitor_end_monotonic_ns": None,
                "coverage_duration_ns": None,
                "action_duration_ns": duration_ns,
                "coverage_ratio": None,
                "coverage_reason": "full_window" if has_pid else "pid_unavailable",
                "cpu_time_s": sample.cpu_time_delta_s,
                "rss_peak_bytes": sample.rss_bytes_peak,
            },
        })

    def record_model(self, event: ModelEvent) -> None:
        key = event.call_id or event.event_id
        if event.event_type == "model_call_started":
            self._model_starts[key] = event
            return
        start = self._model_starts.pop(key, None)
        proxy_call = self._pop_recent_proxy_call(event)
        ts_end = _parse_timestamp(event.occurred_at)
        duration_s = (event.duration_ms or 0) / 1000
        ts_start = _parse_timestamp(start.occurred_at) if start is not None else ts_end - duration_s
        proxy_data = proxy_call.get("data", {}) if isinstance(proxy_call, dict) else {}
        self._record_model_v6(event, start, ts_start, ts_end, proxy_data)

    def _record_model_v6(
        self,
        event: ModelEvent,
        start: ModelEvent | None,
        ts_start: float,
        ts_end: float,
        proxy_data: dict[str, Any],
    ) -> None:
        trace_id = event.run_id or self._instance_id
        span_id = event.call_id or event.event_id
        run_id = event.run_id
        session_id = event.session_id
        agent_id = event.agent_id or _agent_id_from_session_key(event.session_key)

        seq_no = self._next_seq(run_id)

        wall_start_ns = str(int(ts_start * 1_000_000_000))
        wall_end_ns = str(int(ts_end * 1_000_000_000))
        duration_ns = str(int(max(0, event.duration_ms or 0) * 1_000_000))

        status_code = "ok" if event.outcome in ("completed", "ok", "success") else ("error" if event.outcome == "error" else "unknown")

        messages = _first_present(
            None if start is None else start.raw_input,
            proxy_data.get("messages_in"),
        )

        filepath = self._file_for_run(run_id, session_id, agent_id)
        self._ensure_metadata(filepath)

        self._append(filepath, {
            "schema_version": 6,
            "record_type": "span_start",
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": None,
            "session_id": session_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "sequence_no": seq_no,
            "kind": "llm",
            "name": event.model or "unknown-model",
            "wall_time_ns": wall_start_ns,
            "monotonic_time_ns": wall_start_ns,
            "input": {"requested_args": None, "messages": messages},
            "execution": {"mode": None, "execution_id": None},
        })

        self._append(filepath, {
            "schema_version": 6,
            "record_type": "span_end",
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": None,
            "session_id": session_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "sequence_no": seq_no,
            "kind": "llm",
            "name": event.model or "unknown-model",
            "wall_time_ns": wall_end_ns,
            "monotonic_time_ns": wall_end_ns,
            "duration_ns": duration_ns,
            "status": {"code": status_code, "message": None},
            "output": {"content": event.raw_output},
            "execution": {"mode": None, "execution_id": None},
            "resources": {
                "attribution_status": "not_applicable",
                "scope": "none",
                "quality": "unknown",
                "monitor_start_wall_time_ns": None,
                "monitor_end_wall_time_ns": None,
                "monitor_start_monotonic_ns": None,
                "monitor_end_monotonic_ns": None,
                "coverage_duration_ns": None,
                "action_duration_ns": duration_ns,
                "coverage_ratio": None,
                "coverage_reason": "pid_unavailable",
            },
        })

    def record_llm_proxy_call(
        self,
        *,
        action_id: str | None,
        provider: str | None,
        model: str | None,
        messages_in: Any | None,
        content: Any | None,
        raw_request: Any | None,
        raw_response: Any | None,
        ts_start: float,
        ts_end: float,
        status_code: int,
        stream: bool,
        error: str | None = None,
    ) -> None:
        duration_ms = max(0.0, (ts_end - ts_start) * 1000)
        record = {
            "type": "action",
            "action_type": "llm_call",
            "action_id": action_id or f"llm-proxy-{uuid4()}",
            "run_id": None,
            "session_id": None,
            "session_key": None,
            "agent_id": None,
            "ts_start": ts_start,
            "ts_end": ts_end,
            "data": {
                "provider": provider,
                "model": model,
                "messages_in": messages_in,
                "content": content,
                "duration_ms": int(duration_ms),
                "llm_latency_ms": duration_ms,
                "outcome": "error" if error else "completed",
                "context_token_budget": None,
                "proxy": {"status_code": status_code, "stream": stream, "error": error},
                "openclaw_started_event": None,
                "openclaw_ended_event": None,
                "raw_request": raw_request,
                "raw_response": raw_response,
            },
        }
        self._remember_proxy_call(record)

    def _ensure_metadata(self, filepath: Path) -> None:
        """Write metadata once per file. Never truncates existing data."""
        key = str(filepath)
        if key in self._metadata_written:
            return
        self._metadata_written.add(key)
        self._append(filepath, self._metadata_record())

    def _append(self, filepath: Path, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self._lock:
            with filepath.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def _metadata_record(self) -> dict[str, Any]:
        return {
            "schema_version": 6,
            "record_type": "trace_metadata",
            "trace_format_version": 6,
            "scaffold": self.scaffold,
            "mode": "collect",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _pop_tool_start(self, event: ToolCompletedEvent) -> ToolBeforeRequest | None:
        start = self._tool_starts.pop(_tool_key(event.tool_call_id, event.event_id), None)
        if start is not None or event.tool_call_id is not None:
            return start
        matches = [
            (key, value)
            for key, value in self._tool_starts.items()
            if value.tool_name == event.tool_name
        ]
        if len(matches) != 1:
            return None
        key, value = matches[0]
        self._tool_starts.pop(key, None)
        return value

    def _remember_proxy_call(self, record: dict[str, Any]) -> None:
        self._recent_proxy_calls.append(record)
        if len(self._recent_proxy_calls) > 32:
            del self._recent_proxy_calls[:-32]

    def _pop_recent_proxy_call(self, event: ModelEvent) -> dict[str, Any] | None:
        event_ts = _parse_timestamp(event.occurred_at)
        candidates: list[tuple[int, dict[str, Any]]] = []
        for index, record in enumerate(self._recent_proxy_calls):
            data = record.get("data") if isinstance(record.get("data"), dict) else {}
            if event.model is not None and data.get("model") != event.model:
                continue
            ts_end = record.get("ts_end")
            try:
                delta = abs(event_ts - float(ts_end))
            except (TypeError, ValueError):
                continue
            if delta <= 10:
                candidates.append((index, record))
        if not candidates:
            return None
        index, record = candidates[-1]
        self._recent_proxy_calls.pop(index)
        return record


def _parse_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


def _tool_timestamps(sample: ToolRuntimeSample, duration_ms: int) -> tuple[float, float]:
    ts_start = sample.started_at
    ts_end = sample.ended_at
    duration_s = max(0.0, duration_ms / 1000)
    if ts_end < ts_start:
        ts_end = ts_start
    if duration_s > 0 and ts_end - ts_start < duration_s:
        ts_start = ts_end - duration_s
    return ts_start, ts_end


def _tool_key(tool_call_id: str | None, event_id: str) -> str:
    return tool_call_id or event_id


def _agent_id_from_session_key(value: str | None) -> str | None:
    if value is None:
        return None
    parts = value.split(":")
    if len(parts) >= 2 and parts[0] == "agent" and parts[1]:
        return parts[1]
    return None


def _first_present(*values: Any) -> Any | None:
    for value in values:
        if value is not None:
            return value
    return None


def _v6_attribution(sample: ToolRuntimeSample) -> str:
    """Map legacy attribution_status to v6 AttributionStatus."""
    mapping = {
        "pid": "attributed",
        "cgroup-v2": "attributed",
        "unattributed": "unattributed",
        "pid-unavailable": "failed",
    }
    return mapping.get(sample.attribution_status, "unknown")
