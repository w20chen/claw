# Current Plan

## 2026-07-17 CPU Placement In Reference Launcher

- Continued after the reference launcher lifecycle work.
- Implemented Linux-only, best-effort CPU placement in Python `claw-launch`:
  - parses placement forms such as `cpu_set`, `cpus`, `numa_node`, and
    `numa_nodes`
  - accepts plugin-supplied profiling flags:
    `enable_cgroup`, `enable_affinity`, and `enable_numa`
  - creates a per-execution cgroup under `CLAW_CGROUP_ROOT` when configured
  - writes `cpuset.mems` before `cpuset.cpus`
  - moves the child process into the cgroup from `preexec_fn`, before shell
    command `exec`
  - applies `os.sched_setaffinity(0, cpus)` as a second CPU-placement guard
  - reports the cgroup path to the sidecar so runtime samples can use
    cgroup-v2 accounting
  - falls back to PID scope when cgroup setup is disabled, unavailable, or not
    writable
- Kept scheduler metadata off stdout/stderr.
- Still not complete:
  - NUMA memory policy binding via `set_mempolicy`/`numactl`
  - hardened cleanup for daemonized/background subprocesses
  - Rust/Go static launcher
  - PMU/ksys/VTune wrapping
  - topology-aware policy that actively chooses CPU sets

### Validation

- Passed: `cd services/scheduler && pytest tests\test_launcher.py -q`
  - 4 tests passed.
- Passed: `cd services/scheduler && pytest tests -q`
  - 18 tests passed.

## 2026-07-17 Launcher Token Argument Fix

- Reproduced from Linux demo output: sidecar one-time tokens can start with
  `-`, and `argparse` treats `--token <value>` as missing when `<value>` looks
  like another option.
- Fixed wrapper command generation to use equals-form arguments:
  - `--execution-id=<id>`
  - `--token=<token>`
- Fixed `tools/demo_supported_features.py --run-launcher` to use the same
  equals-form arguments.
- Added launcher argparse coverage for dash-prefixed tokens.

### Validation

- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 4 Node tests passed.
- Passed: `cd services/scheduler && pytest tests\test_launcher.py -q`
  - 5 tests passed.
- Passed: `cd services/scheduler && pytest tests -q`
  - 19 tests passed.
- Passed: `python tools\validate_contracts.py`
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`
- Passed: `pytest tests -q --basetemp .pytest-tmp-root`
  - 3 tests passed.

## 2026-07-16 Reference Launcher And Execution Lifecycle

- Used `agent-test-bench` as a read-only reference source:
  - `src/agents/openclaw/tools/shell.py` for subprocess launch, process tree
    sampling, and signal/timeout behavior.
  - `src/harness/container_stats_sampler.py` for cgroup-v2 file parsing
    patterns.
- Could not implement the preferred Rust/Go static launcher in this environment:
  - `cargo --version` failed: `cargo` is not installed.
  - `go version` failed: `go` is not installed.
- Implemented a Python reference launcher instead:
  - console script: `claw-launch = agent_scheduler.launcher:main`
  - claims one-time execution specs from the sidecar
  - runs `/bin/sh -lc <original command>` on POSIX
  - preserves inherited stdin/stdout/stderr
  - forwards `SIGINT`, `SIGTERM`, and `SIGHUP` to the child process group
  - returns the original process exit code
  - reports child PID, process starttime ticks, PID namespace inode, and exit
    status to the sidecar
- Extended scheduler v2 execution lifecycle:
  - `POST /v2/executions/claim`
  - `POST /v2/executions/{execution_id}/started`
  - `POST /v2/executions/{execution_id}/exited`
  - `GET /v2/executions/{execution_id}/scope`
- One-time execution token is consumed by claim. A separate `update_token` is
  returned for started/exited lifecycle updates.
- Added direct cgroup-v2 resource sampling when a trusted scope includes
  `kind: "cgroup-v2"` and `cgroup_path`.
- Added JSON Schemas and examples for execution claim, started, and exited
  messages.
- Current limitation:
  - Python reference launcher registers PID scope by default.
  - It does not yet create per-tool cgroups, set cpuset.cpus/cpuset.mems,
    call `sched_setaffinity`, bind NUMA policy, or run PMU/ksys/VTune.

### Validation

- Passed: `cd services/scheduler && pytest tests -q`
  - 15 tests passed.
- Passed: `pytest tests -q --basetemp .pytest-tmp-root`
  - 3 tests passed.
- Passed: `python tools\validate_contracts.py`
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 4 Node tests passed.
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`
- Passed: `cd services/scheduler && $env:PYTHONPATH='src'; python -m agent_scheduler.launcher --help`

## 2026-07-16 Execution Backend Refactor

- Accepted the new project boundary: OpenClaw plugin remains the deliverable,
  while runtime execution is designed as TypeScript hook + scheduler sidecar +
  host launcher/collector.
- Implemented P0 correctness fixes:
  - `failOpen=false` now returns the hook-compatible `{block: true,
    blockReason: ...}` shape.
  - Removed fuzzy recursive PID discovery from hook payloads.
  - Correlation state now carries `execution_id`.
  - `before_tool_call` can return rewritten `params`.
- Added `executionBackend` config:
  - `hook-only`
  - `marker`
  - `managed-wrapper`
- Added marker env injection for built-in `exec`:
  - `CLAW_EXECUTION_ID`
  - `CLAW_TOOL_CALL_ID`
  - `CLAW_RUN_ID`
  - `CLAW_SESSION_KEY_HASH`
  - `CLAW_COMMAND_DIGEST`
- Added managed-wrapper command rewrite:
  - OpenClaw runs `launcherPath run --execution-id ... --token ...`.
  - Original command is sent to sidecar execution registration, not shell-quoted
    into the launcher command.
  - `managed-wrapper` requires `securityBoundaryAccepted=true`.
- Added sidecar v2 execution registration protocol:
  - `POST /v2/executions`
  - `GET /v2/executions/{execution_id}/scope`
  - One-time execution tokens are held in memory and are not persisted to
    SQLite.
- Added `execution-registration.schema.json` and updated resource scope schema
  fields for cgroup-v2-oriented attribution.
- Not implemented yet:
  - `claw-launch` host binary.
  - Unix socket launcher claim/start protocol.
  - Actual cgroup creation, CPU affinity, NUMA binding, PMU/ksys/VTune.

### Validation

- Passed: `python tools\validate_contracts.py`
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
  - 4 Node tests passed.
- Passed: `cd services/scheduler && pytest tests -q`
  - 13 tests passed.
- Passed: `cd services/scheduler && pytest tests\test_sidecar.py -q`
  - 3 tests passed.
- Passed with workaround: `pytest tests -q --basetemp .pytest-tmp-root`
  - 3 tests passed.
- Could not run as typed: `cd packages/openclaw-plugin && npm run typecheck`
  - Reason: PowerShell blocks the `npm.ps1` shim under the current execution
    policy.
  - Workaround used: `npm.cmd run typecheck`.
- Could not run from repository root as typed:
  `pytest services\scheduler\tests\test_sidecar.py -q`
  - Reason: scheduler pyproject config sets `--basetemp ../../.pytest-tmp`;
    from the repository root this resolves outside the workspace to
    `C:\Users\29068\.pytest-tmp`, which is not writable in this sandbox.
  - Workaround used: run from `services/scheduler`.
- Could not run without basetemp override: `pytest tests -q`
  - Reason: pytest attempted to scan
    `C:\Users\29068\AppData\Local\Temp\pytest-of-29068`, which is not readable
    in this sandbox.
  - Workaround used: `pytest tests -q --basetemp .pytest-tmp-root`.

## 2026-07-16 Linux-Default Review

- Updated repository defaults and docs to assume a Linux operator machine.
- Passed: `python -m pip install -e 'services/scheduler[dev]'`
  - Installed scheduler runtime/dev dependencies, including `jsonschema`.
- Passed: `python tools/validate_contracts.py`
- Passed: `python -m pytest tests\test_agent_test_bench_adapter.py tests\test_import_agent_test_bench_trace.py --basetemp .pytest-tmp-root`
  - 3 tests passed.
- Passed: `cd services/scheduler && python -m pytest --basetemp ../../.pytest-tmp`
  - 12 tests passed.
- Passed: `python -m ruff check .`
- Passed: `python -m mypy .`
- Passed: `cd packages/openclaw-plugin && npm.cmd install`
- Passed: `cd packages/openclaw-plugin && npm.cmd test`
- Passed: `cd packages/openclaw-plugin && npm.cmd run typecheck`
- Passed: `cd packages/openclaw-plugin && npm.cmd run build`
- Could not run: `docker compose config`
  - Reason: the current validation machine does not have a `docker` command on
    PATH. Docker Compose syntax was still reviewed in source, but container
    config/build/runtime validation remains to be run on a Linux host with
    Docker installed.

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
- [x] Phase 7: Official runtime inspect
- [x] Phase 8: Real-time tool lifecycle monitoring MVP
- [x] Phase 9: External `agent-test-bench` benchmark adapter
- [ ] Phase 10: Full independent code review

## Completed Tests

Updated as commands are run:

- Passed: `python tools/validate_contracts.py`
  - Validated tool request, decision, completion, model event, and tool profile
    examples against local JSON Schemas.
- Passed: `cd services/scheduler && python -m pytest`
  - 2 tests passed.
  - Covers tool decision/completion round trip, runtime sample persistence,
    `/v1/tools/recent`, and monitoring metrics presence.
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
- Passed: `python -m pytest tests\test_agent_test_bench_adapter.py tests\test_import_agent_test_bench_trace.py --basetemp .pytest-tmp-root`
  - Validated external benchmark adapter dry-run delegation, trace validation,
    image metadata discovery, scheduler event export, and profile generation.
- Passed: `python tools\run_agent_test_bench.py --bench-root C:\Users\29068\Desktop\agent-test-bench --dry-run -- --provider deepseek --model deepseek-chat --benchmark swe-rebench --scaffold openclaw --container docker --mcp-config none --sample 1`
  - Confirmed the adapter delegates to `python -m trace_collect.cli` inside
    `agent-test-bench` with `PYTHONPATH=<agent-test-bench>\src`.
- Passed: `python tools\validate_contracts.py`
  - Re-run after real-time monitoring changes; contract examples still validate.
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
- Real-time resource measurements now require `resource_scope.pid` for
  attribution. Calls without PID metadata are recorded as `unattributed`; precise
  cgroup/container accounting still requires OpenClaw execution-layer metadata
  or a managed executor.
