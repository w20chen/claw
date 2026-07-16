from __future__ import annotations

from dataclasses import dataclass

from agent_scheduler.contracts.models import ToolBeforeRequest, ToolCompletedEvent
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
    resource_class: str
    operation: str | None


class RealtimeToolMonitor:
    def __init__(self, sampler: ProcessResourceSampler | None = None, max_active: int = 10_000) -> None:
        self.sampler = sampler or ProcessResourceSampler()
        self.max_active = max_active
        self._active: dict[str, _ActiveTool] = {}

    def begin(self, request: ToolBeforeRequest, resource_class: str) -> None:
        key = self._key(request.tool_call_id, request.event_id)
        if len(self._active) >= self.max_active:
            oldest = next(iter(self._active))
            self._active.pop(oldest, None)
        self._active[key] = _ActiveTool(
            request=request,
            snapshot=self.sampler.snapshot(request.resource_scope),
            resource_class=resource_class,
            operation=extract_operation(request),
        )

    def complete(self, completion: ToolCompletedEvent) -> ToolRuntimeSample:
        key = self._key(completion.tool_call_id, completion.event_id)
        active = self._active.pop(key, None)
        if active is None and completion.tool_call_id is not None:
            active = self._pop_by_tool_call_id(completion.tool_call_id)
        if active is None and completion.tool_call_id is None:
            active = self._pop_unique_by_tool_name(completion.tool_name)
        completion_scope = completion.resource_scope
        if completion_scope is None and active is not None:
            completion_scope = active.request.resource_scope
        end = self.sampler.snapshot(completion_scope)
        if active is None:
            start = end
            operation = None
            resource_class = "unknown"
        else:
            start = active.snapshot
            operation = active.operation
            resource_class = active.resource_class
        return ToolRuntimeSample(
            event_id=completion.event_id,
            tool_call_id=completion.tool_call_id,
            tool_name=completion.tool_name,
            operation=operation,
            started_at=start.captured_at,
            ended_at=end.captured_at,
            duration_ms=completion.duration_ms,
            monitor_duration_ms=max(0, int((end.monotonic_s - start.monotonic_s) * 1000)),
            cpu_time_delta_s=_delta_float(start.process_cpu_time_s, end.process_cpu_time_s),
            rss_bytes_before=start.rss_bytes,
            rss_bytes_after=end.rss_bytes,
            read_bytes_delta=_delta_int(start.read_bytes, end.read_bytes),
            write_bytes_delta=_delta_int(start.write_bytes, end.write_bytes),
            ctx_switches_delta=_delta_int(start.ctx_switches, end.ctx_switches),
            resource_class=resource_class,
            target_pid=end.target_pid if end.target_pid is not None else start.target_pid,
            process_count_before=start.process_count,
            process_count_after=end.process_count,
            attribution_status=_attribution_status(start, end),
            monitor_source=end.source if end.available else start.source,
        )

    def active_count(self) -> int:
        return len(self._active)

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
    if start.available and end.available:
        return "pid"
    return "pid-unavailable"
