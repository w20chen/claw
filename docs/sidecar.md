# Scheduler Sidecar

The sidecar package is `services/scheduler`.

Endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/status`
- `GET /metrics`
- `GET /v1/tools/recent`
- `POST /v1/decisions/tool`
- `POST /v1/events/tool-completed`
- `POST /v1/events/model`

SQLite is used for lightweight persistence. Writes are parameterized and use
idempotent keys so duplicate events do not crash the service.

## Real-time Tool Monitoring

When the plugin calls `POST /v1/decisions/tool` and the sidecar allows the tool,
the sidecar opens an in-memory monitoring window keyed by `tool_call_id`.
When `POST /v1/events/tool-completed` arrives, the sidecar closes that window,
stores a `tool_runtime_samples` row, and updates Prometheus counters/gauges.

Stored sample fields include:

- `tool_call_id`, `tool_name`, and derived `operation`
- `operation_hint`, a privacy-preserving command category such as `pytest`,
  `grep`, or `git`
- user-visible `duration_ms` from the completion event
- sidecar-observed `monitor_duration_ms`
- `target_pid`, process counts, and `attribution_status`
- PID process-tree CPU time delta, RSS before/after, IO byte deltas, and
  context-switch deltas when `resource_scope.pid` is present and `psutil` can
  read it
- predicted `resource_class`

Inspect the most recent samples:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
```

Useful metrics:

- `scheduler_tool_runtime_samples_total`
- `scheduler_tool_runtime_pid_samples_total`
- `scheduler_tool_runtime_unattributed_samples_total`
- `scheduler_tool_runtime_pid_unavailable_samples_total`
- `scheduler_active_tool_monitors`
- `scheduler_tool_cpu_seconds_total`
- `scheduler_tool_memory_rss_bytes`
- `scheduler_tool_process_count`
- `scheduler_tool_io_read_bytes_total`
- `scheduler_tool_io_write_bytes_total`
- `scheduler_tool_context_switches_total`

Current limitation: OpenClaw may not expose a tool PID for every hook payload.
In that case the sidecar records `attribution_status: "unattributed"` and keeps
duration/prediction telemetry, but it does not misattribute sidecar process
metrics to the tool. Precise cgroup/container accounting should be added once
OpenClaw exposes execution-layer metadata or this project owns a managed
executor.
