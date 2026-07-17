# agent-test-bench Integration

Read-only source repository:

`AGENT_TEST_BENCH_ROOT` or a sibling checkout such as `../agent-test-bench`.

Relevant findings:

- Canonical traces are JSONL files named `trace.jsonl`.
- `trace_metadata` records use `trace_format_version: 5`.
- Tool actions use `action_type: "tool_exec"`.
- The benchmark repository has resource measurement and replay machinery under
  `src/trace_collect` and `src/harness`, but those modules are not online
  runtime dependencies for this project.
- Online plugin runtime now performs lightweight real-time monitoring from
  OpenClaw tool lifecycle events. This is intentionally smaller than the full
  benchmark profiler stack.

Importer:

```bash
python3 tools/import_agent_test_bench_trace.py input-trace.jsonl output-events.jsonl --dry-run
python3 tools/import_agent_test_bench_trace.py input-trace.jsonl output-events.jsonl \
  --profiles-out tool-profiles.generated.json
```

Benchmark adapter:

```bash
python3 tools/run_agent_test_bench.py -- \
  --provider deepseek --model deepseek-chat \
  --benchmark swe-rebench --scaffold openclaw \
  --container docker --mcp-config none \
  --sample 1
```

Everything after `--` is passed unchanged to
`python3 -m trace_collect.cli` inside the `agent-test-bench` repository. This
preserves benchmark CLI usage, trace layout, and image handling.

The importer maps canonical tool execution spans into offline
`ToolCompletedEvent` records when duration information is available. It can
also aggregate observed `tool_exec` durations into scheduler-compatible static
tool profiles.

## Feature Mapping

agent-test-bench capability | Scheduler integration
---|---
Canonical `trace.jsonl` | Imported with `tools/import_agent_test_bench_trace.py`.
Benchmark CLI | Delegated with `tools/run_agent_test_bench.py`; arguments after `--` are passed verbatim to `trace_collect.cli`.
`trace_format_version: 5` metadata | Read to preserve `run_id` when available.
OpenClaw `tool_exec` actions | Converted to `ToolCompletedEvent` and profile samples.
Classified exec names such as `exec-pytest` | `exec-*` suffix becomes profile `operation`.
Trace simulate / replay | Remains offline in agent-test-bench; scheduler consumes exported traces/profiles only.
Resource monitoring samples | Online sidecar now follows the same attribution rule: sample the target PID/process tree when available, otherwise mark the sample `unattributed`.
VTune / ksys per-tool profiling | Remains offline; scheduler should consume summarized profile exports, not launch profilers.
HTML visualization | Remains in agent-test-bench.
Benchmark/container orchestration | Remains in agent-test-bench and is not imported by the online sidecar.
Agent scaffold / AgentLoop | Not imported. OpenClaw native hooks are the online integration point.
Real-time OpenClaw tool monitoring | Implemented in the scheduler sidecar via `/v1/decisions/tool`, `/v1/events/tool-completed`, `/v1/tools/recent`, and Prometheus metrics.
`exec` command classification | Ported into the scheduler as `operation_hint` / `operation` matching so `exec` + `python -m pytest` can reuse `exec-pytest` profiles.

## Development Contract

For future agent-test-bench work, prefer exporting one or both of:

1. Canonical `trace.jsonl` files with `tool_exec` actions and timestamps.
2. Scheduler profile files matching `contracts/tool-profile.schema.json`.

The online sidecar should never import benchmark runners, container managers,
AgentLoop classes, or visualization modules. That keeps production plugin
behavior small and deterministic while still letting the
research repository feed it real workload measurements.

The boundary is:

- agent-test-bench produces offline traces, profile summaries, and richer
  profiler-derived labels.
- The OpenClaw plugin produces online lifecycle events.
- The scheduler sidecar joins online lifecycle events with local predictions,
  stores live runtime samples, and exposes operational metrics.

Suggested future profile export contract:

```json
{
  "profile_version": "1",
  "profiles": [
    {
      "tool_name": "exec",
      "operation": "pytest",
      "resource_class": "cpu_memory_mixed",
      "duration_p50_ms": 1500,
      "duration_p90_ms": 4000
    }
  ]
}
```
