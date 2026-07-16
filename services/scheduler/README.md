# Scheduler Sidecar

Run:

```bash
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Configuration uses environment variables:

- `AGENT_SCHEDULER_DB_PATH`
- `AGENT_SCHEDULER_POLICY`
- `AGENT_SCHEDULER_MAX_GLOBAL_CONCURRENCY`
- `AGENT_SCHEDULER_LEASE_TTL_MS`
- `AGENT_SCHEDULER_ADMISSION_WAIT_MS`
- `AGENT_SCHEDULER_TOOL_PROFILES`
- `AGENT_SCHEDULER_TOKEN`

Runtime inspection:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
```

`/v1/tools/recent` returns the latest correlated OpenClaw tool runtime samples.
If OpenClaw provides `resource_scope.pid`, samples and metrics include
PID process-tree CPU, RSS, IO, and context-switch measurements. Without a PID,
the sample is explicitly marked `unattributed`.
