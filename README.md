# OpenClaw Agent Scheduler

OpenClaw plugin plus Python sidecar for hardware-aware, privacy-preserving
agent tool scheduling. The project boundary is now: the deliverable remains an
OpenClaw plugin, but the execution path is designed as TypeScript hooks,
scheduler sidecar, and host launcher/collector. OpenClaw core and Agent Loop
are not modified; tool calls still originate from OpenClaw's built-in `exec`.

The scheduler is model-provider agnostic. It observes OpenClaw tool/model
lifecycle hooks after OpenClaw has selected a model, so it can be used with any
provider OpenClaw is configured to run, including hosted APIs, provider plugins
such as DeepSeek, OpenRouter-style providers, and local OpenAI-compatible
servers such as vLLM.

Implemented:

- `scheduler.v1` JSON contracts and examples.
- FastAPI sidecar with health, status, decision, completion, model-event, and
  Prometheus-text metrics endpoints.
- SQLite persistence with idempotent event writes.
- Real-time tool lifecycle monitoring with per-tool runtime samples, recent
  sample inspection, privacy-preserving `operation_hint` classification, and
  PID-attributed CPU/RSS/IO/context-switch metrics when OpenClaw provides a
  `resource_scope`.
- `exec` instrumentation modes:
  - `hook-only`: observe/report without modifying tool params.
  - `marker`: injects `CLAW_EXECUTION_ID`, tool/run IDs, session-key digest,
    and command digest into `exec.params.env`.
  - `managed-wrapper`: registers a one-time execution spec with the sidecar and
    rewrites `exec.params.command` to `claw-launch run --execution-id ...`.
- Sidecar `scheduler.v2` execution registration endpoint for future
  launcher/collector integration.
- Python reference `claw-launch` console script that claims a one-time
  execution spec, runs `/bin/sh -lc <original command>`, forwards common
  signals, registers PID scope, and returns the original exit code.
- Reference launcher CPU placement on Linux: optional per-execution cgroup
  creation, `cpuset.mems`/`cpuset.cpus` writes, child cgroup entry before
  `exec`, and `sched_setaffinity` as a second guard.
- Observe-only and bounded concurrency policies.
- Static profile predictor, EWMA calibration, Linux topology inventory.
- TypeScript OpenClaw plugin source with redaction, timeout-aware HTTP client,
  observe/enforce mode handling, and correlation TTL.
- `agent-test-bench` trace importer for offline `trace.jsonl` conversion.
- External `agent-test-bench` benchmark adapter that delegates to the original
  `trace_collect.cli` command and validates/imports the produced traces without
  changing benchmark behavior.

Not implemented in this MVP:

- Managed executor or actual CPU/NUMA affinity enforcement.
- Rust/Go static `claw-launch` binary and cgroup/NUMA collector.
- NUMA memory policy binding, PMU/ksys/VTune wrapping, and production hardening
  of cgroup cleanup/daemonized background processes.
- KV cache migration or GPU serving coordination.
- Managed per-tool subprocess or cgroup enforcement. If OpenClaw does not
  provide a PID/process scope, samples are marked `unattributed` rather than
  pretending sidecar process metrics belong to the tool.

## Quick Start

For copy-pasteable local commands, read
[`docs/operator-guide.md`](docs/operator-guide.md). It covers OpenClaw setup,
plugin linking, sidecar startup, live observation, and the `agent-test-bench`
adapter.

## Supported Now: Directly Observable Demos

The project currently supports sidecar health/status, v1 scheduling decisions,
tool-completion persistence, recent runtime samples, v2 managed execution
registration, `claw-launch` claim/start/exit reporting, and Linux CPU placement
through cgroup cpuset plus `sched_setaffinity`.

Run the sidecar in one terminal:

```bash
cd services/scheduler
PYTHONPATH=src python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

On Windows PowerShell, use:

```powershell
cd services\scheduler
$env:PYTHONPATH = "src"
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Then, from the repository root in a second terminal:

```bash
python tools/demo_supported_features.py --run-launcher
```

Expected visible results:

- `/health/live` and `/health/ready` return JSON.
- `POST /v1/decisions/tool` returns an `allow` decision.
- `POST /v1/events/tool-completed` stores a completion.
- `GET /v1/tools/recent` shows a new runtime sample.
- `POST /v2/executions` creates a one-time execution spec.
- `claw-launch` claims that spec, prints `claw-launch-ok`, reports
  `started/exited`, and returns the original command exit code.
- `GET /v2/executions/<id>/scope` shows the trusted PID or cgroup scope.

For the detailed command guide, including manual `curl` calls, OpenClaw plugin
activation, managed-wrapper mode, and Linux cgroup CPU placement, read
[`docs/supported-features.md`](docs/supported-features.md).

```bash
npm install -g openclaw@2026.7.1
openclaw --version
python -m pip install -e 'services/scheduler[dev]'
cd packages/openclaw-plugin && npm install && cd ../..
make dev-sidecar
make test
make build-plugin
```

If your Python packaging backend does not support editable installs, use:

```bash
python -m pip install 'services/scheduler[dev]'
```

Start the sidecar directly:

```bash
cd services/scheduler
export PYTHONPATH=src
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Build the OpenClaw plugin:

```bash
cd packages/openclaw-plugin
npm install
npm run build
npm pack
```

Install with the official OpenClaw plugin CLI when available:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

This plugin is coupled to OpenClaw's plugin SDK and hook payloads. The validated
baseline is OpenClaw `2026.7.1`; newer versions should be used only after
`openclaw plugins inspect hardware-scheduler --runtime --json` confirms the
hooks still load.

## Architecture

```text
OpenClaw Gateway
  -> TypeScript plugin hooks
     -> before_tool_call can inject markers or rewrite exec command
  -> localhost HTTP/JSON
  -> Python scheduler sidecar
     -> SQLite events
     -> one-time execution registry
     -> realtime tool runtime samples
     -> static prediction + calibration
     -> admission policy
     -> topology inventory
     -> metrics
  -> host launcher/collector
     -> Python reference launcher registers PID/cgroup scope
     -> cpuset and affinity supported on Linux
     -> NUMA memory policy, process-tree cleanup, PMU planned
```

The plugin never sends full prompts, model responses, raw tool output, or raw
tool parameters by default. Raw parameters require explicit `sendRawParams=true`
and still pass recursive redaction.

## Modes

`observe` mode always lets tools run, even if the sidecar blocks or is down.
`enforce` mode applies sidecar decisions. If the sidecar is unavailable,
`failOpen=true` allows the call and `failOpen=false` blocks it with a clear
reason.

`executionBackend` controls `exec` instrumentation:

- `hook-only` is the default and preserves all tool params.
- `marker` preserves the command and injects env markers for a host collector.
- `managed-wrapper` rewrites `command` to the configured `launcherPath`. It
  requires `securityBoundaryAccepted=true` because the launcher becomes the
  trust boundary that retrieves and runs the original command.

## Contracts

JSON Schema files live under `contracts/`. Python models and TypeScript types
mirror those schemas, and tests validate examples across both sides.

## agent-test-bench Integration

An external `agent-test-bench` checkout remains a research and evaluation
source. This project reads exported canonical `trace.jsonl` files and can
generate scheduler tool profiles from `tool_exec` spans, but does not import
its AgentLoop, benchmark runner, or agent scaffold into the online plugin
runtime.

To run benchmarks through the original harness and then validate/import traces,
use `tools/run_agent_test_bench.py`; see
[`docs/agent-test-bench-benchmark.md`](docs/agent-test-bench-benchmark.md) or
the end-to-end flow in [`docs/operator-guide.md`](docs/operator-guide.md).

At runtime, the OpenClaw plugin sends tool start/completion events to the
sidecar. The sidecar stores correlated runtime samples in SQLite and exposes the
latest samples at `GET /v1/tools/recent`; Prometheus metrics are exposed at
`GET /metrics`.
