from __future__ import annotations

from dataclasses import dataclass

from agent_scheduler.admission.leases import LeaseManager
from agent_scheduler.config import SchedulerConfig
from agent_scheduler.contracts.models import ResourceScope
from agent_scheduler.executions import ExecutionRegistry
from agent_scheduler.monitoring.docker_exec import DockerExecObserver
from agent_scheduler.monitoring.tool_runtime import RealtimeToolMonitor
from agent_scheduler.policies.base import SchedulingPolicy
from agent_scheduler.policies.concurrency import ConcurrencyPolicy
from agent_scheduler.policies.observe import ObserveOnlyPolicy
from agent_scheduler.predictors.static_profile import StaticProfilePredictor
from agent_scheduler.telemetry.metrics import Metrics
from agent_scheduler.topology.linux import read_topology
from agent_scheduler.trace import AgentTestBenchTraceWriter


@dataclass
class AppState:
    config: SchedulerConfig
    predictor: StaticProfilePredictor
    leases: LeaseManager
    policy: SchedulingPolicy
    tool_monitor: RealtimeToolMonitor
    docker_exec_observer: DockerExecObserver | None
    executions: ExecutionRegistry
    metrics: Metrics
    topology: dict
    trace_writer: AgentTestBenchTraceWriter
    _sandbox_scope_override: ResourceScope | None
    _completed_tool_event_ids: set[str]  # dedup: track completed tool event_ids
    _recent_samples: list[dict[str, object]]  # recent tool runtime samples for /v1/tools/recent
    _max_recent_samples: int = 200  # max samples to keep in memory


def build_state(config: SchedulerConfig | None = None) -> AppState:
    cfg = config or SchedulerConfig.from_env()
    leases = LeaseManager(cfg.max_global_concurrency, cfg.lease_ttl_ms)
    predictor = StaticProfilePredictor.from_path(cfg.tool_profiles_path)
    policy: SchedulingPolicy
    if cfg.policy == "concurrency":
        policy = ConcurrencyPolicy(leases, cfg.admission_wait_ms)
    else:
        policy = ObserveOnlyPolicy()
    return AppState(
        config=cfg,
        predictor=predictor,
        leases=leases,
        policy=policy,
        tool_monitor=RealtimeToolMonitor(
            poll_interval_s=max(0.01, cfg.resource_poll_interval_ms / 1000),
            max_timeline_points=max(1, cfg.resource_timeline_max_points),
        ),
        docker_exec_observer=DockerExecObserver(
            enabled=cfg.docker_exec_observer_enabled,
            docker_socket=cfg.docker_socket,
            container_id=cfg.sandbox_container_id,
            container_prefix=cfg.docker_exec_container_prefix,
        )
        if cfg.docker_exec_observer_enabled
        else None,
        executions=ExecutionRegistry(),
        metrics=Metrics(),
        topology=read_topology(),
        trace_writer=AgentTestBenchTraceWriter(
            cfg.trace_dir,
            max_messages_bytes=cfg.trace_max_messages_bytes,
        ),
        _sandbox_scope_override=None,
        _completed_tool_event_ids=set(),
        _recent_samples=[],
    )
