import json
import subprocess
import sys
from pathlib import Path

from swe_rebench.config import RunnerConfig
from swe_rebench.prepare import _ENTRYPOINT_TEMPLATE, _write_entrypoint
from swe_rebench.task_source import filter_tasks, parse_instance_ids, tasks_from_records
from swe_rebench.runner import _inspect_trace, _reset_task_trace_dir, _smoke_summary, _task_artifacts


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
