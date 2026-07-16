# Supported Features

This page states what is currently supported and how to verify it. For the
full run sequence, use [operator-guide.md](operator-guide.md).

## Feature Matrix

| Area | Status | Notes |
| --- | --- | --- |
| JSON contracts | Supported | `contracts/` is the protocol source of truth. |
| Sidecar health/status | Supported | `/health/live`, `/health/ready`, `/v1/status`. |
| Tool decisions | Supported | Observe-only and bounded concurrency policies. |
| Tool completions | Supported | Idempotent SQLite persistence. |
| Model events | Supported | Stored and optionally written to trace. |
| Runtime samples | Supported | CPU, RSS, disk I/O, network I/O, context switches when scoped. |
| Live `trace.jsonl` | Supported | Enable with `AGENT_SCHEDULER_TRACE_PATH`. |
| agent-test-bench format | Supported | v5-shaped records; raw content requires `recordRawTrace=true`. |
| Plugin hooks | Supported | `before_tool_call`, `after_tool_call`, model start/end. |
| `exec` hook-only | Supported | No param rewrite. |
| `exec` marker mode | Supported | Adds correlation env vars. |
| `exec` managed-wrapper | Supported | Uses sidecar registration plus `claw-launch`. |
| PID/cgroup attribution | Supported | Best with managed-wrapper or explicit `resource_scope`. |
| Linux CPU placement | Reference only | cpuset/affinity path exists; scheduling policy is not optimized. |
| CPU-side scheduling optimization | Not implemented | Do not treat current policy as hardware optimizer. |
| NUMA/PMU/GPU/KV scheduling | Not implemented | Future work. |

## Resource Monitoring Boundary

Every completed tool event can produce a trace action and duration sample.
Resource fields are populated only when a trusted process scope exists:

- PID scope: process-tree CPU/RSS/disk/context-switch sampling via `psutil`.
- cgroup-v2 scope: cgroup CPU, memory, I/O, and process count files.
- network I/O: best-effort `/proc/<pid>/net/dev` namespace counters.
- no scope: sample is `unattributed`; resource values are `null`.

The sidecar never substitutes its own process metrics for tool metrics.

## Quick Verification

Contracts:

```bash
python3 tools/validate_contracts.py
```

Sidecar and demo:

```bash
cd services/scheduler
PYTHONPATH=src AGENT_SCHEDULER_TRACE_PATH=../../data/trace.jsonl \
  python3 -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

In another shell:

```bash
python3 tools/demo_supported_features.py --run-launcher
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
tail -n 20 data/trace.jsonl
```

Plugin:

```bash
cd packages/openclaw-plugin
npm test
npm run typecheck
```

Scheduler tests:

```bash
cd services/scheduler
python3 -m pytest tests -q
```

Root tests:

```bash
python3 -m pytest tests -q --basetemp .pytest-tmp-root
```

## Expected Trace Shape

```json
{"type":"trace_metadata","trace_format_version":5,"scaffold":"openclaw","mode":"collect"}
{"type":"action","action_type":"llm_call","action_id":"...","data":{"messages_in":[...],"content":"...","llm_latency_ms":1234.0}}
{"type":"action","action_type":"tool_exec","action_id":"...","data":{"tool_name":"exec","tool_args":{"command":"pytest"},"tool_result":"...","resource_usage":{"attribution_status":"pid"}}}
```

The plugin records raw model/tool content only when `recordRawTrace=true`.
