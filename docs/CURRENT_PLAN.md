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
  - Optional raw model/tool trace capture through plugin hooks.

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
  - CPU time
  - RSS memory
  - disk read/write bytes
  - best-effort network rx/tx bytes
  - context switches
- Optional `AGENT_SCHEDULER_TRACE_PATH` live trace writer.
- Optional plugin `recordRawTrace=true` capture of hook-visible model
  input/output, tool args/results, and raw hook payloads.
- Offline `agent-test-bench` trace importer and benchmark adapter.

## Current Boundaries

- Placement is advisory at the scheduler policy layer.
- Linux CPU cpuset/affinity exists only in the reference launcher path.
- Resource attribution is reliable only with trusted PID or cgroup scope.
- Network I/O is namespace-level best effort from `/proc/<pid>/net/dev`.
- Tools without scope are traced but marked `unattributed`.
- Raw model/tool content is recorded only when the plugin is explicitly
  configured with `recordRawTrace=true`.
- Do not modify OpenClaw core.
- Do not modify `C:\Users\29068\Desktop\agent-test-bench`.

## Validation Commands

Run after code changes:

```bash
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
```

Use `npm.cmd` on Windows PowerShell when `npm.ps1` is blocked.

## Last Known Validation

- Passed: `python tools\validate_contracts.py`
- Passed: `python -m pytest tests -q --basetemp .pytest-tmp-root`
  - 3 tests passed.
- Passed: `cd services/scheduler && python -m pytest tests -q`
  - 20 tests passed.
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 4 Node tests passed.
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`

## Known Environment Notes

- OpenClaw validated baseline: `2026.7.1`.
- PowerShell may block npm `.ps1` shims; use `.cmd`.
- Full live OpenClaw agent validation still depends on local model auth.
- Docker/Podman validation for `agent-test-bench` must be run on a host with
  container support.
