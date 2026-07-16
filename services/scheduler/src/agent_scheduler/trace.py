from __future__ import annotations

import json
import threading
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._append(
                {
                    "type": "trace_metadata",
                    "trace_format_version": 5,
                    "scaffold": scaffold,
                    "mode": "collect",
                    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            )

    def record_tool_started(self, event: ToolBeforeRequest) -> None:
        self._tool_starts[_tool_key(event.tool_call_id, event.event_id)] = event

    def record_tool(self, event: ToolCompletedEvent, sample: ToolRuntimeSample) -> None:
        start = self._pop_tool_start(event)
        tool_args = None if start is None else start.raw_params
        self._append(
            {
                "type": "action",
                "action_type": "tool_exec",
                "action_id": event.tool_call_id or event.event_id,
                "agent_id": event.agent_id,
                "ts_start": sample.started_at,
                "ts_end": sample.ended_at,
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
        ts_end = _parse_timestamp(event.occurred_at)
        duration_s = (event.duration_ms or 0) / 1000
        ts_start = _parse_timestamp(start.occurred_at) if start is not None else ts_end - duration_s
        self._append(
            {
                "type": "action",
                "action_type": "llm_call",
                "action_id": event.call_id or event.event_id,
                "agent_id": event.agent_id,
                "ts_start": ts_start,
                "ts_end": ts_end,
                "data": {
                    "provider": event.provider,
                    "model": event.model,
                    "messages_in": None if start is None else start.raw_input,
                    "content": event.raw_output,
                    "duration_ms": event.duration_ms,
                    "llm_latency_ms": (
                        float(event.duration_ms) if event.duration_ms is not None else None
                    ),
                    "outcome": event.outcome,
                    "context_token_budget": event.context_token_budget,
                    "openclaw_started_event": None if start is None else start.raw_event,
                    "openclaw_ended_event": event.raw_event,
                },
            }
        )

    def _append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

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


def _parse_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


def _tool_key(tool_call_id: str | None, event_id: str) -> str:
    return tool_call_id or event_id


def _resource_usage(sample: ToolRuntimeSample) -> dict[str, Any]:
    memory_values = [
        value
        for value in (sample.rss_bytes_before, sample.rss_bytes_after)
        if value is not None
    ]
    return {
        "attribution_status": sample.attribution_status,
        "monitor_source": sample.monitor_source,
        "cpu_time_delta_s": sample.cpu_time_delta_s,
        "memory_rss_bytes_before": sample.rss_bytes_before,
        "memory_rss_bytes_after": sample.rss_bytes_after,
        "memory_footprint_bytes": max(memory_values) if memory_values else None,
        "disk_read_bytes_delta": sample.read_bytes_delta,
        "disk_write_bytes_delta": sample.write_bytes_delta,
        "net_rx_bytes_delta": sample.net_rx_bytes_delta,
        "net_tx_bytes_delta": sample.net_tx_bytes_delta,
        "context_switches_delta": sample.ctx_switches_delta,
        "target_pid": sample.target_pid,
        "process_count_before": sample.process_count_before,
        "process_count_after": sample.process_count_after,
    }
