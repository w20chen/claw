from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchedulerConfig:
    db_path: Path = Path("scheduler.sqlite3")
    policy: str = "observe-only"
    max_global_concurrency: int = 4
    lease_ttl_ms: int = 300_000
    admission_wait_ms: int = 5_000
    calibration_alpha: float = 0.2
    calibration_min_ratio: float = 0.25
    calibration_max_ratio: float = 4.0
    tool_profiles_path: Path | None = None
    auth_token: str | None = None
    trace_path: Path | None = None

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        profile = os.getenv("AGENT_SCHEDULER_TOOL_PROFILES")
        trace = os.getenv("AGENT_SCHEDULER_TRACE_PATH")
        return cls(
            db_path=Path(os.getenv("AGENT_SCHEDULER_DB_PATH", "scheduler.sqlite3")),
            policy=os.getenv("AGENT_SCHEDULER_POLICY", "observe-only"),
            max_global_concurrency=int(os.getenv("AGENT_SCHEDULER_MAX_GLOBAL_CONCURRENCY", "4")),
            lease_ttl_ms=int(os.getenv("AGENT_SCHEDULER_LEASE_TTL_MS", "300000")),
            admission_wait_ms=int(os.getenv("AGENT_SCHEDULER_ADMISSION_WAIT_MS", "5000")),
            calibration_alpha=float(os.getenv("AGENT_SCHEDULER_CALIBRATION_ALPHA", "0.2")),
            calibration_min_ratio=float(os.getenv("AGENT_SCHEDULER_CALIBRATION_MIN_RATIO", "0.25")),
            calibration_max_ratio=float(os.getenv("AGENT_SCHEDULER_CALIBRATION_MAX_RATIO", "4.0")),
            tool_profiles_path=Path(profile) if profile else None,
            auth_token=os.getenv("AGENT_SCHEDULER_TOKEN"),
            trace_path=Path(trace) if trace else None,
        )
