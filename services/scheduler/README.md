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
