# OpenClaw Agent Scheduler

OpenClaw plugin plus Python sidecar for task-level trace recording, runtime
resource monitoring, and future hardware-aware scheduling.

The project boundary is intentionally narrow:

- Deliverable: an OpenClaw plugin, scheduler sidecar, reference launcher, and
  OpenAI-compatible LLM proxy.
- No OpenClaw core changes.
- No `agent-test-bench` runtime import.
- JSON Schema under `contracts/` is the protocol source of truth.
- Full LLM trace capture uses the sidecar LLM proxy. Tool args/results are
  recorded by default through plugin `recordRawTrace=true`.

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
- Live `trace.jsonl` writer shaped like `agent-test-bench` v5:
  `trace_metadata`, `llm_call`, and `tool_exec`. The default full-trace path is
  to route OpenClaw model traffic through the sidecar LLM proxy, which records
  full request messages and response content. With `recordRawTrace=true`, tool
  hooks record visible tool args/results and raw hook event payloads.
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
- Full LLM request/response capture requires routing the selected OpenClaw
  provider through the sidecar proxy. If the provider bypasses the proxy, model
  hook records may contain metadata only.
- NUMA memory policy, PMU/ksys/VTune wrapping, GPU/KV-cache scheduling, and a
  hardened static launcher are future work.

## Quick Start

Install dependencies:

```bash
npm install -g openclaw@2026.7.1
python3 -m pip install -e 'services/scheduler[dev]'
command -v claw-launch
claw-launch --help

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

Start the sidecar:

```bash
cp .env.example .env

cd services/scheduler
python3 -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Configure an OpenClaw OpenAI-compatible local provider to use the sidecar
proxy. The validated path uses OpenClaw's `vllm` onboarding mode with the
sidecar as the custom base URL:

```bash
export DEEPSEEK_API_KEY='<your-deepseek-api-key>'
openclaw onboard --non-interactive \
  --mode local \
  --auth-choice vllm \
  --custom-base-url 'http://127.0.0.1:8765/v1' \
  --custom-api-key "$DEEPSEEK_API_KEY" \
  --custom-model-id 'deepseek-v4-flash'
```

DeepSeek's upstream URL is the built-in sidecar default. If OpenClaw sends a
placeholder or local-provider key that DeepSeek will not accept, set
`AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY` in `.env` and restart the sidecar; that
sidecar key overrides OpenClaw's forwarded `Authorization` header.

Link the plugin:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

Configure the plugin for real raw trace recording:

```bash
cat <<JSON5 | openclaw config patch --stdin
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
          launcherPath: "$(command -v claw-launch)",
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
openclaw models list
export OPENCLAW_TEST_MODEL='vllm/deepseek-v4-flash'
openclaw agent --local --agent main --model "$OPENCLAW_TEST_MODEL" \
  --message 'Use the shell to run: python3 -c "from pathlib import Path; import hashlib, math, os, time; p=Path(\"openclaw_trace_probe.bin\"); blob=bytearray(os.urandom(16*1024*1024)); total=sum(math.sqrt(i) for i in range(2000000)); digest=hashlib.sha256(blob).hexdigest()[:16]; p.write_bytes(blob); data=p.read_bytes(); time.sleep(0.5); print(\"heavy-ok\", len(data), int(total), digest)". Then summarize the result.'

curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
tail -n 20 data/trace.jsonl
python3 tools/inspect_trace.py data/trace.jsonl --tail 20 --details
python3 tools/inspect_trace.py data/trace.jsonl --type tool_exec --tail 10 --details --timeline
```

OpenClaw logs must show model traffic going to
`http://127.0.0.1:8765/v1/chat/completions`. If they show
`https://api.deepseek.com/chat/completions`, the selected model is bypassing the
proxy and full LLM input/output will not be recorded.

The default run creates:

- `data/openclaw-trace.sqlite3`: sidecar SQLite persistence for tool/model
  events, decisions, completions, and runtime samples.
- `data/trace.jsonl`: live agent-test-bench v5-shaped trace records. It
  includes `llm_call` records with `messages_in`, `content`, `raw_request`,
  and `raw_response` when the proxy path is used, plus `tool_exec` records
  with `tool_args`, `tool_result`, and `resource_usage`.

PowerShell note: use `npm.cmd` and `openclaw.cmd` if `.ps1` shims are blocked.

## Important Configuration

Sidecar:

- `.env`: default sidecar config file, loaded automatically from the repo root
  or from `AGENT_SCHEDULER_ENV_FILE`.
- `AGENT_SCHEDULER_DB_PATH`: SQLite path.
- `AGENT_SCHEDULER_TRACE_PATH`: optional live `trace.jsonl` output.
- `AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL`: optional real OpenAI-compatible
  provider base URL used by the LLM proxy. Defaults to DeepSeek.
- `AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY`: optional upstream provider API key
  override. Leave unset when OpenClaw already sends `Authorization`.
- `AGENT_SCHEDULER_POLICY`: `observe-only` or `concurrency`.
- `AGENT_SCHEDULER_TOOL_PROFILES`: optional scheduler profile JSON.

Plugin:

- `endpoint`: sidecar URL, usually `http://127.0.0.1:8765`.
- `mode`: `observe` or `enforce`.
- `executionBackend`: `hook-only`, `marker`, or `managed-wrapper`.
- `launcherPath`: path to `claw-launch` for `managed-wrapper`.
- `securityBoundaryAccepted`: required for `managed-wrapper`.
- `recordRawTrace`: defaults to `true`; records visible OpenClaw tool hook
  args/results into `trace.jsonl`.

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
python3 tools/validate_contracts.py
python3 -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python3 -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
```
