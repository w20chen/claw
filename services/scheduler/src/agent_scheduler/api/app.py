from __future__ import annotations

import time

from fastapi import Depends, FastAPI
from fastapi.responses import PlainTextResponse

from agent_scheduler.api.dependencies import AppState, build_state
from agent_scheduler.contracts.models import (
    ModelEvent,
    PlacementAdvice,
    StatusResponse,
    ToolBeforeRequest,
    ToolCompletedEvent,
)
from agent_scheduler.policies.base import SchedulingContext
from agent_scheduler.security.auth import verify_bearer


def create_app(state: AppState | None = None) -> FastAPI:
    app_state = state or build_state()
    app = FastAPI(title="OpenClaw Hardware Scheduler Sidecar", version="0.1.0")
    app.state.scheduler = app_state

    def get_state() -> AppState:
        return app.state.scheduler

    def auth(s: AppState = Depends(get_state)) -> None:
        verify_bearer(s.config.auth_token)

    @app.get("/health/live")
    async def live() -> dict[str, bool]:
        return {"live": True}

    @app.get("/health/ready")
    async def ready(s: AppState = Depends(get_state)) -> dict[str, bool]:
        return {"ready": s.store.conn is not None}

    @app.get("/v1/status", response_model=StatusResponse)
    async def status(s: AppState = Depends(get_state), _: None = Depends(auth)) -> StatusResponse:
        return StatusResponse(ready=True, policy=s.config.policy, topology=s.topology)

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics(s: AppState = Depends(get_state)) -> str:
        return s.metrics.render(
            await s.leases.active_count(),
            active_tool_monitors=s.tool_monitor.active_count(),
        )

    @app.get("/v1/tools/recent")
    async def recent_tools(
        limit: int = 20,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> dict[str, object]:
        return {"samples": s.store.recent_tool_runtime_samples(limit)}

    @app.post("/v1/decisions/tool")
    async def decide_tool(
        request: ToolBeforeRequest,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ):
        start = time.monotonic()
        s.metrics.inc("scheduler_tool_requests_total")
        s.store.save_request(request)
        prediction = await s.predictor.predict(request)
        decision = await s.policy.decide(
            request,
            SchedulingContext(prediction=prediction, placement=PlacementAdvice()),
        )
        if decision.action == "allow":
            s.tool_monitor.begin(request, prediction.resource_class)
        s.store.save_decision(request.event_id, request.tool_call_id, decision)
        s.metrics.inc("scheduler_tool_decisions_total")
        s.metrics.decision_latencies.append(time.monotonic() - start)
        return decision

    @app.post("/v1/events/tool-completed")
    async def complete_tool(
        event: ToolCompletedEvent,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> dict[str, bool]:
        inserted = s.store.save_completion(event)
        await s.leases.release(event.lease_id)
        if inserted:
            sample = s.tool_monitor.complete(event)
            if s.store.save_tool_runtime_sample(sample):
                s.metrics.observe_tool_runtime(sample)
            s.metrics.inc("scheduler_tool_completions_total")
            s.metrics.tool_durations.append(event.duration_ms / 1000)
            if s.calibrator.update(event, None):
                s.metrics.inc("scheduler_calibration_updates_total")
        return {"stored": inserted}

    @app.post("/v1/events/model")
    async def model_event(
        event: ModelEvent,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> dict[str, bool]:
        s.store.save_model_event(event)
        return {"stored": True}

    return app
