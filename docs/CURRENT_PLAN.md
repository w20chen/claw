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
  - 3 tests passed.
- Passed: `cd services/scheduler && python3 -m pytest tests -q`
  - 31 tests passed.
- Passed: `python3 -m py_compile services\scheduler\src\agent_scheduler\llm_proxy.py services\scheduler\src\agent_scheduler\api\app.py services\scheduler\src\agent_scheduler\trace.py services\scheduler\src\agent_scheduler\config.py`
- Passed: `python3 tools\inspect_trace.py tests\fixtures\agent_test_bench_trace.jsonl --all --details --width 100`
- Passed: `python3 tools\inspect_trace.py tests\fixtures\agent_test_bench_trace.jsonl --all --details --timeline --width 100`
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 6 Node tests passed.
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`

## Known Environment Notes

- OpenClaw validated baseline: `2026.7.1`.
- PowerShell may block npm `.ps1` shims; use `.cmd`.
- On Windows, pass `--basetemp .pytest-tmp-root` so pytest writes temporary
  files inside the workspace.
- Full live OpenClaw agent validation still depends on local model auth.
- Docker/Podman validation for `agent-test-bench` must be run on a host with
  container support.
