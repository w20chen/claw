from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from agent_scheduler.contracts.models import ResourceScope


@dataclass(frozen=True)
class ResourceSnapshot:
    captured_at: float
    monotonic_s: float
    process_cpu_time_s: float | None
    rss_bytes: int | None
    read_bytes: int | None
    write_bytes: int | None
    ctx_switches: int | None
    target_pid: int | None
    process_count: int | None
    available: bool
    source: str


class ProcessResourceSampler:
    """Best-effort sampler for a target process tree.

    This mirrors the important agent-test-bench invariant: resource samples must
    belong to the agent/tool process tree. If OpenClaw does not provide a PID,
    the result is explicitly unattributed instead of sampling the sidecar.
    """

    def __init__(self) -> None:
        self._psutil = self._load_psutil()

    def snapshot(self, scope: ResourceScope | None = None) -> ResourceSnapshot:
        now = time.time()
        mono = time.monotonic()
        if scope is None or scope.pid is None:
            return self._empty(now, mono, None, "unattributed")
        if self._psutil is None:
            return self._empty(now, mono, scope.pid, "psutil-unavailable")
        try:
            process = self._psutil.Process(scope.pid)
            if scope.process_start_time is not None:
                create_time = float(process.create_time())
                if abs(create_time - scope.process_start_time) > 1.0:
                    return self._empty(now, mono, scope.pid, "pid-reused")
            processes = [process]
            if scope.include_children:
                try:
                    processes.extend(process.children(recursive=True))
                except Exception:
                    pass
            return self._snapshot_processes(now, mono, scope.pid, processes)
        except Exception:
            return self._empty(now, mono, scope.pid, "pid-unavailable")

    def _snapshot_processes(
        self,
        now: float,
        mono: float,
        target_pid: int,
        processes: list[Any],
    ) -> ResourceSnapshot:
        cpu_time = 0.0
        rss_bytes = 0
        read_bytes = 0
        write_bytes = 0
        ctx_switches = 0
        found_cpu = False
        found_memory = False
        found_io = False
        found_ctx = False
        process_count = 0
        for process in processes:
            try:
                cpu = process.cpu_times()
                cpu_time += float(cpu.user + cpu.system)
                found_cpu = True
            except Exception:
                pass
            try:
                rss_bytes += int(process.memory_info().rss)
                found_memory = True
            except Exception:
                pass
            try:
                io = process.io_counters()
                read_bytes += int(getattr(io, "read_bytes", 0))
                write_bytes += int(getattr(io, "write_bytes", 0))
                found_io = True
            except Exception:
                pass
            try:
                ctx = process.num_ctx_switches()
                ctx_switches += int(ctx.voluntary + ctx.involuntary)
                found_ctx = True
            except Exception:
                pass
            process_count += 1
        return ResourceSnapshot(
            captured_at=now,
            monotonic_s=mono,
            process_cpu_time_s=cpu_time if found_cpu else None,
            rss_bytes=rss_bytes if found_memory else None,
            read_bytes=read_bytes if found_io else None,
            write_bytes=write_bytes if found_io else None,
            ctx_switches=ctx_switches if found_ctx else None,
            target_pid=target_pid,
            process_count=process_count,
            available=found_cpu or found_memory or found_io or found_ctx,
            source="psutil-process-tree",
        )

    @staticmethod
    def _empty(now: float, mono: float, target_pid: int | None, source: str) -> ResourceSnapshot:
        return ResourceSnapshot(
            captured_at=now,
            monotonic_s=mono,
            process_cpu_time_s=None,
            rss_bytes=None,
            read_bytes=None,
            write_bytes=None,
            ctx_switches=None,
            target_pid=target_pid,
            process_count=None,
            available=False,
            source=source,
        )

    @staticmethod
    def _load_psutil() -> Any | None:
        try:
            import psutil  # type: ignore[import-not-found,import-untyped]

            return psutil
        except Exception:
            return None
