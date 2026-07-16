# OpenClaw Agent Scheduler

OpenClaw plugin plus Python sidecar for task-level trace recording, runtime
resource monitoring, and future hardware-aware scheduling.

The project boundary is intentionally narrow:

- Deliverable: an OpenClaw plugin, scheduler sidecar, and reference launcher.
- No OpenClaw core changes.
- No `agent-test-bench` runtime import.
- JSON Schema under `contracts/` is the protocol source of truth.
- Raw trace capture is opt-in with plugin `recordRawTrace=true`. When enabled,
  the plugin records the OpenClaw hook payload fields it can see, without
  modifying OpenClaw core.

## What Works Now

- OpenClaw hooks: `before_tool_call`, `after_tool_call`,
  `model_call_started`, `model_call_ended`.
- Sidecar endpoints for tool decisions, completions, model events, metrics,
  recent runtime samples, and managed `exec` execution lifecycle.
- SQLite persistence with idempotent writes.
- Per-tool runtime samples:
  - CPU time
  - RSS memory before/after and footprint
  - disk read/write bytes
  - best-effort network rx/tx bytes
  - context switches
- Optional live `trace.jsonl` writer shaped like `agent-test-bench` v5:
  `trace_metadata`, `llm_call`, and `tool_exec`. With `recordRawTrace=true`,
  records include visible model input/output, tool args/results, and raw hook
  event payloads.
- `exec` backends:
  - `hook-only`: observe only.
  - `marker`: preserve command and inject correlation env vars.
  - `managed-wrapper`: rewrite command to `claw-launch`, which claims and runs
    the original command through the sidecar.
- Linux reference launcher support for PID scope, optional cgroup-v2 scope, and
  optional CPU cpuset/affinity placement.
- Offline `agent-test-bench` trace import and profile generation.

## Current Limits

- CPU-side scheduling optimization is not implemented yet.
- Placement is advisory. The reference launcher can apply CPU placement only on
  Linux when configured.
- Precise CPU/memory/disk attribution requires a trusted PID or cgroup scope.
  Tools without scope are still traced, but resource fields are `null` and the
  sample is marked `unattributed`.
- Network I/O uses `/proc/<pid>/net/dev`, so it is best-effort Linux network
  namespace accounting, not exact per-process eBPF accounting.
- NUMA memory policy, PMU/ksys/VTune wrapping, GPU/KV-cache scheduling, and a
  hardened static launcher are future work.

## Quick Start

Install dependencies:

```bash
npm install -g openclaw@2026.7.1
python -m pip install -e 'services/scheduler[dev]'

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

Start the sidecar:

```bash
cd services/scheduler
export PYTHONPATH=src
export AGENT_SCHEDULER_DB_PATH=../../data/scheduler.sqlite3
export AGENT_SCHEDULER_TRACE_PATH=../../data/trace.jsonl
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Link the plugin:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

Configure the plugin for real raw trace recording:

```bash
cat <<'JSON5' | openclaw config patch --stdin
{
  plugins: {
    entries: {
      "hardware-scheduler": {
        enabled: true,
        config: {
          endpoint: "http://127.0.0.1:8765",
          mode: "observe",
          failOpen: true,
          recordRawTrace: true,
          executionBackend: "managed-wrapper",
          launcherPath: "claw-launch",
          securityBoundaryAccepted: true
        }
      }
    }
  }
}
JSON5
```

Run a real OpenClaw task and inspect outputs:

```bash
export OPENCLAW_HARDWARE_SCHEDULER_ENDPOINT=http://127.0.0.1:8765
export OPENCLAW_HARDWARE_SCHEDULER_RECORD_RAW_TRACE=true
export OPENCLAW_HARDWARE_SCHEDULER_EXECUTION_BACKEND=managed-wrapper
export OPENCLAW_HARDWARE_SCHEDULER_LAUNCHER_PATH=claw-launch
export OPENCLAW_HARDWARE_SCHEDULER_SECURITY_BOUNDARY_ACCEPTED=true

openclaw models list
export OPENCLAW_TEST_MODEL='<provider/model-from-openclaw-models-list>'
openclaw agent --local --agent main --model "$OPENCLAW_TEST_MODEL" \
  --message 'Use the shell to run: python -c "print(2 + 2)". Then summarize the result.'

curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
tail -n 20 data/trace.jsonl
```

PowerShell note: use `npm.cmd` and `openclaw.cmd` if `.ps1` shims are blocked.

## Important Configuration

Sidecar:

- `AGENT_SCHEDULER_DB_PATH`: SQLite path.
- `AGENT_SCHEDULER_TRACE_PATH`: optional live `trace.jsonl` output.
- `AGENT_SCHEDULER_POLICY`: `observe-only` or `concurrency`.
- `AGENT_SCHEDULER_TOOL_PROFILES`: optional scheduler profile JSON.

Plugin:

- `endpoint`: sidecar URL, usually `http://127.0.0.1:8765`.
- `mode`: `observe` or `enforce`.
- `executionBackend`: `hook-only`, `marker`, or `managed-wrapper`.
- `launcherPath`: path to `claw-launch` for `managed-wrapper`.
- `securityBoundaryAccepted`: required for `managed-wrapper`.
- `recordRawTrace`: set `true` to record visible OpenClaw hook input/output
  content into `trace.jsonl`.

## Docs

- [Operator guide](docs/operator-guide.md): concise install/run/observe flow.
- [Supported features](docs/supported-features.md): current feature matrix and
  validation commands.
- [Architecture](docs/architecture.md): component boundaries.
- [Protocol](docs/protocol.md): scheduler event and execution protocol.
- [Sidecar](docs/sidecar.md): sidecar endpoints and runtime samples.
- [OpenClaw plugin](docs/openclaw-plugin.md): hook and `exec` behavior.
- [agent-test-bench integration](docs/integration-agent-test-bench.md):
  offline trace import and benchmark adapter.

## Validation

```bash
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
```
