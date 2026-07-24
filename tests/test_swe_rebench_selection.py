import json
import subprocess
import sys
from pathlib import Path

from swe_rebench.config import RunnerConfig
from swe_rebench.docker import ContainerResult
from swe_rebench.task_source import TaskDef
from swe_rebench.prepare import _ENTRYPOINT_TEMPLATE, _PLUGIN_CONFIG, _write_entrypoint
from swe_rebench.task_source import filter_tasks, parse_instance_ids, tasks_from_records
from swe_rebench.runner import (
    _inspect_trace,
    _run_one,
    _require_llm_api_key,
    _reset_task_trace_dir,
    _smoke_summary,
    _task_artifacts,
)


def _records() -> list[dict[str, object]]:
    return [
        {
            "instance_id": "django__a",
            "docker_image": "swerebench/sweb.eval.x86_64.django-a:latest",
            "problem_statement": "A",
            "repo": "django/django",
        },
        {
            "instance_id": "flask__b",
            "docker_image": "swerebench/sweb.eval.x86_64.flask-b:latest",
            "problem_statement": "B",
            "repo": "pallets/flask",
        },
        {
            "instance_id": "django__c",
            "docker_image": "swerebench/sweb.eval.x86_64.django-c:latest",
            "problem_statement": "C",
            "repo": "django/django",
        },
    ]


def test_filter_tasks_supports_repo_skip_and_sample() -> None:
    tasks = tasks_from_records(_records())

    selected = filter_tasks(tasks, repo="django/django", skip=1, sample=1)

    assert [task.instance_id for task in selected] == ["django__c"]


def test_filter_tasks_preserves_instance_id_order() -> None:
    tasks = tasks_from_records(_records())

    selected = filter_tasks(
        tasks,
        instance_ids=parse_instance_ids("django__c,django__a"),
    )

    assert [task.instance_id for task in selected] == ["django__c", "django__a"]


def test_runner_dry_run_accepts_batch_selection_args(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps(_records()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "swe_rebench.runner",
            "run",
            "--config",
            "swe_rebench/config.example.yaml",
            "--tasks",
            str(tasks_path),
            "--repo",
            "django/django",
            "--sample",
            "1",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Loaded 1 tasks" in result.stderr
    assert "django__a" in result.stderr
    assert "django__c" not in result.stderr


def test_runner_falls_back_to_example_config_when_config_yaml_is_missing(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps(_records()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "swe_rebench.runner",
            "run",
            "--config",
            "swe_rebench/does-not-exist.yaml",
            "--tasks",
            str(tasks_path),
            "--repo",
            "django/django",
            "--sample",
            "1",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "falling back to example config" in result.stderr
    assert "Loaded 1 tasks" in result.stderr


def test_inspect_trace_flags_missing_task_id_and_tool_spans(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "record_type": "trace_metadata",
                        "trace_format_version": 6,
                    }
                ),
                json.dumps(
                    {
                        "record_type": "span_start",
                        "kind": "llm",
                        "name": "model",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = _inspect_trace(trace_path, "django__missing")

    assert report["has_llm_span"] is True
    assert report["has_tool_span"] is False
    assert "trace does not contain TASK_INSTANCE_ID" in report["warnings"]
    assert "trace has no tool span/action" in report["warnings"]


def test_inspect_trace_detects_tool_kind_span(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps({"record_type": "trace_metadata", "trace_format_version": 6}),
                json.dumps(
                    {
                        "record_type": "span_start",
                        "kind": "tool",
                        "name": "exec",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = _inspect_trace(trace_path, "")

    assert report["has_tool_span"] is True
    assert "trace has no tool span/action" not in report["warnings"]


def test_inspect_trace_warns_when_launcher_spans_are_unattributed(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"record_type": "trace_metadata", "trace_format_version": 6})
        + "\n"
        + json.dumps(
            {
                "record_type": "span_end",
                "kind": "tool",
                "name": "exec",
                "execution": {"mode": "launcher"},
                "resources": {"attribution_status": "unattributed"},
                "status": {"code": "ok"},
                "output": {"exit_code": None},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = _inspect_trace(trace_path, "")

    assert report["launcher_tool_span_ends"] == 1
    assert report["unattributed_launcher_tool_span_ends"] == 1
    assert "launcher tool spans have no resource attribution" in report["warnings"]


def test_inspect_trace_warns_when_ok_status_has_failed_exit_code(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"record_type": "trace_metadata", "trace_format_version": 6})
        + "\n"
        + json.dumps(
            {
                "record_type": "span_end",
                "kind": "tool",
                "name": "exec",
                "status": {"code": "ok"},
                "output": {"result": {"details": {"exitCode": 1}}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = _inspect_trace(trace_path, "")

    assert report["failed_tool_span_ends"] == 1
    assert "tool span status disagrees with non-zero exit code" in report["warnings"]


def test_inspect_trace_does_not_treat_result_code_as_exit_code(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"record_type": "trace_metadata", "trace_format_version": 6})
        + "\n"
        + json.dumps(
            {
                "record_type": "span_end",
                "kind": "tool",
                "name": "web_fetch",
                "status": {"code": "ok"},
                "output": {"result": {"code": 404, "body": "not found"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = _inspect_trace(trace_path, "")

    assert report["failed_tool_span_ends"] == 0
    assert "tool span status disagrees with non-zero exit code" not in report["warnings"]


def test_entrypoint_uses_runtime_llm_env_and_writes_task_manifest() -> None:
    assert 'AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="${LLM_UPSTREAM_BASE_URL:-__UPSTREAM__}"' in _ENTRYPOINT_TEMPLATE
    assert 'AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY="${LLM_API_KEY:-__LLM_KEY__}"' in _ENTRYPOINT_TEMPLATE
    assert 'export OPENCLAW_MODEL_REF="${OPENCLAW_MODEL_REF:-__MODEL_FULL__}"' in _ENTRYPOINT_TEMPLATE
    assert 'task_manifest.json' in _ENTRYPOINT_TEMPLATE
    assert 'agent-cwd.txt' in _ENTRYPOINT_TEMPLATE
    assert 'agent_prompt.txt' in _ENTRYPOINT_TEMPLATE
    assert 'agent-stdout.txt' in _ENTRYPOINT_TEMPLATE
    assert 'model.patch' in _ENTRYPOINT_TEMPLATE
    assert 'result_summary.json' in _ENTRYPOINT_TEMPLATE


def test_swe_rebench_plugin_config_uses_managed_wrapper_cgroup() -> None:
    assert _PLUGIN_CONFIG["executionBackend"] == "managed-wrapper"
    assert _PLUGIN_CONFIG["launcherPath"] == "/opt/claw/bin/claw-launch"
    assert _PLUGIN_CONFIG["enableCgroup"] is True
    assert _PLUGIN_CONFIG["securityBoundaryAccepted"] is True
    assert _PLUGIN_CONFIG["recordRawTrace"] is False
    assert _PLUGIN_CONFIG["trace"]["include_raw_events"] is False


def test_entrypoint_installs_stable_launcher_path() -> None:
    assert "cat > /opt/claw/bin/claw-launch" in _ENTRYPOINT_TEMPLATE
    assert 'export PYTHONPATH="/claw/scheduler/src${PYTHONPATH:+:$PYTHONPATH}"' in _ENTRYPOINT_TEMPLATE
    assert "python3 -m agent_scheduler.launcher" in _ENTRYPOINT_TEMPLATE


def test_runner_config_enables_complete_cgroup_sampling() -> None:
    config = RunnerConfig.from_yaml("swe_rebench/config.yaml")

    assert config.runtime.mode == "container-openclaw"
    assert config.docker.privileged is True
    assert config.docker.cgroupns_mode == "host"
    assert config.docker.cgroup_mount_rw is True


def test_runner_config_parses_host_openclaw_sandbox_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
runtime:
  mode: "host-openclaw-sandbox"
""",
        encoding="utf-8",
    )

    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)

    assert config.runtime.mode == "host-openclaw-sandbox"


def test_runner_config_rejects_unknown_runtime_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
runtime:
  mode: "mystery"
""",
        encoding="utf-8",
    )

    try:
        RunnerConfig.from_yaml(config_path, repo_root=tmp_path)
    except ValueError as exc:
        assert "runtime.mode" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_run_one_dispatches_to_host_sandbox_runtime(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
runtime:
  mode: "host-openclaw-sandbox"
output:
  trace_root: "traces"
  report_path: "report.json"
bundle:
  output_dir: "bundle"
""",
        encoding="utf-8",
    )
    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)
    task = TaskDef(instance_id="task-1", image="image:latest", problem_statement="fix")
    trace_dir = tmp_path / "traces" / "task-1"
    trace_dir.mkdir(parents=True)
    (trace_dir / "stale.txt").write_text("old", encoding="utf-8")
    called: dict[str, object] = {}

    def fake_host_runner(**kwargs):
        called.update(kwargs)
        assert kwargs["trace_dir"].is_dir()
        assert not (kwargs["trace_dir"] / "stale.txt").exists()
        return ContainerResult(
            task_id="task-1",
            image="image:latest",
            exit_code=0,
            trace_dir=trace_dir,
        )

    import swe_rebench.runner as runner

    monkeypatch.setattr(runner, "run_host_sandbox_task", fake_host_runner)

    result = _run_one(
        client=object(),
        task=task,
        bundle_dir=tmp_path / "bundle",
        trace_dir=trace_dir,
        config=config,
    )

    assert result.exit_code == 0
    assert called["task"] == task
    assert called["config"] == config


def test_runner_config_parses_docker_bool_strings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
docker:
  privileged: "false"
  cgroup_mount_rw: "true"
""",
        encoding="utf-8",
    )

    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)

    assert config.docker.privileged is False
    assert config.docker.cgroup_mount_rw is True


def test_task_artifacts_summarizes_patch_and_result_summary(tmp_path: Path) -> None:
    (tmp_path / "model.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")
    (tmp_path / "agent-cwd.txt").write_text("/testbed\n", encoding="utf-8")
    (tmp_path / "agent-stdout.txt").write_text("done\n", encoding="utf-8")
    (tmp_path / "result_summary.json").write_text(
        json.dumps({"has_patch": True, "patch_bytes": 19}),
        encoding="utf-8",
    )

    artifacts = _task_artifacts(tmp_path)

    assert artifacts["model.patch"]["has_diff"] is True
    assert artifacts["agent-cwd.txt"]["preview"] == "/testbed\n"
    assert artifacts["agent-stdout.txt"]["preview"] == "done\n"
    assert artifacts["result_summary.json"]["summary"]["has_patch"] is True


def test_reset_task_trace_dir_removes_stale_artifacts(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    trace_dir = trace_root / "task-a"
    trace_dir.mkdir(parents=True)
    (trace_dir / "model.patch").write_text("stale diff\n", encoding="utf-8")

    _reset_task_trace_dir(trace_root, trace_dir)

    assert trace_dir.is_dir()
    assert not (trace_dir / "model.patch").exists()


def test_reset_task_trace_dir_refuses_outside_trace_root(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    outside = tmp_path / "outside-task"

    try:
        _reset_task_trace_dir(trace_root, outside)
    except ValueError as exc:
        assert "outside trace root" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_smoke_summary_reports_no_patch_as_unsuccessful() -> None:
    summary = _smoke_summary(
        {
            "agent-cwd.txt": {"preview": "/testbed\n"},
            "result_summary.json": {
                "summary": {
                    "agent_exit_code": 0,
                    "testbed_exists": True,
                    "patch_bytes": 0,
                    "has_patch": False,
                }
            },
        }
    )

    assert summary["success"] is False
    assert summary["reason"] == "no patch produced"
    assert summary["agent_cwd"] == "/testbed"


def test_runner_config_reads_api_key_from_default_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    key_file = tmp_path / "swe_rebench" / "llm_api_key.txt"
    key_file.parent.mkdir()
    key_file.write_text("sk-real-from-file\n", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  api_key: "${LLM_API_KEY}"
""",
        encoding="utf-8",
    )

    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)

    assert config.llm.api_key == "sk-real-from-file"


def test_runner_config_env_api_key_takes_precedence_over_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-real-from-env")
    key_file = tmp_path / "swe_rebench" / "llm_api_key.txt"
    key_file.parent.mkdir()
    key_file.write_text("sk-real-from-file\n", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  api_key: "${LLM_API_KEY}"
""",
        encoding="utf-8",
    )

    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)

    assert config.llm.api_key == "sk-real-from-env"


def test_require_llm_api_key_reports_default_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  api_key: "${LLM_API_KEY}"
""",
        encoding="utf-8",
    )
    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)

    try:
        _require_llm_api_key(config)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("expected SystemExit")

    assert "LLM API key is not configured" in message
    assert "swe_rebench" in message
    assert "llm_api_key.txt" in message


def test_entrypoint_generation_does_not_embed_api_key(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  api_key: "sk-secret"
bundle:
  output_dir: "bundle"
""",
        encoding="utf-8",
    )
    config = RunnerConfig.from_yaml(config_path, repo_root=tmp_path)
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    _write_entrypoint(bundle_dir, config)

    assert "sk-secret" not in (bundle_dir / "entrypoint.sh").read_text(encoding="utf-8")
