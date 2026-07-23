# Trace Schema v6

## Overview

Every LLM call and tool execution is modeled as a **span**. Each span is
written as two JSONL records: `span_start` (before execution) and `span_end`
(after completion). One trace file captures all tool/LLM input, output, and
resource usage.

**This is the only trace format. There is no backwards compatibility layer.**

- Action start is recorded even if the process crashes before completion
- Explicit `parent_span_id` links tool spans to the LLM call that produced them
- Monotonic clock is used for duration, not wall clock
- Resource monitoring coverage is explicitly tracked
- Tool arguments use the before-hook values as the source of truth

## File Format

The trace is a JSONL file (one JSON object per line). Each line is a
self-contained event. Line order does NOT encode parent-child relationships.

### Record Types

| `record_type`      | Description |
|---------------------|-------------|
| `trace_metadata`    | File header with version, clock info, timestamp |
| `span_start`        | Written immediately when a span begins |
| `span_end`          | Written when a span completes |

## Span Identity

All span records share these fields:

```json
{
  "schema_version": 6,
  "record_type": "span_start",
  "trace_id": "run-id",
  "span_id": "stable-action-id",
  "parent_span_id": null,
  "session_id": "session-id",
  "run_id": "run-id",
  "agent_id": "main",
  "sequence_no": 1,
  "kind": "llm",
  "name": "model-name-or-tool-name",
  "wall_time_ns": "1784796575290404608",
  "monotonic_time_ns": "123456789"
}
```

### Field Descriptions

- **trace_id**: Defaults to `run_id`. Groups related spans.
- **span_id**: Unique ID for one LLM call or tool execution within a trace.
  LLM spans use `call_id` from OpenClaw if available. Tool spans use
  `tool_call_id` from OpenClaw.
- **parent_span_id**: For tool spans, points to the LLM span that produced
  the tool call. For top-level LLM spans, this is `null`.
- **sequence_no**: Monotonically increasing per-run, assigned by the plugin.
  Used for stable ordering only — NOT for inferring parent-child relationships.
- **kind**: `"llm"` or `"tool"`.
- **name**: Model name for LLM spans; tool name for tool spans.
- **wall_time_ns**: Unix wall-clock time in nanoseconds (for display and
  cross-component alignment). Serialized as a string to preserve precision
  beyond IEEE 754 limits.
- **monotonic_time_ns**: Monotonic clock time in nanoseconds (for duration
  calculations). Uses `process.hrtime.bigint()` in Node.js.

### Clock Sources

- Wall clock: `Date.now() * 1e6 + sub-ms offset from process.hrtime()`
- Monotonic: `process.hrtime.bigint()`
- Precision: nanosecond (best-effort); actual precision is microsecond-range
  on most platforms.

## span_start

Written before the actual execution begins. The plugin must flush this record
so it survives even if the process crashes.

```json
{
  "schema_version": 6,
  "record_type": "span_start",
  "trace_id": "run-1",
  "span_id": "tool-call-abc",
  "parent_span_id": "llm-span-1",
  "session_id": "sess-1",
  "run_id": "run-1",
  "agent_id": "main",
  "sequence_no": 2,
  "kind": "tool",
  "name": "exec",
  "wall_time_ns": "1784796575290404608",
  "monotonic_time_ns": "123456789",
  "input": {
    "requested_args": {
      "command": "python3 script.py",
      "timeout": 30
    }
  },
  "execution": {
    "mode": "launcher",
    "execution_id": "exec-123"
  }
}
```

### input.requested_args

The ACTUAL arguments received by the tool's `before_tool_call` hook. This is
the **sole source of truth** for tool parameters. Do NOT use:
- Streamed LLM response `function.arguments`
- `raw_response` from the model hook
- Post-hoc parsed model text

### input.messages (LLM spans only)

Snapshot of the messages sent to the LLM. Configurable via
`trace.include_llm_messages`.

## span_end

Written after the span completes. Must use monotonic clock for duration.

```json
{
  "schema_version": 6,
  "record_type": "span_end",
  "trace_id": "run-1",
  "span_id": "tool-call-abc",
  "parent_span_id": "llm-span-1",
  "session_id": "sess-1",
  "run_id": "run-1",
  "agent_id": "main",
  "sequence_no": 2,
  "kind": "tool",
  "name": "exec",
  "wall_time_ns": "1784796577436404480",
  "monotonic_time_ns": "2269456789",
  "duration_ns": "2146000000",
  "status": {"code": "ok", "message": null},
  "output": {"exit_code": 0, "result": "..."},
  "execution": {
    "mode": "launcher",
    "execution_id": "exec-123",
    "requested_command": "python3 script.py",
    "effective_command": "claw-launch run ...",
    "payload_command": "python3 script.py",
    "payload_pid": 1282991,
    "payload_pid_start_time_ticks": 123456789,
    "cgroup_path": "/sys/fs/cgroup/claw/exec_123",
    "pid_role": "payload_root"
  },
  "resources": {
    "attribution_status": "partially_attributed",
    "scope": "process_tree",
    "quality": "partial",
    "monitor_start_wall_time_ns": null,
    "monitor_end_wall_time_ns": null,
    "monitor_start_monotonic_ns": null,
    "monitor_end_monotonic_ns": null,
    "coverage_duration_ns": null,
    "action_duration_ns": "2146000000",
    "coverage_ratio": null,
    "coverage_reason": "pid_registered_late",
    "cpu_time_s": 0.17,
    "rss_peak_bytes": 49913856
  }
}
```

### Status Codes

| Code | Meaning |
|------|---------|
| `ok` | Normal completion |
| `error` | Executor threw an exception |
| `timeout` | OpenClaw timeout |
| `cancelled` | User or runtime cancelled |
| `interrupted` | SIGTERM/SIGINT caught |
| `unknown` | Cannot determine final state |

### Incomplete Spans

If the plugin process crashes, `span_start` records may exist without
corresponding `span_end` records. These are **incomplete spans**. The trace
validator reports them. Do NOT fabricate fake `span_end` records to fill gaps.

On normal plugin shutdown, any still-active spans are closed with
`status.code: "interrupted"`.

### Command Variants

For tool spans using the launcher, three command variants are distinguished:

| Field | Meaning |
|-------|---------|
| `requested_command` | The original command the agent asked to run |
| `effective_command` | What OpenClaw actually executes (e.g. `claw-launch run ...`) |
| `payload_command` | What the launcher ultimately executes inside the sandbox |

### Resource Attribution

| `attribution_status` | Meaning |
|----------------------|---------|
| `attributed` | PID and/or cgroup successfully monitored |
| `partially_attributed` | Partial monitoring (e.g. late PID registration) |
| `unattributed` | No PID available (e.g. native tools) |
| `failed` | Monitor had an error |
| `not_applicable` | Resource monitoring not relevant (e.g. LLM spans) |
| `unknown` | Cannot determine attribution |

### Monitor Quality

| Value | Meaning |
|-------|---------|
| `complete` | Monitor window fully covers the action |
| `partial` | Monitor covers only part of the action |
| `unknown` | Coverage cannot be determined |

### Coverage Calculation

```
coverage_duration_ns = max(0, min(action_end, monitor_end) - max(action_start, monitor_start))
coverage_ratio = coverage_duration_ns / action_duration_ns
```

### Coverage Reasons

| Reason | Description |
|--------|-------------|
| `full_window` | Monitor covered the entire action |
| `pid_registered_late` | PID was registered after action started |
| `monitor_stopped_early` | Monitor stopped before action ended |
| `pid_unavailable` | No PID could be obtained |
| `cgroup_unavailable` | cgroup path not available |
| `monitor_error` | Monitor encountered an error |
| `clock_data_missing` | Clock timestamps not available |

## Native Tools (No PID)

For OpenClaw native tools like `read_file`, `write`, etc. that run in-process
without a separate PID:

```json
{
  "execution": {
    "mode": "in_process_or_runtime_managed",
    "payload_pid": null
  },
  "resources": {
    "attribution_status": "unattributed",
    "quality": "unknown",
    "coverage_reason": "pid_unavailable"
  }
}
```

These spans still have complete `span_start` / `span_end` records with timing
and status information.

## PID Reuse Protection

In addition to the PID, the `payload_pid_start_time_ticks` field (from
`/proc/<pid>/stat`) is recorded. This prevents misattribution when PIDs are
reused by the kernel.

## Parent-Child Mapping

When an LLM response contains tool calls:

1. The plugin extracts `tool_call_id` values from the model response.
2. Each `tool_call_id` is mapped to the current LLM span's `span_id`.
3. When `before_tool_call` fires for each tool, the plugin looks up the
   parent `span_id` using the `tool_call_id`.

If the parent cannot be resolved, `parent_span_id` is set to `null` and a
`correlation` diagnostic is added.

## Sensitive Data Redaction

The trace sanitizer redacts:
- Field names containing `token`, `api_key`, `secret`, `password`, etc.
- `Authorization: Bearer ...` headers
- `--token=...` command-line flags
- Environment variables with `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CLAW_*`, etc.

Redaction operates on trace WRITE copies only — the actual tool execution
uses the original values.

## Configuration

```json
{
  "trace": {
    "schema_version": 6,
    "include_raw_events": false,
    "include_llm_messages": true,
    "include_tool_outputs": true,
    "redact_sensitive_data": true,
    "flush_span_start": true,
    "max_string_bytes": 16384,
    "max_messages_bytes": 131072,
    "max_tool_output_bytes": 65536,
    "trace_dir": "/var/log/claw/traces"
  }
}
```

- `trace_dir`: Set to a writable directory. Each run produces its own file
  named `{agent_id}_{session_id}_{run_id}.jsonl`. Empty string disables tracing.

### Scheduler sidecar configuration

Set the environment variable:
```bash
export AGENT_SCHEDULER_TRACE_DIR=/var/log/claw/traces
```

The scheduler writes to the same per-run file pattern.

## Validator

```bash
# TypeScript (in tests)
node --test test/trace-v6.test.mjs

# Python CLI
python scripts/validate_trace.py trace.jsonl
python scripts/validate_trace.py -q trace.jsonl
```

The validator checks:
- JSONL line validity
- Schema version
- Start/end pairing
- Duplicate ends
- Ends without starts
- Incomplete spans
- Non-negative durations
- Coverage ratios in [0,1]
- Possible plaintext secrets

Example output:

```
Trace validation summary

records: 42
spans (from starts): 20
complete spans: 19
incomplete spans: 1
unresolved parents: 0
duplicate ends: 0
ends without starts: 0
invalid coverage ratios: 0
possible secret leaks: 0
duration mismatches: 0
inconsistent span identity: 0

VALID WITH WARNINGS
```

## Complete Example: LLM → 2 Parallel Tools → LLM

### trace_metadata
```json
{"schema_version":6,"record_type":"trace_metadata","trace_format_version":6,"scaffold":"openclaw","mode":"collect","created_at":"2026-07-23T00:00:00Z","clock_source":"Date.now() + process.hrtime() for wall clock; process.hrtime.bigint() for monotonic","clock_precision":"nanosecond (best-effort)"}
```

### Span 1: LLM call (generates 2 tool calls)
```json
{"schema_version":6,"record_type":"span_start","trace_id":"run-1","span_id":"call-llm-1","parent_span_id":null,"session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":1,"kind":"llm","name":"claude-sonnet-4-20250514","wall_time_ns":"1784796575000000000","monotonic_time_ns":"100000000","input":{"requested_args":null,"messages":[{"role":"user","content":"List files and check disk space"}]},"execution":{"mode":null,"execution_id":null}}
```

```json
{"schema_version":6,"record_type":"span_end","trace_id":"run-1","span_id":"call-llm-1","parent_span_id":null,"session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":1,"kind":"llm","name":"claude-sonnet-4-20250514","wall_time_ns":"1784796577000000000","monotonic_time_ns":"2100000000","duration_ns":"2000000000","status":{"code":"ok","message":null},"output":{"content":"I'll run those commands for you."},"execution":{"mode":null,"execution_id":null},"resources":{"attribution_status":"not_applicable","scope":"none","quality":"unknown","monitor_start_wall_time_ns":null,"monitor_end_wall_time_ns":null,"monitor_start_monotonic_ns":null,"monitor_end_monotonic_ns":null,"coverage_duration_ns":null,"action_duration_ns":"2000000000","coverage_ratio":null,"coverage_reason":"pid_unavailable"}}
```

### Span 2: exec tool (via launcher, partial resource coverage)
```json
{"schema_version":6,"record_type":"span_start","trace_id":"run-1","span_id":"toolu_01ABC123","parent_span_id":"call-llm-1","session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":2,"kind":"tool","name":"exec","wall_time_ns":"1784796577100000000","monotonic_time_ns":"2200000000","input":{"requested_args":{"command":"ls -la /data","timeout":30}},"execution":{"mode":"launcher","execution_id":"exec-001"},"correlation":{"status":"resolved"}}
```

```json
{"schema_version":6,"record_type":"span_end","trace_id":"run-1","span_id":"toolu_01ABC123","parent_span_id":"call-llm-1","session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":2,"kind":"tool","name":"exec","wall_time_ns":"1784796578500000000","monotonic_time_ns":"3600000000","duration_ns":"1400000000","status":{"code":"ok","message":null},"output":{"exit_code":0,"result":"total 48\ndrwxr-xr-x ..."},"execution":{"mode":"launcher","execution_id":"exec-001","requested_command":"ls -la /data","effective_command":"'/opt/claw/bin/claw-launch' run --execution-id='exec-001' --token='<redacted>'","payload_command":"ls -la /data","payload_pid":1282991,"payload_pid_start_time_ticks":99123456,"cgroup_path":"/sys/fs/cgroup/claw/exec_001","pid_role":"payload_root"},"resources":{"attribution_status":"partially_attributed","scope":"process_tree","quality":"partial","monitor_start_wall_time_ns":null,"monitor_end_wall_time_ns":null,"monitor_start_monotonic_ns":null,"monitor_end_monotonic_ns":null,"coverage_duration_ns":null,"action_duration_ns":"1400000000","coverage_ratio":null,"coverage_reason":"pid_registered_late","cpu_time_s":0.15,"rss_peak_bytes":12390400}}
```

### Span 3: write tool (native, no PID)
```json
{"schema_version":6,"record_type":"span_start","trace_id":"run-1","span_id":"toolu_02DEF456","parent_span_id":"call-llm-1","session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":3,"kind":"tool","name":"write","wall_time_ns":"1784796577150000000","monotonic_time_ns":"2250000000","input":{"requested_args":{"file_path":"/tmp/report.txt","content":"Disk OK"}},"execution":{"mode":"in_process_or_runtime_managed","execution_id":null},"correlation":{"status":"resolved"}}
```

```json
{"schema_version":6,"record_type":"span_end","trace_id":"run-1","span_id":"toolu_02DEF456","parent_span_id":"call-llm-1","session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":3,"kind":"tool","name":"write","wall_time_ns":"1784796577200000000","monotonic_time_ns":"2300000000","duration_ns":"50000000","status":{"code":"ok","message":null},"output":{"exit_code":0,"result":"File written successfully"},"execution":{"mode":"in_process_or_runtime_managed","execution_id":null,"payload_pid":null},"resources":{"attribution_status":"unattributed","scope":"none","quality":"unknown","monitor_start_wall_time_ns":null,"monitor_end_wall_time_ns":null,"monitor_start_monotonic_ns":null,"monitor_end_monotonic_ns":null,"coverage_duration_ns":null,"action_duration_ns":"50000000","coverage_ratio":null,"coverage_reason":"pid_unavailable"}}
```

### Span 4: Final LLM call (summarizes results)
```json
{"schema_version":6,"record_type":"span_start","trace_id":"run-1","span_id":"call-llm-2","parent_span_id":null,"session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":4,"kind":"llm","name":"claude-sonnet-4-20250514","wall_time_ns":"1784796578600000000","monotonic_time_ns":"3700000000","input":{"requested_args":null,"messages":[{"role":"user","content":"List files and check disk space"},{"role":"assistant","content":"I'll run those commands for you."},{"role":"user","content":"[tool result: ls output...]"},{"role":"user","content":"[tool result: File written successfully]"}]},"execution":{"mode":null,"execution_id":null}}
```

```json
{"schema_version":6,"record_type":"span_end","trace_id":"run-1","span_id":"call-llm-2","parent_span_id":null,"session_id":"sess-1","run_id":"run-1","agent_id":"main","sequence_no":4,"kind":"llm","name":"claude-sonnet-4-20250514","wall_time_ns":"1784796580000000000","monotonic_time_ns":"5100000000","duration_ns":"1400000000","status":{"code":"ok","message":null},"output":{"content":"Here's a summary..."},"execution":{"mode":null,"execution_id":null},"resources":{"attribution_status":"not_applicable","scope":"none","quality":"unknown","monitor_start_wall_time_ns":null,"monitor_end_wall_time_ns":null,"monitor_start_monotonic_ns":null,"monitor_end_monotonic_ns":null,"coverage_duration_ns":null,"action_duration_ns":"1400000000","coverage_ratio":null,"coverage_reason":"pid_unavailable"}}
```

## Known Limitations

1. **Native tools without independent PID**: OpenClaw native tools like
   `write`, `read_file` run in-process. Without modifying OpenClaw core,
   they cannot have independently attributed resource usage.

2. **Plugin SIGKILL**: If the plugin process receives SIGKILL, `span_end`
   cannot be written. The `span_start` survives but the span is incomplete.
   Normal shutdown (SIGTERM) is handled.

3. **Wall clock alignment**: Cross-process wall clock alignment depends on
   system NTP. Monotonic clocks are always preferred for duration.

4. **Partial resource coverage**: When PID is registered late, the coverage
   ratio reflects the monitor window, not the tool's full resource consumption.
   The `coverage_reason` field indicates why coverage is incomplete.

5. **LLM proxy traces**: The Python scheduler sidecar's LLM proxy capture
   (in `trace.py`) generates its own trace records. These are not yet
   integrated into the v6 span model and are produced independently.

6. **Message de-duplication**: The plugin now avoids storing duplicate
   messages in both `messages_in` and `raw_request.messages`. Only
   `input.messages` is written when `include_llm_messages` is true.
