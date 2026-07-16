from __future__ import annotations

import time

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse

from agent_scheduler.api.dependencies import AppState, build_state
from agent_scheduler.contracts.models import (
    ExecutionClaimRequest,
    ExecutionClaimResponse,
    ExecutionExitedRequest,
    ExecutionRegistrationRequest,
    ExecutionRegistrationResponse,
    ExecutionScopeResponse,
    ExecutionStartedRequest,
    ExecutionUpdateResponse,
    ModelEvent,
    PlacementAdvice,
    StatusResponse,
    ToolBeforeRequest,
    ToolCompletedEvent,
)
from agent_scheduler.llm_proxy import proxy_chat_completions, proxy_models
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

    @app.get("/v1/models")
    @app.get("/models")
    async def llm_proxy_models(
        request: Request,
        s: AppState = Depends(get_state),
    ):
        return await proxy_models(request, s.config)

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def llm_proxy_chat_completions(
        request: Request,
        s: AppState = Depends(get_state),
    ):
        return await proxy_chat_completions(request, s.config, s.trace_writer)

    @app.post("/v1/decisions/tool")
    async def decide_tool(
        request: ToolBeforeRequest,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ):
        start = time.monotonic()
        s.metrics.inc("scheduler_tool_requests_total")
        s.store.save_request(request)
        if s.trace_writer is not None:
            s.trace_writer.record_tool_started(request)
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
                if s.trace_writer is not None:
                    s.trace_writer.record_tool(event, sample)
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
        if s.trace_writer is not None:
            s.trace_writer.record_model(event)
        return {"stored": True}

    @app.post("/v2/executions", response_model=ExecutionRegistrationResponse)
    async def register_execution(
        request: ExecutionRegistrationRequest,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> ExecutionRegistrationResponse:
        return s.executions.register(request)

    @app.get("/v2/executions/{execution_id}/scope", response_model=ExecutionScopeResponse)
    async def execution_scope(
        execution_id: str,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> ExecutionScopeResponse:
        return ExecutionScopeResponse(execution_scope=s.executions.scope(execution_id))

    @app.post("/v2/executions/claim", response_model=ExecutionClaimResponse)
    async def claim_execution(
        request: ExecutionClaimRequest,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> ExecutionClaimResponse:
        return s.executions.claim(request)

    @app.post("/v2/executions/{execution_id}/started", response_model=ExecutionUpdateResponse)
    async def execution_started(
        execution_id: str,
        request: ExecutionStartedRequest,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> ExecutionUpdateResponse:
        response = s.executions.started(execution_id, request)
        record = s.executions.get(execution_id)
        if record is not None and record.scope is not None:
            s.tool_monitor.bind_scope(record.request.tool_call_id, record.scope)
        return response

    @app.post("/v2/executions/{execution_id}/exited", response_model=ExecutionUpdateResponse)
    async def execution_exited(
        execution_id: str,
        request: ExecutionExitedRequest,
        s: AppState = Depends(get_state),
        _: None = Depends(auth),
    ) -> ExecutionUpdateResponse:
        return s.executions.exited(execution_id, request)

    return app
