from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_scheduler.api.app import create_app
from agent_scheduler.api.dependencies import build_state
from agent_scheduler.config import SchedulerConfig


def _client(tmp_path: Path) -> TestClient:
    state = build_state(SchedulerConfig(db_path=tmp_path / "test.sqlite3"))
    return TestClient(create_app(state))


def test_decision_and_completion_round_trip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    request = {
        "schema_version": "scheduler.v1",
        "event_id": "evt-1",
        "occurred_at": "2026-07-16T03:23:00Z",
        "plugin_version": "0.1.0",
        "run_id": None,
        "session_id": None,
        "session_key": None,
        "agent_id": None,
        "tool_call_id": "call-1",
        "tool_name": "exec",
        "tool_kind": "shell",
        "tool_input_kind": "json",
        "derived_paths": [],
        "params_digest": "sha256:" + "a" * 64,
        "param_features": {
            "serialized_size_bytes": 10,
            "string_length": 5,
            "list_item_count": 0,
            "path_count": 0,
            "has_command_like_field": True,
        },
        "raw_params": None,
    }
    decision_response = client.post("/v1/decisions/tool", json=request)
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["action"] == "allow"

    completion = {
        "schema_version": "scheduler.v1",
        "event_id": "evt-2",
        "occurred_at": "2026-07-16T03:23:01Z",
        "plugin_version": "0.1.0",
        "run_id": None,
        "session_id": None,
        "session_key": None,
        "agent_id": None,
        "tool_call_id": "call-1",
        "decision_id": decision["decision_id"],
        "lease_id": decision["lease_id"],
        "tool_name": "exec",
        "duration_ms": 100,
        "succeeded": True,
        "error_type": None,
        "error_digest": None,
        "result_size_bytes": None,
    }
    assert client.post("/v1/events/tool-completed", json=completion).json() == {"stored": True}
    assert client.post("/v1/events/tool-completed", json=completion).json() == {"stored": False}


def test_metrics_endpoint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "scheduler_tool_requests_total" in response.text
