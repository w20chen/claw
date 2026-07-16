from __future__ import annotations

from dataclasses import dataclass

from agent_scheduler.admission.leases import LeaseManager
from agent_scheduler.calibration.ewma import EWMACalibrator
from agent_scheduler.config import SchedulerConfig
from agent_scheduler.executions import ExecutionRegistry
from agent_scheduler.monitoring.tool_runtime import RealtimeToolMonitor
from agent_scheduler.policies.base import SchedulingPolicy
from agent_scheduler.policies.concurrency import ConcurrencyPolicy
from agent_scheduler.policies.observe import ObserveOnlyPolicy
from agent_scheduler.predictors.static_profile import StaticProfilePredictor
from agent_scheduler.storage.sqlite import SQLiteStore
from agent_scheduler.telemetry.metrics import Metrics
from agent_scheduler.topology.linux import read_topology


@dataclass
class AppState:
    config: SchedulerConfig
    store: SQLiteStore
    predictor: StaticProfilePredictor
    leases: LeaseManager
    policy: SchedulingPolicy
    calibrator: EWMACalibrator
    tool_monitor: RealtimeToolMonitor
    executions: ExecutionRegistry
    metrics: Metrics
    topology: dict


def build_state(config: SchedulerConfig | None = None) -> AppState:
    cfg = config or SchedulerConfig.from_env()
    store = SQLiteStore(cfg.db_path)
    store.initialize()
    leases = LeaseManager(cfg.max_global_concurrency, cfg.lease_ttl_ms)
    predictor = StaticProfilePredictor.from_path(cfg.tool_profiles_path)
    policy: SchedulingPolicy
    if cfg.policy == "concurrency":
        policy = ConcurrencyPolicy(leases, cfg.admission_wait_ms)
    else:
        policy = ObserveOnlyPolicy()
    return AppState(
        config=cfg,
        store=store,
        predictor=predictor,
        leases=leases,
        policy=policy,
        calibrator=EWMACalibrator(store, cfg),
        tool_monitor=RealtimeToolMonitor(),
        executions=ExecutionRegistry(),
        metrics=Metrics(),
        topology=read_topology(),
    )
