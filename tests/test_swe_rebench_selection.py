import json
import subprocess
import sys
from pathlib import Path

from swe_rebench.task_source import filter_tasks, parse_instance_ids, tasks_from_records
from swe_rebench.runner import _inspect_trace, _task_artifacts
from swe_rebench.prepare import _ENTRYPOINT_TEMPLATE


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


def test_entrypoint_uses_runtime_llm_env_and_writes_task_manifest() -> None:
    assert 'AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="${LLM_UPSTREAM_BASE_URL:-__UPSTREAM__}"' in _ENTRYPOINT_TEMPLATE
    assert 'AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY="${LLM_API_KEY:-__LLM_KEY__}"' in _ENTRYPOINT_TEMPLATE
    assert 'export OPENCLAW_MODEL_REF="${OPENCLAW_MODEL_REF:-__MODEL_FULL__}"' in _ENTRYPOINT_TEMPLATE
    assert 'task_manifest.json' in _ENTRYPOINT_TEMPLATE
    assert 'agent_prompt.txt' in _ENTRYPOINT_TEMPLATE
    assert 'model.patch' in _ENTRYPOINT_TEMPLATE
    assert 'result_summary.json' in _ENTRYPOINT_TEMPLATE


def test_task_artifacts_summarizes_patch_and_result_summary(tmp_path: Path) -> None:
    (tmp_path / "model.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")
    (tmp_path / "result_summary.json").write_text(
        json.dumps({"has_patch": True, "patch_bytes": 19}),
        encoding="utf-8",
    )

    artifacts = _task_artifacts(tmp_path)

    assert artifacts["model.patch"]["has_diff"] is True
    assert artifacts["result_summary.json"]["summary"]["has_patch"] is True
