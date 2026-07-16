# agent-test-bench Integration

Read-only source repository inspected:

`C:\Users\29068\Desktop\agent-test-bench`

Relevant findings:

- Canonical traces are JSONL files named `trace.jsonl`.
- `trace_metadata` records use `trace_format_version: 5`.
- Tool actions use `action_type: "tool_exec"`.
- The benchmark repository has resource measurement and replay machinery under
  `src/trace_collect` and `src/harness`, but those modules are not online
  runtime dependencies for this project.

Importer:

```bash
python tools/import_agent_test_bench_trace.py input-trace.jsonl output-events.jsonl --dry-run
```

The importer maps canonical tool execution spans into offline
`ToolCompletedEvent` records when duration information is available. Fields
that cannot be mapped are reported in the import statistics.

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
