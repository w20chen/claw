from __future__ import annotations

import os
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
    request: dict[str, object] = {
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
        "operation_hint": "pytest",
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
        "resource_scope": None,
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
    recent = client.get("/v1/tools/recent").json()
    assert len(recent["samples"]) == 1
    sample = recent["samples"][0]
    assert sample["tool_call_id"] == "call-1"
    assert sample["tool_name"] == "exec"
    assert sample["duration_ms"] == 100
    assert sample["resource_class"] == "unknown"
    assert sample["attribution_status"] == "unattributed"

    request_without_tool_call_id = request | {
        "event_id": "evt-3",
        "tool_call_id": None,
        "params_digest": "sha256:" + "b" * 64,
        "resource_scope": {
            "pid": os.getpid(),
            "process_start_time": None,
            "container_id": None,
            "include_children": True,
            "source": "test",
        },
    }
    second_decision = client.post("/v1/decisions/tool", json=request_without_tool_call_id).json()
    completion_without_tool_call_id = completion | {
        "event_id": "evt-4",
        "tool_call_id": None,
        "decision_id": second_decision["decision_id"],
        "lease_id": second_decision["lease_id"],
    }
    assert client.post("/v1/events/tool-completed", json=completion_without_tool_call_id).json() == {
        "stored": True
    }
    recent = client.get("/v1/tools/recent").json()
    assert len(recent["samples"]) == 2
    assert recent["samples"][0]["target_pid"] == os.getpid()


def test_metrics_endpoint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "scheduler_tool_requests_total" in response.text
    assert "scheduler_tool_runtime_samples_total" in response.text
    assert "scheduler_tool_runtime_unattributed_samples_total" in response.text
    assert "scheduler_tool_cpu_seconds_total" in response.text
    assert "scheduler_tool_memory_rss_bytes" in response.text
    assert "scheduler_tool_process_count" in response.text
