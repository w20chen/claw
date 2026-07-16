from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from agent_scheduler.contracts.models import ResourceScope, ToolBeforeRequest, ToolCompletedEvent
from agent_scheduler.monitoring.process import ProcessResourceSampler, ResourceSnapshot
from agent_scheduler.predictors.static_profile import extract_operation


@dataclass(frozen=True)
class ToolRuntimeSample:
    event_id: str
    tool_call_id: str | None
    tool_name: str
    operation: str | None
    started_at: float
    ended_at: float
    duration_ms: int
    monitor_duration_ms: int
    cpu_time_delta_s: float | None
    rss_bytes_before: int | None
    rss_bytes_after: int | None
    read_bytes_delta: int | None
    write_bytes_delta: int | None
    net_rx_bytes_delta: int | None
    net_tx_bytes_delta: int | None
    ctx_switches_delta: int | None
    resource_class: str
    target_pid: int | None
    process_count_before: int | None
    process_count_after: int | None
    attribution_status: str
    monitor_source: str


@dataclass(frozen=True)
class _ActiveTool:
    request: ToolBeforeRequest
    snapshot: ResourceSnapshot
    latest_snapshot: ResourceSnapshot
    resource_class: str
    operation: str | None


class RealtimeToolMonitor:
    def __init__(
        self,
        sampler: ProcessResourceSampler | None = None,
        max_active: int = 10_000,
        poll_interval_s: float = 0.1,
    ) -> None:
        self.sampler = sampler or ProcessResourceSampler()
        self.max_active = max_active
        self.poll_interval_s = poll_interval_s
        self._active: dict[str, _ActiveTool] = {}
        self._lock = threading.RLock()
        self._poller = threading.Thread(target=self._poll_active, daemon=True)
        self._poller.start()

    def begin(self, request: ToolBeforeRequest, resource_class: str) -> None:
        key = self._key(request.tool_call_id, request.event_id)
        snapshot = self.sampler.snapshot(request.resource_scope)
        with self._lock:
            if len(self._active) >= self.max_active:
                oldest = next(iter(self._active))
                self._active.pop(oldest, None)
            self._active[key] = _ActiveTool(
                request=request,
                snapshot=snapshot,
                latest_snapshot=snapshot,
                resource_class=resource_class,
                operation=extract_operation(request),
            )

    def complete(self, completion: ToolCompletedEvent) -> ToolRuntimeSample:
        key = self._key(completion.tool_call_id, completion.event_id)
        with self._lock:
            active = self._active.pop(key, None)
            if active is None and completion.tool_call_id is not None:
                active = self._pop_by_tool_call_id(completion.tool_call_id)
            if active is None and completion.tool_call_id is None:
                active = self._pop_unique_by_tool_name(completion.tool_name)
        completion_scope = completion.resource_scope
        if completion_scope is None and active is not None:
            completion_scope = active.request.resource_scope
        end = self.sampler.snapshot(completion_scope)
        if active is not None and not end.available and active.latest_snapshot.available:
            end = active.latest_snapshot
        if active is None:
            start = end
            operation = None
            resource_class = "unknown"
        else:
            start = active.snapshot
            operation = active.operation
            resource_class = active.resource_class
        wall_started_at, wall_ended_at = _wall_times_from_duration(
            start.captured_at,
            end.captured_at,
            completion.duration_ms,
        )
        return ToolRuntimeSample(
            event_id=completion.event_id,
            tool_call_id=completion.tool_call_id,
            tool_name=completion.tool_name,
            operation=operation,
            started_at=wall_started_at,
            ended_at=wall_ended_at,
            duration_ms=completion.duration_ms,
            monitor_duration_ms=max(0, int((end.monotonic_s - start.monotonic_s) * 1000)),
            cpu_time_delta_s=_delta_float(start.process_cpu_time_s, end.process_cpu_time_s),
            rss_bytes_before=start.rss_bytes,
            rss_bytes_after=end.rss_bytes,
            read_bytes_delta=_delta_int(start.read_bytes, end.read_bytes),
            write_bytes_delta=_delta_int(start.write_bytes, end.write_bytes),
            net_rx_bytes_delta=_delta_int(start.net_rx_bytes, end.net_rx_bytes),
            net_tx_bytes_delta=_delta_int(start.net_tx_bytes, end.net_tx_bytes),
            ctx_switches_delta=_delta_int(start.ctx_switches, end.ctx_switches),
            resource_class=resource_class,
            target_pid=end.target_pid if end.target_pid is not None else start.target_pid,
            process_count_before=start.process_count,
            process_count_after=end.process_count,
            attribution_status=_attribution_status(start, end),
            monitor_source=end.source if end.available else start.source,
        )

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def bind_scope(self, tool_call_id: str | None, scope: ResourceScope) -> None:
        if tool_call_id is None:
            return
        with self._lock:
            active = self._pop_by_tool_call_id(tool_call_id)
            if active is None:
                return
            request = active.request.model_copy(update={"resource_scope": scope})
            snapshot = self.sampler.snapshot(request.resource_scope)
            self._active[self._key(request.tool_call_id, request.event_id)] = _ActiveTool(
                request=request,
                snapshot=snapshot,
                latest_snapshot=snapshot,
                resource_class=active.resource_class,
                operation=active.operation,
            )

    def _pop_by_tool_call_id(self, tool_call_id: str) -> _ActiveTool | None:
        for key, active in list(self._active.items()):
            if active.request.tool_call_id == tool_call_id:
                self._active.pop(key, None)
                return active
        return None

    def _pop_unique_by_tool_name(self, tool_name: str) -> _ActiveTool | None:
        matches = [(key, active) for key, active in self._active.items() if active.request.tool_name == tool_name]
        if len(matches) != 1:
            return None
        key, active = matches[0]
        self._active.pop(key, None)
        return active

    def _poll_active(self) -> None:
        while True:
            time.sleep(self.poll_interval_s)
            with self._lock:
                items = list(self._active.items())
            for key, active in items:
                if active.request.resource_scope is None:
                    continue
                snapshot = self.sampler.snapshot(active.request.resource_scope)
                if not snapshot.available:
                    continue
                with self._lock:
                    current = self._active.get(key)
                    if current is not active:
                        continue
                    self._active[key] = _ActiveTool(
                        request=active.request,
                        snapshot=active.snapshot,
                        latest_snapshot=snapshot,
                        resource_class=active.resource_class,
                        operation=active.operation,
                    )

    @staticmethod
    def _key(tool_call_id: str | None, event_id: str) -> str:
        return tool_call_id or event_id


def _delta_int(start: int | None, end: int | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, end - start)


def _delta_float(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, end - start)


def _attribution_status(start: ResourceSnapshot, end: ResourceSnapshot) -> str:
    if start.target_pid is None and end.target_pid is None:
        return "unattributed"
    if start.source == "cgroup-v2" or end.source == "cgroup-v2":
        return "cgroup-v2"
    if start.available and end.available:
        return "pid"
    return "pid-unavailable"


def _wall_times_from_duration(started_at: float, ended_at: float, duration_ms: int) -> tuple[float, float]:
    duration_s = max(0.0, duration_ms / 1000)
    if duration_s <= 0:
        return started_at, ended_at
    if ended_at < started_at:
        ended_at = started_at
    if ended_at - started_at < duration_s:
        started_at = ended_at - duration_s
    return started_at, ended_at
