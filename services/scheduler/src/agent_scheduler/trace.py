from __future__ import annotations

import json
import threading
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_scheduler.contracts.models import ModelEvent, ToolBeforeRequest, ToolCompletedEvent
from agent_scheduler.monitoring.tool_runtime import ToolRuntimeSample


class AgentTestBenchTraceWriter:
    def __init__(self, path: Path, *, scaffold: str = "openclaw") -> None:
        self.path = path
        self.scaffold = scaffold
        self._lock = threading.Lock()
        self._model_starts: dict[str, ModelEvent] = {}
        self._tool_starts: dict[str, ToolBeforeRequest] = {}
        self._recent_proxy_calls: list[dict[str, Any]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._append(self._metadata_record())

    def record_tool_started(self, event: ToolBeforeRequest) -> None:
        self._tool_starts[_tool_key(event.tool_call_id, event.event_id)] = event

    def record_tool(self, event: ToolCompletedEvent, sample: ToolRuntimeSample) -> None:
        start = self._pop_tool_start(event)
        tool_args = None if start is None else start.raw_params
        ts_start, ts_end = _tool_timestamps(sample, event.duration_ms)
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
        self._append(record)

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
