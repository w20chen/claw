from __future__ import annotations

from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.decision_latencies: list[float] = []
        self.tool_durations: list[float] = []
        self.admission_waits: list[float] = []

    def inc(self, name: str) -> None:
        self.counters[name] += 1

    def render(self, active_leases: int) -> str:
        lines = []
        names = [
            "scheduler_tool_requests_total",
            "scheduler_tool_decisions_total",
            "scheduler_tool_completions_total",
            "scheduler_sidecar_errors_total",
            "scheduler_calibration_updates_total",
        ]
        for name in names:
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {self.counters[name]}")
        lines.append("# TYPE scheduler_active_leases gauge")
        lines.append(f"scheduler_active_leases {active_leases}")
        lines.append("# TYPE scheduler_decision_latency_seconds summary")
        lines.append(f"scheduler_decision_latency_seconds_count {len(self.decision_latencies)}")
        lines.append(f"scheduler_decision_latency_seconds_sum {sum(self.decision_latencies):.6f}")
        lines.append("# TYPE scheduler_tool_duration_seconds summary")
        lines.append(f"scheduler_tool_duration_seconds_count {len(self.tool_durations)}")
        lines.append(f"scheduler_tool_duration_seconds_sum {sum(self.tool_durations):.6f}")
        lines.append("# TYPE scheduler_admission_wait_seconds summary")
        lines.append(f"scheduler_admission_wait_seconds_count {len(self.admission_waits)}")
        lines.append(f"scheduler_admission_wait_seconds_sum {sum(self.admission_waits):.6f}")
        return "\n".join(lines) + "\n"
