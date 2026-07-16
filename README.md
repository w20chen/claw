# OpenClaw Hardware-Aware Agent Scheduler

OpenClaw plugin plus Python sidecar for hardware-aware, privacy-preserving
agent tool scheduling. The first delivery is intentionally conservative:
OpenClaw hooks normalize events and ask the local sidecar for allow/block
decisions; the sidecar persists decisions, exposes metrics, predicts from
static tool profiles, and returns advisory placement metadata.

Implemented:

- `scheduler.v1` JSON contracts and examples.
- FastAPI sidecar with health, status, decision, completion, model-event, and
  Prometheus-text metrics endpoints.
- SQLite persistence with idempotent event writes.
- Real-time tool lifecycle monitoring with per-tool runtime samples, recent
  sample inspection, privacy-preserving `operation_hint` classification, and
  PID-attributed CPU/RSS/IO/context-switch metrics when OpenClaw provides a
  `resource_scope`.
- Observe-only and bounded concurrency policies.
- Static profile predictor, EWMA calibration, Linux topology inventory.
- TypeScript OpenClaw plugin source with redaction, timeout-aware HTTP client,
  observe/enforce mode handling, and correlation TTL.
- `agent-test-bench` trace importer for offline `trace.jsonl` conversion.

Not implemented in this MVP:

- Managed executor or actual CPU/NUMA affinity enforcement.
- KV cache migration or GPU serving coordination.
- Managed per-tool subprocess or cgroup enforcement. If OpenClaw does not
  provide a PID/process scope, samples are marked `unattributed` rather than
  pretending sidecar process metrics belong to the tool.

## Quick Start

```bash
make dev-sidecar
make test
make build-plugin
```

Start the sidecar directly:

```bash
cd services/scheduler
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
openclaw plugins install --link ./packages/openclaw-plugin --force
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

## Architecture

```text
OpenClaw Gateway
  -> TypeScript plugin hooks
  -> localhost HTTP/JSON
  -> Python scheduler sidecar
     -> SQLite events
     -> realtime tool runtime samples
     -> static prediction + calibration
     -> admission policy
     -> topology inventory
     -> metrics
```

The plugin never sends full prompts, model responses, raw tool output, or raw
tool parameters by default. Raw parameters require explicit `sendRawParams=true`
and still pass recursive redaction.

## Modes

`observe` mode always lets tools run, even if the sidecar blocks or is down.
`enforce` mode applies sidecar decisions. If the sidecar is unavailable,
`failOpen=true` allows the call and `failOpen=false` blocks it with a clear
reason.

## Contracts

JSON Schema files live under `contracts/`. Python models and TypeScript types
mirror those schemas, and tests validate examples across both sides.

## agent-test-bench Integration

The existing `C:\Users\29068\Desktop\agent-test-bench` repository remains a
research and evaluation source. This project reads exported canonical
`trace.jsonl` files and can generate scheduler tool profiles from `tool_exec`
spans, but does not import its AgentLoop, benchmark runner, or agent scaffold
into the online plugin runtime.

At runtime, the OpenClaw plugin sends tool start/completion events to the
sidecar. The sidecar stores correlated runtime samples in SQLite and exposes the
latest samples at `GET /v1/tools/recent`; Prometheus metrics are exposed at
`GET /metrics`.
