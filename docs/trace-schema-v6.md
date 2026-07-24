# Trace Output

Traces are JSONL files. With `.env.example`, they are written under:

```text
data/traces/*.jsonl
```

SWE-Rebench traces are written under:

```text
swe_rebench/traces/<task_id>/*.jsonl
```

Inspect traces:

```bash
python tools/inspect_trace.py data/traces/<trace-file>.jsonl --all --details
python tools/inspect_trace.py data/traces/<trace-file>.jsonl --all --timeline
```

Expected record types:

```json
{"schema_version":6,"record_type":"trace_metadata","trace_format_version":6}
{"schema_version":6,"record_type":"span_start","kind":"llm","name":"..."}
{"schema_version":6,"record_type":"span_end","kind":"tool","name":"exec"}
```

Useful fields:

- `input.messages`: LLM request messages when proxy capture is active.
- `output.content`: LLM or tool output.
- `input.requested_args`: tool input when `recordRawTrace: true`.
- `resources.attribution_status`: resource attribution status.
- `resources.cpu_time_s`, `resources.rss_peak_bytes`: sampled resource data.

Coverage reasons distinguish attribution failures from expected shared scopes:

- `not_applicable`: no local payload process applies, e.g. LLM spans.
- `internal_tool_no_process`: an in-process tool had no PID/cgroup scope.
- `shared_runtime_process`: an internal tool was sampled through the shared
  OpenClaw runtime process, not a dedicated tool process.
- `monitor_window_no_overlap`: a PID/cgroup existed, but the sampler did not
  capture an overlapping resource window.

The JSON Schema contracts remain the source of truth for protocol details.
