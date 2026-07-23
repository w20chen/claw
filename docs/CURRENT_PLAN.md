# Current Plan

This file tracks the current implementation state and validation commands that
matter for the next development step. Historical detail belongs in git history,
not in this working plan.

## Current Priority

- Do not implement CPU-side scheduling optimization yet.
- Keep the MVP focused on:
  - OpenClaw plugin delivery.
  - Sidecar protocol and persistence.
  - Per-tool runtime resource monitoring.
  - Live agent-test-bench-style `trace.jsonl`.
  - Full LLM trace capture through the sidecar LLM proxy.
  - Raw tool trace capture through plugin hooks.

## Implemented

- `scheduler.v1` tool/model contracts and examples.
- `scheduler.v2` managed execution registration:
  - register
  - claim
  - started
  - exited
  - scope lookup
- TypeScript OpenClaw plugin hooks:
  - `before_tool_call`
  - `after_tool_call`
  - `model_call_started`
  - `model_call_ended`
- `exec` instrumentation backends:
  - `hook-only`
  - `marker`
  - `managed-wrapper`
- Python reference `claw-launch`.
- Runtime samples for scoped tools:
  - CPU time and average CPU utilization
  - observed peak RSS memory
  - disk read/write bytes and average throughput
  - best-effort network rx/tx bytes and average throughput
  - context switches
  - compact per-tool resource timeline
- Optional `AGENT_SCHEDULER_TRACE_PATH` live trace writer.
- CLI trace visualization with `tools/inspect_trace.py`.
- OpenAI-compatible LLM proxy for full request/response capture:
  - `/v1/models`
  - `/v1/chat/completions`
  - streaming response reconstruction
- Optional plugin `recordRawTrace=true` capture of hook-visible tool
  args/results and raw hook payloads.
- Offline `agent-test-bench` trace importer and benchmark adapter.

## Current Boundaries

- Placement is advisory at the scheduler policy layer.
- Linux CPU cpuset/affinity exists only in the reference launcher path.
- Resource attribution is reliable only with trusted PID or cgroup scope.
- Network I/O is namespace-level best effort from `/proc/<pid>/net/dev`.
- Tools without scope are traced but marked `unattributed`.
- Full LLM content is recorded only when OpenClaw routes the selected provider
  through the sidecar LLM proxy.
- Raw tool content is recorded only when the plugin is explicitly configured
  with `recordRawTrace=true`.
- Do not modify OpenClaw core.
- Do not modify `C:\Users\29068\Desktop\agent-test-bench`.

## SWE-Rebench Integration (swe_rebench/)

The `swe_rebench/` package is an **independent** batch runner that runs
swe-rebench tasks inside Docker containers with full OpenClaw + sidecar
trace collection.

- **Isolation**: Does not modify `packages/openclaw-plugin/`, `services/scheduler/`,
  or OpenClaw core.  All code lives under `swe_rebench/`.
- **Bundle**: `python -m swe_rebench.runner prepare` assembles a runtime bundle
  that gets volume-mounted into each container at `/claw`.
- **Per-task traces**: Each task writes `trace.jsonl` to a dedicated directory
  under `swe_rebench/traces/<task_id>/`.
- **Flat export**: `--export` copies all traces to `swe_rebench/export/` keyed
  by task ID.
- **Sub-commands**: `prepare`, `run`, `collect`, `cleanup`.
- **Task sources**: swe-bench JSON/JSONL datasets, simple JSON lists, or
  single-task CLI (`--image` + `--task-id` + `--problem`).
- **Config**: `swe_rebench/config.example.yaml` (copy and edit as `config.yaml`).

Files:
- `swe_rebench/runner.py` — main CLI orchestrator
- `swe_rebench/prepare.py` — bundle assembler (+ container entrypoint/setup generator)
- `swe_rebench/docker.py` — Docker SDK wrapper with CLI fallback
- `swe_rebench/task_source.py` — multi-format task loader
- `swe_rebench/config.py` — YAML config with env-var substitution

## Validation Commands

Run after code changes:

```bash
python3 tools/validate_contracts.py
python3 -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python3 -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
```

Use `npm.cmd` on Windows PowerShell when `npm.ps1` is blocked.

## Last Known Validation

- Passed: `python3 tools\validate_contracts.py`
- Passed: `python3 -m pytest tests -q --basetemp .pytest-tmp-root`
  - 33 passed, 1 xfail (Windows: `cpu_time_s` is None due to missing process sampling).
- Passed: `cd services/scheduler && python3 -m pytest tests -q`
  - 33 passed, 1 xfail (same Windows limitation).
- Passed: `python3 -m py_compile services\scheduler\src\agent_scheduler\llm_proxy.py services\scheduler\src\agent_scheduler\api\app.py services\scheduler\src\agent_scheduler\trace.py services\scheduler\src\agent_scheduler\config.py`
- Passed: `python3 tools\inspect_trace.py tests\fixtures\agent_test_bench_trace.jsonl --all --details --width 100`
- Passed: `python3 tools\inspect_trace.py tests\fixtures\agent_test_bench_trace.jsonl --all --details --timeline --width 100`
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 33 Node tests passed (2026-07-23, after trace writer key fix + Python sidecar fix).
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`

## Known Environment Notes

- OpenClaw validated baseline: `2026.7.1`.
- PowerShell may block npm `.ps1` shims; use `.cmd`.
- On Windows, pass `--basetemp .pytest-tmp-root` so pytest writes temporary
  files inside the workspace.
- Full live OpenClaw agent validation still depends on local model auth.
- Docker/Podman validation for `agent-test-bench` must be run on a host with
  container support.
