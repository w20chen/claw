from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_LLM_UPSTREAM_BASE_URL = "https://api.deepseek.com"


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
    resource_poll_interval_ms: int = 50
    resource_timeline_max_points: int = 2_000
    llm_proxy_enabled: bool = True
    llm_proxy_upstream_base_url: str | None = None
    llm_proxy_upstream_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        env_base = load_env_file()
        profile = os.getenv("AGENT_SCHEDULER_TOOL_PROFILES")
        trace = os.getenv("AGENT_SCHEDULER_TRACE_PATH")
        return cls(
            db_path=_path_from_env("AGENT_SCHEDULER_DB_PATH", "scheduler.sqlite3", env_base),
            policy=os.getenv("AGENT_SCHEDULER_POLICY", "observe-only"),
            max_global_concurrency=int(os.getenv("AGENT_SCHEDULER_MAX_GLOBAL_CONCURRENCY", "4")),
            lease_ttl_ms=int(os.getenv("AGENT_SCHEDULER_LEASE_TTL_MS", "300000")),
            admission_wait_ms=int(os.getenv("AGENT_SCHEDULER_ADMISSION_WAIT_MS", "5000")),
            calibration_alpha=float(os.getenv("AGENT_SCHEDULER_CALIBRATION_ALPHA", "0.2")),
            calibration_min_ratio=float(os.getenv("AGENT_SCHEDULER_CALIBRATION_MIN_RATIO", "0.25")),
            calibration_max_ratio=float(os.getenv("AGENT_SCHEDULER_CALIBRATION_MAX_RATIO", "4.0")),
            tool_profiles_path=_resolve_path(profile, env_base) if profile else None,
            auth_token=os.getenv("AGENT_SCHEDULER_TOKEN"),
            trace_path=_resolve_path(trace, env_base) if trace else None,
            resource_poll_interval_ms=int(os.getenv("AGENT_SCHEDULER_RESOURCE_POLL_INTERVAL_MS", "50")),
            resource_timeline_max_points=int(os.getenv("AGENT_SCHEDULER_RESOURCE_TIMELINE_MAX_POINTS", "2000")),
            llm_proxy_enabled=os.getenv("AGENT_SCHEDULER_LLM_PROXY_ENABLED", "true").lower()
            not in {"0", "false", "no"},
            llm_proxy_upstream_base_url=os.getenv(
                "AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL",
                DEFAULT_LLM_UPSTREAM_BASE_URL,
            ),
            llm_proxy_upstream_api_key=os.getenv("AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY"),
        )


def load_env_file() -> Path:
    selected = os.getenv("AGENT_SCHEDULER_ENV_FILE")
    candidates = [Path(selected)] if selected else list(_default_env_candidates())
    for candidate in candidates:
        path = candidate.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            continue
        _load_dotenv(path)
        return path.parent
    return Path.cwd()


def _default_env_candidates() -> Iterable[Path]:
    cwd = Path.cwd()
    root = _repo_root()
    yield cwd / ".env"
    yield cwd / ".env.openclaw-recorder"
    yield root / ".env"
    yield root / ".env.openclaw-recorder"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_dotenv(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if sep != "=":
            continue
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _unquote_env_value(value.strip())


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _path_from_env(name: str, default: str, base: Path) -> Path:
    return _resolve_path(os.getenv(name, default), base)


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path
