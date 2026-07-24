# Scheduler Sidecar

The sidecar package is `services/scheduler`.

Endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/status`
- `GET /metrics`
- `GET /v1/tools/recent`
- `GET /v1/models`
- `GET /models`
- `POST /v1/chat/completions`
- `POST /chat/completions`
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

## LLM Proxy

The sidecar includes an OpenAI-compatible proxy and this is the default path
for complete LLM trace capture. The validated OpenClaw setup is to onboard an
OpenAI-compatible local provider with `vllm` mode and point its custom base URL
at the sidecar:

```bash
export DEEPSEEK_API_KEY='<your-deepseek-api-key>'
openclaw onboard --non-interactive --accept-risk \
  --mode local \
  --auth-choice vllm \
  --custom-base-url 'http://127.0.0.1:8765/v1' \
  --custom-api-key "$DEEPSEEK_API_KEY" \
  --custom-model-id 'deepseek-v4-flash'
# Add --skip-health if you only use 'openclaw agent --local' (no gateway).
```

Use the model as `vllm/deepseek-v4-flash`.

DeepSeek is the built-in upstream default. For a different OpenAI-compatible
provider, configure the real upstream provider on the sidecar:

```bash
AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL=http://127.0.0.1:8000/v1
```

The built-in DeepSeek default is `https://api.deepseek.com`. If OpenClaw logs
still show requests going directly to `https://api.deepseek.com/...`, the
sidecar proxy is not receiving LLM traffic yet.

The proxy forwards OpenClaw's `Authorization` header by default, so do not
duplicate API keys in sidecar config unless OpenClaw does not send auth to the
proxy. Use `AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY` only as an explicit override.
For the `vllm` proxy-to-DeepSeek setup, setting this override in `.env` is the
most explicit option:

```bash
AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL=https://api.deepseek.com
AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY=<your-deepseek-api-key>
```

Restart the sidecar after editing `.env`.

The proxy forwards `/v1/models` and `/v1/chat/completions` to the upstream
provider. Non-streaming and streaming chat completions are recorded as schema
v6 LLM spans. Streaming responses are stored as one reconstructed assistant
message; individual SSE chunks are not written to the trace.

When the proxy is working, OpenClaw logs show:

```text
url=http://127.0.0.1:8765/v1/chat/completions
```

The sidecar writes these default files relative to the repository root when
using `.env.example`:

- `data/openclaw-trace.sqlite3`: SQLite persistence for sidecar state,
  decisions, completions, model events, and runtime samples.
- `data/traces/*.jsonl`: append-only span traces with `trace_metadata`,
  `span_start`, and `span_end` records.

### Model Name Spoofing

OpenClaw's provider discovery (vllm, openai, etc.) fetches `/v1/models` and
validates the response against its internal provider registry. Upstream model
metadata (e.g. `owned_by: "deepseek"`) can cause a **provider mismatch** error
even when the model list is otherwise correct.

**By default, the sidecar automatically normalises the upstream `/v1/models`
response**: every model entry's `owned_by` is rewritten to `"organization"`,
which passes all OpenAI-compatible provider checks.  No configuration is
needed for this — it happens transparently on every request.

For advanced cases where you need to expose a different model name to OpenClaw
than the real upstream model (e.g. exposing `gpt-4o` while actually calling
`deepseek-v4-flash`), set:

```bash
# Model ID that OpenClaw sees in /v1/models.
AGENT_SCHEDULER_LLM_PROXY_EXPOSE_MODEL=gpt-4o

# Real model ID sent to the upstream API.
AGENT_SCHEDULER_LLM_PROXY_UPSTREAM_MODEL=deepseek-v4-flash
```

When `EXPOSE_MODEL` is set, `/v1/models` returns a synthetic single-model list
(no upstream call).  Chat completion requests with `model=<EXPOSE_MODEL>` are
rewritten to `model=<UPSTREAM_MODEL>` before forwarding.

When both vars are set to the same value, the proxy returns a clean synthetic
model list with no name translation — useful when the upstream `/models`
endpoint is unreachable or returns a format the normaliser cannot parse.

## Real-time Tool Monitoring

When the plugin calls `POST /v1/decisions/tool` and the sidecar allows the tool,
the sidecar opens an in-memory monitoring window keyed by `tool_call_id`.
When `POST /v1/events/tool-completed` arrives, the sidecar closes that window,
stores a `tool_runtime_samples` row, and updates Prometheus counters/gauges.
By default, scoped tools are polled every 50 ms. Tune this with
`AGENT_SCHEDULER_RESOURCE_POLL_INTERVAL_MS`. Lower values can catch shorter
tools, at the cost of more sidecar overhead.

The sidecar writes one aggregate runtime sample when the tool completes. It
also stores a compact per-tool `resource_timeline` inside that final sample,
up to `AGENT_SCHEDULER_RESOURCE_TIMELINE_MAX_POINTS` points. Timeline points
are normalized to relative deltas and interval rates; raw network namespace
counters are not shown as absolute byte totals. The sidecar does not append one
JSONL record per polling tick.

Stored sample fields include:

- `tool_call_id`, `tool_name`, and derived `operation`
- `operation_hint`, a command category such as `pytest`,
  `grep`, or `git`
- user-visible `duration_ms` from the completion event
- sidecar-observed `monitor_duration_ms`
- `target_pid`, process counts, and `attribution_status`
- PID process-tree CPU time delta, RSS before/after, IO byte deltas, and
  context-switch deltas when `resource_scope.pid` is present and `psutil` can
  read it
- average CPU utilization in cores and percent over the tool duration
- observed peak RSS, tracked across poll samples
- average disk and network throughput in bytes/second
- sampling metadata: interval, point count, quality, and timeline truncation
- cgroup-v2 CPU time, memory, I/O, process count, and context-switch deltas
  when a trusted scope includes `kind: "cgroup-v2"` and `cgroup_path`.
  cgroup monitoring is enabled by default on Linux when the launcher can create
  or use a delegated cgroup; see [Operator Guide](operator-guide.md#7-cgroup-notes).
- best-effort network rx/tx deltas from `/proc/<pid>/net/dev`
- predicted `resource_class`

For cgroup-v2 scopes, network counters are treated as auxiliary data only. A
sample is considered `cgroup-v2` only when at least one core cgroup metric is
available, such as CPU usage, memory, I/O, process membership, or context
switches. If not, the sampler falls back to PID/process-tree sampling.

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
- `scheduler_tool_memory_rss_peak_bytes`
- `scheduler_tool_cpu_utilization_avg_cores`
- `scheduler_tool_process_count`
- `scheduler_tool_io_read_bytes_total`
- `scheduler_tool_io_write_bytes_total`
- `scheduler_tool_io_read_bytes_per_second`
- `scheduler_tool_io_write_bytes_per_second`
- `scheduler_tool_net_rx_bytes_total`
- `scheduler_tool_net_tx_bytes_total`
- `scheduler_tool_net_rx_bytes_per_second`
- `scheduler_tool_net_tx_bytes_per_second`
- `scheduler_tool_context_switches_total`

Set `AGENT_SCHEDULER_TRACE_DIR` to write live trace records to that directory.
The writer creates one JSONL file per run/session. Full model input/output is
populated when OpenClaw uses the LLM proxy. Tool args/results are populated
when the plugin sends raw fields with `recordRawTrace=true`; otherwise they are
`null`.

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
For unprivileged cgroup-v2 delegation, the process that starts OpenClaw should
also be moved into the delegated root cgroup; otherwise the kernel can reject
moving children into sub-cgroups with `Permission denied`.
Set `CLAW_CGROUP_REQUIRED=1` while debugging if cgroup fallback should be a
hard failure instead of a silent downgrade to PID monitoring. This required
mode forces a cgroup attempt even if profiling metadata disables cgroup and
checks that the child process actually joined the cgroup. Join failures are
reported as `cgroup_join_failed` or `cgroup_join_missing`.
`[Errno 95] Operation not supported` during `cgroup.procs` writes means the
host cgroup hierarchy rejected process migration into the child cgroup. In that
case, leave required mode off and use PID process-tree monitoring unless the
host cgroup delegation can be changed.
