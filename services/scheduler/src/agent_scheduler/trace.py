from __future__ import annotations

import json
import threading
import time
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_scheduler.contracts.models import ModelEvent, ToolBeforeRequest, ToolCompletedEvent
from agent_scheduler.monitoring.tool_runtime import ToolRuntimeSample


class AgentTestBenchTraceWriter:
    """Trace writer supporting both v5 (legacy) and v6 (span-based) formats.

    Set schema_version=6 to write span_start/span_end pairs.
    Set schema_version=5 for backward-compatible single-line actions.
    """

    def __init__(
        self,
        path: Path,
        *,
        scaffold: str = "openclaw",
        schema_version: int = 5,
    ) -> None:
        self.path = path
        self.scaffold = scaffold
        self.schema_version = schema_version
        self._lock = threading.Lock()
        self._model_starts: dict[str, ModelEvent] = {}
        self._tool_starts: dict[str, ToolBeforeRequest] = {}
        self._recent_proxy_calls: list[dict[str, Any]] = []
        self._seq_counter = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._append(self._metadata_record())

    def record_tool_started(self, event: ToolBeforeRequest) -> None:
        self._tool_starts[_tool_key(event.tool_call_id, event.event_id)] = event

    def record_tool(self, event: ToolCompletedEvent, sample: ToolRuntimeSample) -> None:
        start = self._pop_tool_start(event)
        tool_args = None if start is None else start.raw_params
        ts_start, ts_end = _tool_timestamps(sample, event.duration_ms)

        if self.schema_version >= 6:
            self._record_tool_v6(event, sample, start, tool_args, ts_start, ts_end)
        else:
            self._record_tool_v5(event, sample, start, tool_args, ts_start, ts_end)

    def _record_tool_v5(
        self,
        event: ToolCompletedEvent,
        sample: ToolRuntimeSample,
        start: ToolBeforeRequest | None,
        tool_args: Any,
        ts_start: float,
        ts_end: float,
    ) -> None:
        self._append(
            {
                "type": "action",
                "action_type": "tool_exec",
                "action_id": event.tool_call_id or event.event_id,
                "run_id": event.run_id,
                "session_id": event.session_id,
                "session_key": event.session_key,
                "agent_id": event.agent_id or _agent_id_from_session_key(event.session_key),
                "ts_start": ts_start,
                "ts_end": ts_end,
                "data": {
                    "tool_name": event.tool_name,
                    "tool_args": tool_args,
                    "tool_result": event.raw_result,
                    "duration_ms": float(event.duration_ms),
                    "success": event.succeeded,
                    "error": event.error_type,
                    "resource_usage": _resource_usage(sample),
                    "openclaw_before_event": None if start is None else start.raw_event,
                    "openclaw_after_event": event.raw_event,
                },
            }
        )

    def _record_tool_v6(
        self,
        event: ToolCompletedEvent,
        sample: ToolRuntimeSample,
        start: ToolBeforeRequest | None,
        tool_args: Any,
        ts_start: float,
        ts_end: float,
    ) -> None:
        trace_id = event.run_id or "unknown-run"
        span_id = event.tool_call_id or event.event_id
        parent_span_id = None  # Python sidecar doesn't track LLM span lineage
        run_id = event.run_id
        session_id = event.session_id
        agent_id = event.agent_id or _agent_id_from_session_key(event.session_key)

        self._seq_counter += 1
        seq_no = self._seq_counter

        wall_start_ns = str(int(ts_start * 1_000_000_000))
        wall_end_ns = str(int(ts_end * 1_000_000_000))
        # Monotonic not available in Python sidecar trace; use wall as fallback
        mono_start_ns = wall_start_ns
        mono_end_ns = wall_end_ns
        duration_ns = str(int(max(0, event.duration_ms) * 1_000_000))

        status_code = "ok" if event.succeeded else ("error" if event.error_type else "unknown")

        scope = start.resource_scope if start is not None else None
        has_pid = scope is not None and scope.pid is not None

        # span_start (written retroactively, so time_quality is "derived")
        self._append({
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
            "input": {
                "requested_args": tool_args,
            },
            "execution": {
                "mode": "launcher" if event.execution_id else "in_process_or_runtime_managed",
                "execution_id": event.execution_id,
            },
        })

        # span_end
        self._append({
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
            "status": {
                "code": status_code,
                "message": event.error_type,
            },
            "output": {
                "exit_code": 0 if event.succeeded else None,
                "result": event.raw_result,
            },
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

        if self.schema_version >= 6:
            self._record_model_v6(event, start, ts_start, ts_end, proxy_data)
        else:
            self._record_model_v5(event, start, ts_start, ts_end, proxy_data)

    def _record_model_v5(
        self,
        event: ModelEvent,
        start: ModelEvent | None,
        ts_start: float,
        ts_end: float,
        proxy_data: dict[str, Any],
    ) -> None:
        self._append(
            {
                "type": "action",
                "action_type": "llm_call",
                "action_id": event.call_id or event.event_id,
                "run_id": event.run_id,
                "session_id": event.session_id,
                "session_key": event.session_key,
                "agent_id": event.agent_id or _agent_id_from_session_key(event.session_key),
                "ts_start": ts_start,
                "ts_end": ts_end,
                "data": {
                    "provider": event.provider,
                    "model": event.model,
                    "messages_in": _first_present(
                        None if start is None else start.raw_input,
                        proxy_data.get("messages_in"),
                    ),
                    "content": _first_present(event.raw_output, proxy_data.get("content")),
                    "duration_ms": event.duration_ms,
                    "llm_latency_ms": (
                        float(event.duration_ms) if event.duration_ms is not None else None
                    ),
                    "outcome": event.outcome,
                    "context_token_budget": event.context_token_budget,
                    "openclaw_started_event": None if start is None else start.raw_event,
                    "openclaw_ended_event": event.raw_event,
                    "raw_request": proxy_data.get("raw_request"),
                    "raw_response": proxy_data.get("raw_response"),
                    "proxy": proxy_data.get("proxy"),
                },
            }
        )

    def _record_model_v6(
        self,
        event: ModelEvent,
        start: ModelEvent | None,
        ts_start: float,
        ts_end: float,
        proxy_data: dict[str, Any],
    ) -> None:
        trace_id = event.run_id or "unknown-run"
        span_id = event.call_id or event.event_id
        run_id = event.run_id
        session_id = event.session_id
        agent_id = event.agent_id or _agent_id_from_session_key(event.session_key)

        self._seq_counter += 1
        seq_no = self._seq_counter

        wall_start_ns = str(int(ts_start * 1_000_000_000))
        wall_end_ns = str(int(ts_end * 1_000_000_000))
        duration_ns = str(int(max(0, event.duration_ms or 0) * 1_000_000))

        status_code = "ok" if event.outcome in ("completed", "ok", "success") else ("error" if event.outcome == "error" else "unknown")

        # Don't duplicate messages_in (v6 stores in input.messages only)
        messages = _first_present(
            None if start is None else start.raw_input,
            proxy_data.get("messages_in"),
        )

        self._append({
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
            "input": {
                "requested_args": None,
                "messages": messages,
            },
            "execution": {
                "mode": None,
                "execution_id": None,
            },
        })

        self._append({
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
            "status": {
                "code": status_code,
                "message": None,
            },
            "output": {
                "content": event.raw_output,
            },
            "execution": {
                "mode": None,
                "execution_id": None,
            },
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
                "proxy": {
                    "status_code": status_code,
                    "stream": stream,
                    "error": error,
                },
                "openclaw_started_event": None,
                "openclaw_ended_event": None,
                "raw_request": raw_request,
                "raw_response": raw_response,
            },
        }
        self._remember_proxy_call(record)

    def _append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                if record.get("type") != "trace_metadata" and self.path.stat().st_size == 0:
                    metadata = json.dumps(
                        self._metadata_record(),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    fh.write(metadata + "\n")
                fh.write(line + "\n")

    def _metadata_record(self) -> dict[str, Any]:
        if self.schema_version >= 6:
            return {
                "schema_version": 6,
                "record_type": "trace_metadata",
                "trace_format_version": 6,
                "scaffold": self.scaffold,
                "mode": "collect",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        return {
            "type": "trace_metadata",
            "trace_format_version": 5,
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


def _resource_usage(sample: ToolRuntimeSample) -> dict[str, Any]:
    return {
        "attribution_status": sample.attribution_status,
        "monitor_source": sample.monitor_source,
        "sampling_interval_ms": sample.sampling_interval_ms,
        "sampling_point_count": sample.sampling_point_count,
        "sampling_quality": sample.sampling_quality,
        "cpu_time_delta_s": sample.cpu_time_delta_s,
        "cpu_utilization_avg_cores": sample.cpu_utilization_avg_cores,
        "cpu_utilization_avg_pct": sample.cpu_utilization_avg_pct,
        "memory_rss_bytes_before": sample.rss_bytes_before,
        "memory_rss_bytes_after": sample.rss_bytes_after,
        "memory_rss_bytes_peak": sample.rss_bytes_peak,
        "memory_footprint_bytes": sample.rss_bytes_peak,
        "disk_read_bytes_delta": sample.read_bytes_delta,
        "disk_write_bytes_delta": sample.write_bytes_delta,
        "disk_read_bytes_per_s": sample.disk_read_bytes_per_s,
        "disk_write_bytes_per_s": sample.disk_write_bytes_per_s,
        "net_rx_bytes_delta": sample.net_rx_bytes_delta,
        "net_tx_bytes_delta": sample.net_tx_bytes_delta,
        "net_rx_bytes_per_s": sample.net_rx_bytes_per_s,
        "net_tx_bytes_per_s": sample.net_tx_bytes_per_s,
        "context_switches_delta": sample.ctx_switches_delta,
        "target_pid": sample.target_pid,
        "process_count_before": sample.process_count_before,
        "process_count_after": sample.process_count_after,
        "timeline_truncated": sample.resource_timeline_truncated,
        "timeline": sample.resource_timeline,
    }


def _v6_attribution(sample: ToolRuntimeSample) -> str:
    """Map legacy attribution_status to v6 AttributionStatus."""
    mapping = {
        "pid": "attributed",
        "cgroup-v2": "attributed",
        "unattributed": "unattributed",
        "pid-unavailable": "failed",
    }
    return mapping.get(sample.attribution_status, "unknown")
