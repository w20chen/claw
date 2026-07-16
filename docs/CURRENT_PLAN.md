# Current Plan

## Verified Environment

- Date: 2026-07-16
- `node --version`: `v24.18.0`
- `npm.cmd --version`: `11.16.0`
- `npm --version` in PowerShell: blocked by script execution policy
- Official OpenClaw installed with `npm.cmd install -g openclaw@latest`
- Official OpenClaw CLI: `OpenClaw 2026.7.1 (2d2ddc4)`
- Use `C:\Users\29068\AppData\Roaming\npm\openclaw.cmd` from PowerShell.
  The bare `openclaw` command can still hit PowerShell's blocked `.ps1` shim
  unless script execution policy is explicitly changed by the user.
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
- Passed: `C:\Users\29068\AppData\Roaming\npm\openclaw.cmd plugins install --link C:\Users\29068\Desktop\claw\packages\openclaw-plugin`
  - Linked local plugin path into OpenClaw.
- Passed: `C:\Users\29068\AppData\Roaming\npm\openclaw.cmd plugins inspect hardware-scheduler --runtime --json`
  - `status: loaded`
  - `hookCount: 4`
  - `typedHooks`: `before_tool_call`, `after_tool_call`, `model_call_started`,
    `model_call_ended`
  - Compatibility note: hook-only plugin shape, supported compatibility path.
- Passed: short-lived Gateway start check with
  `openclaw.cmd gateway run --allow-unconfigured --auth none --bind loopback --port 18789 --force --verbose`
  - Gateway started and loaded gateway-facing plugins.
  - Gateway startup log does not list hook-only agent-runtime plugins; use
    runtime inspect for hook registration proof.
- Passed: sidecar in-process HTTP check
  - `/health/ready` returned ready.
  - `POST /v1/decisions/tool` returned `allow` with `policy_name=observe-only`.
  - `POST /v1/events/tool-completed` returned `stored=true`.
  - Metrics showed one request, one decision, and one completion.
- Passed: `python -m pytest tests\test_import_agent_test_bench_trace.py --basetemp .pytest-tmp-root`
  - Validated agent-test-bench trace import and generated profile output.
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
- Passed: `C:\Users\29068\AppData\Roaming\npm\openclaw.cmd --version`
  - Output: `OpenClaw 2026.7.1 (2d2ddc4)`
- Passed: `C:\Users\29068\AppData\Roaming\npm\openclaw.cmd plugins list`
  - Confirmed official plugin CLI is installed and stock plugin registry loads.

## Issues

- A Python `openclaw.exe` from `Python312\Scripts` still exists and can shadow
  the official CLI depending on shell resolution. The user PATH was updated to
  put `C:\Users\29068\AppData\Roaming\npm` first for new processes, but
  PowerShell may still prefer the npm `openclaw.ps1` shim and block it under the
  current execution policy. Use `openclaw.cmd` for now.
- TypeScript compiler is installed locally under `packages/openclaw-plugin`
  after `npm.cmd install`.
- Python `ruff` and `mypy` are not installed in the current global environment.
- Isolated `python -m build` failed due a user Temp/encoding issue; the
  non-isolated build succeeded.
- Official OpenClaw SDK package import path must be revalidated once the SDK is
  installed. Current verified import path for this local OpenClaw is
  `openclaw/plugin-sdk/plugin-entry`.
- Full live agent-turn validation is blocked by model auth:
  `openclaw models status` reports default `openai/gpt-5.5` auth missing.

## Unresolved Risks

- Hook event field names may differ from the public examples. The plugin uses
  defensive extraction and must be compiled against the installed SDK before
  declaring runtime compatibility.
- `placement_advice` is advisory only. Real CPU/NUMA/LLC enforcement requires a
  managed executor, container layer, or OpenClaw execution-layer adapter.
