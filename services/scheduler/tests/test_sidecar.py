from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from agent_scheduler.api.app import create_app
from agent_scheduler.api.dependencies import build_state
from agent_scheduler.config import SchedulerConfig


def _client(tmp_path: Path) -> TestClient:
    state = build_state(SchedulerConfig(db_path=tmp_path / "test.sqlite3"))
    return TestClient(create_app(state))


def _trace_client(tmp_path: Path) -> tuple[TestClient, Path]:
    trace_path = tmp_path / "trace.jsonl"
    state = build_state(SchedulerConfig(db_path=tmp_path / "test.sqlite3", trace_path=trace_path))
    return TestClient(create_app(state)), trace_path


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
        "execution_id": None,
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
    assert "scheduler_tool_net_rx_bytes_total" in response.text
    assert "scheduler_tool_net_tx_bytes_total" in response.text


def test_agent_test_bench_trace_jsonl_records_tool_and_model_events(tmp_path: Path) -> None:
    client, trace_path = _trace_client(tmp_path)
    request: dict[str, object] = {
        "schema_version": "scheduler.v1",
        "event_id": "evt-trace-before",
        "occurred_at": "2026-07-16T03:23:00Z",
        "plugin_version": "0.1.0",
        "run_id": "run-trace",
        "session_id": "session-trace",
        "session_key": None,
        "agent_id": "agent-trace",
        "tool_call_id": "call-trace",
        "tool_name": "exec",
        "tool_kind": "shell",
        "tool_input_kind": "json",
        "operation_hint": "pytest",
        "derived_paths": [],
        "params_digest": "sha256:" + "c" * 64,
        "param_features": {
            "serialized_size_bytes": 24,
            "string_length": 20,
            "list_item_count": 0,
            "path_count": 0,
            "has_command_like_field": True,
        },
        "raw_params": None,
        "resource_scope": None,
    }
    decision = client.post("/v1/decisions/tool", json=request).json()

    completion = {
        "schema_version": "scheduler.v1",
        "event_id": "evt-trace-after",
        "occurred_at": "2026-07-16T03:23:02Z",
        "plugin_version": "0.1.0",
        "run_id": "run-trace",
        "session_id": "session-trace",
        "session_key": None,
        "agent_id": "agent-trace",
        "tool_call_id": "call-trace",
        "decision_id": decision["decision_id"],
        "lease_id": decision["lease_id"],
        "execution_id": None,
        "tool_name": "exec",
        "duration_ms": 2000,
        "succeeded": True,
        "error_type": None,
        "error_digest": None,
        "result_size_bytes": 128,
    }
    assert client.post("/v1/events/tool-completed", json=completion).json() == {"stored": True}

    model_started = {
        "schema_version": "scheduler.v1",
        "event_id": "evt-model-start",
        "occurred_at": "2026-07-16T03:23:03Z",
        "plugin_version": "0.1.0",
        "run_id": "run-trace",
        "session_id": "session-trace",
        "session_key": None,
        "agent_id": "agent-trace",
        "event_type": "model_call_started",
        "call_id": "llm-trace",
        "provider": "test-provider",
        "model": "test-model",
        "duration_ms": None,
        "outcome": None,
        "context_token_budget": 8192,
    }
    model_ended = model_started | {
        "event_id": "evt-model-end",
        "occurred_at": "2026-07-16T03:23:05Z",
        "event_type": "model_call_ended",
        "duration_ms": 2000,
        "outcome": "success",
    }
    assert client.post("/v1/events/model", json=model_started).json() == {"stored": True}
    assert client.post("/v1/events/model", json=model_ended).json() == {"stored": True}

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["type"] == "trace_metadata"
    assert records[0]["trace_format_version"] == 5

    tool_records = [record for record in records if record.get("action_type") == "tool_exec"]
    assert len(tool_records) == 1
    tool_record = tool_records[0]
    assert tool_record["type"] == "action"
    assert tool_record["action_id"] == "call-trace"
    assert tool_record["agent_id"] == "agent-trace"
    assert tool_record["data"]["tool_name"] == "exec"
    assert tool_record["data"]["tool_args"] is None
    assert tool_record["data"]["tool_result"] is None
    assert tool_record["data"]["duration_ms"] == 2000.0
    resource_usage = tool_record["data"]["resource_usage"]
    assert resource_usage["attribution_status"] == "unattributed"
    assert "cpu_time_delta_s" in resource_usage
    assert "memory_footprint_bytes" in resource_usage
    assert "net_rx_bytes_delta" in resource_usage
    assert "disk_read_bytes_delta" in resource_usage

    model_records = [record for record in records if record.get("action_type") == "llm_call"]
    assert len(model_records) == 1
    assert model_records[0]["type"] == "action"
    assert model_records[0]["action_id"] == "llm-trace"
    assert model_records[0]["data"]["model"] == "test-model"


def test_execution_registration_round_trip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/v2/executions",
        json={
            "execution_id": "exec-1",
            "tool_call_id": "call-1",
            "run_id": "run-1",
            "session_key_hash": "sha256:" + "a" * 64,
            "command_digest": "sha256:" + "b" * 64,
            "command": "pytest tests -q",
            "workdir": "/workspace",
            "host": "gateway",
            "placement": {"cpu_set": None, "numa_node": None, "llc_cluster": None, "advisory": True},
            "profiling": {"mode": "off"},
            "backend": "marker",
        },
    )
    assert response.status_code == 200
    registration = response.json()
    assert registration["execution_id"] == "exec-1"
    assert registration["one_time_token"]
    assert registration["expires_at"].endswith("Z")

    claim = client.post(
        "/v2/executions/claim",
        json={
            "execution_id": "exec-1",
            "token": registration["one_time_token"],
            "launcher_pid": 100,
        },
    )
    assert claim.status_code == 200
    spec = claim.json()
    assert spec["execution_id"] == "exec-1"
    assert spec["command"] == "pytest tests -q"
    assert spec["workdir"] == "/workspace"
    assert spec["update_token"]

    duplicate_claim = client.post(
        "/v2/executions/claim",
        json={
            "execution_id": "exec-1",
            "token": registration["one_time_token"],
            "launcher_pid": 100,
        },
    )
    assert duplicate_claim.status_code == 409

    started = client.post(
        "/v2/executions/exec-1/started",
        json={
            "update_token": spec["update_token"],
            "launcher_pid": 100,
            "child_pid": 101,
            "process_starttime_ticks": 12345,
            "cgroup_path": None,
            "pid_namespace_inode": 4026531836,
            "container_id": None,
        },
    )
    assert started.status_code == 200
    assert started.json() == {"stored": True}

    scope = client.get("/v2/executions/exec-1/scope")
    assert scope.status_code == 200
    assert scope.json()["execution_scope"] == {
        "kind": "pid",
        "execution_id": "exec-1",
        "pid": 101,
        "root_pid": 101,
        "process_start_time": None,
        "root_starttime_ticks": 12345.0,
        "cgroup_path": None,
        "pid_namespace_inode": 4026531836,
        "container_id": None,
        "include_children": True,
        "source": "claw-launch",
        "attribution_source": "claw-launch",
    }

    exited = client.post(
        "/v2/executions/exec-1/exited",
        json={"update_token": spec["update_token"], "exit_code": 0, "signal": None},
    )
    assert exited.status_code == 200
    assert exited.json() == {"stored": True}
