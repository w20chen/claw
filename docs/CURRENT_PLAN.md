# Current Plan

## Verified Environment

- Date: 2026-07-16
- `node --version`: `v24.18.0`
- `npm.cmd --version`: `11.16.0`
- `npm --version` in PowerShell: blocked by script execution policy
- `openclaw --version`: not supported by the local command; it resolves to
  `python -m agents.openclaw` from `agent-test-bench` and exits with
  `unrecognized arguments: --version`
- Python: `3.12.4`
- FastAPI/Pydantic: FastAPI `0.128.0`, Pydantic `2.12.5`
- Missing local development tools observed so far: `tsc`, `aiosqlite`, `ruff`,
  `mypy`, `prometheus_client`

## Official SDK Facts Checked

OpenClaw plugin design was checked against the current public documentation
URLs requested in the brief:

- https://docs.openclaw.ai/plugins/sdk-overview
- https://docs.openclaw.ai/plugins/building-plugins
- https://docs.openclaw.ai/plugins/manifest
- https://docs.openclaw.ai/plugins/sdk-entrypoints
- https://docs.openclaw.ai/plugins/hooks
- https://docs.openclaw.ai/plugins/manage-plugins
- https://github.com/openclaw/openclaw
- https://github.com/w20chen/agent-test-bench

Observed contract used by this implementation:

- OpenClaw plugin manifest: `openclaw.plugin.json`
- Runtime entrypoint: TypeScript ESM module
- Plugin entry helper: `definePluginEntry`
- Hook registration: `api.on(...)`
- Hooks targeted by MVP: `before_tool_call`, `after_tool_call`,
  `model_call_started`, `model_call_ended`
- Runtime validation target, when official CLI is installed:
  `openclaw plugins inspect hardware-scheduler --runtime --json`

The local environment cannot currently prove the exact official SDK package
import path by TypeScript compilation because the official SDK package and
`tsc` are not installed. The plugin therefore includes a local `.d.ts` shim
only for repository tests and documents this as an unresolved compatibility
risk.

## Phases

- [x] Phase 0: Environment and SDK research
- [x] Phase 1: Protocol and repository skeleton
- [x] Phase 2: Python sidecar MVP
- [x] Phase 3: TypeScript OpenClaw plugin MVP
- [x] Phase 4: Cross-language contract examples and validation script
- [x] Phase 5: `agent-test-bench` trace importer
- [x] Phase 6: Packaging/deployment docs and examples
- [ ] Phase 7: Full independent code review and official runtime inspect

## Completed Tests

Updated as commands are run:

- Passed: `python tools/validate_contracts.py`
  - Validated tool request, decision, completion, model event, and tool profile
    examples against local JSON Schemas.
- Passed: `cd services/scheduler && python -m pytest`
  - 2 tests passed.
- Passed: `$env:PYTHONPATH='services/scheduler/src'; python tools\smoke_test.py`
  - Sidecar live/ready smoke test passed.
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 2 Node tests passed.
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`
- Passed: `cd packages/openclaw-plugin && npm.cmd run build`
- Passed: `cd packages/openclaw-plugin && npm.cmd pack --dry-run --cache .\.npm-cache`
  - Tarball includes `dist/*`, `openclaw.plugin.json`, `README.md`, and
    `package.json`.
- Passed: `cd packages/openclaw-plugin && npm.cmd pack --cache .\.npm-cache`
  - Tarball: `packages/openclaw-plugin/w20chen-openclaw-hardware-scheduler-0.1.0.tgz`
- Passed with workaround: `cd services/scheduler && python -m build --no-isolation`
  - Wheel: `services/scheduler/dist/agent_scheduler-0.1.0-py3-none-any.whl`
  - Sdist: `services/scheduler/dist/agent_scheduler-0.1.0.tar.gz`
- Failed as expected in this environment: `python -m ruff check .`
  - Reason: `No module named ruff`
- Failed as expected in this environment: `python -m mypy .`
  - Reason: `No module named mypy`
- Failed as expected in this environment:
  `openclaw plugins inspect hardware-scheduler --runtime --json`
  - Reason: local `openclaw` resolves to `python -m agents.openclaw` and does
    not support plugin-management subcommands.

## Issues

- Local `openclaw` is not the official plugin CLI.
- TypeScript compiler is installed locally under `packages/openclaw-plugin`
  after `npm.cmd install`.
- Python `ruff` and `mypy` are not installed in the current global environment.
- Isolated `python -m build` failed due a user Temp/encoding issue; the
  non-isolated build succeeded.
- Official OpenClaw SDK package import path must be revalidated once the SDK is
  installed.

## Unresolved Risks

- Hook event field names may differ from the public examples. The plugin uses
  defensive extraction and must be compiled against the installed SDK before
  declaring runtime compatibility.
- `placement_advice` is advisory only. Real CPU/NUMA/LLC enforcement requires a
  managed executor, container layer, or OpenClaw execution-layer adapter.
