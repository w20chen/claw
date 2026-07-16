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
- `POST /v2/executions`
- `POST /v2/executions/claim`
- `POST /v2/executions/{execution_id}/started`
- `POST /v2/executions/{execution_id}/exited`
- `GET /v2/executions/{execution_id}/scope`

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
- cgroup-v2 CPU time, memory, I/O, process count, and context-switch deltas
  when a trusted scope includes `kind: "cgroup-v2"` and `cgroup_path`
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

## Managed Execution Registration

`POST /v2/executions` stores a one-time execution spec in memory. The Python
reference launcher, exposed as the `claw-launch` console script, calls
`POST /v2/executions/claim` with the one-time token, receives the original
command, then reports:

- `started`: child PID, optional cgroup path, PID namespace inode
- `exited`: original process exit code or signal

The one-time claim token is consumed on first use. The sidecar returns a
separate `update_token` for `started` and `exited`. Raw commands are not
persisted to SQLite.

When `CLAW_CGROUP_ROOT` is set on Linux and writable, the reference launcher
creates a per-execution cgroup and reports a cgroup-v2 scope. The runtime
sampler then reads `cpu.stat`, `memory.current`, `io.stat`, and `cgroup.procs`
directly. Without that cgroup path, the launcher registers a PID scope. Calls
without any trusted scope are recorded as `attribution_status: "unattributed"`
rather than misattributing sidecar process metrics to the tool.
