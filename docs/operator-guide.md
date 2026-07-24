# Operator Guide

This guide is the normal user path for running OpenClaw with the
hardware-scheduler plugin and sidecar trace recorder.

## What You Get

The sidecar writes span-based JSONL traces and stores recent tool samples. With
the recommended proxy setup, traces include full LLM request/response content.
With `recordRawTrace: true`, tool hook inputs and outputs are sent to the
sidecar. With `managed-wrapper`, `exec` tools are correlated with a trusted PID
or cgroup for resource attribution.

## Prerequisites

- Python 3.10+
- Node.js and npm
- OpenClaw CLI 2026.7.1 or newer
- A working OpenAI-compatible LLM provider key
- Docker only if you run SWE-Rebench

## 1. Install And Build

From the repository root:

```bash
python -m pip install -e "services/scheduler[dev]"

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

Confirm the launcher exists:

```bash
claw-launch --help
```

If that fails, reinstall the scheduler package into the Python environment used
by your shell.

## 2. Start The Sidecar

```bash
cp .env.example .env
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Health checks:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

The example `.env` writes traces under `data/traces` and SQLite state under
`data/openclaw-trace.sqlite3`.

## 3. Route LLM Traffic Through The Proxy

Configure an OpenClaw local OpenAI-compatible provider that points at the
sidecar:

```bash
export LLM_API_KEY="sk-..."

openclaw onboard --non-interactive --accept-risk --skip-health \
  --mode local \
  --auth-choice vllm \
  --custom-base-url "http://127.0.0.1:8765/v1" \
  --custom-api-key "$LLM_API_KEY" \
  --custom-model-id "deepseek-v4-flash"
```

DeepSeek is the built-in upstream default. For a different provider, edit
`.env` and restart the sidecar:

```bash
AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL=https://openrouter.ai/api/v1
AGENT_SCHEDULER_LLM_PROXY_EXPOSE_MODEL=deepseek-chat
AGENT_SCHEDULER_LLM_PROXY_UPSTREAM_MODEL=deepseek/deepseek-chat
```

Set `AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY` only when OpenClaw does not forward
the provider key you need.

## 4. Install And Configure The Plugin

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

The runtime inspect output should list:

```text
before_tool_call
after_tool_call
model_call_started
model_call_ended
```

Patch the plugin config. Use an absolute launcher path:

```bash
claw-launch --help
```

```bash
cat <<'JSON5' | openclaw config patch --stdin
{
  plugins: {
    entries: {
      "hardware-scheduler": {
        enabled: true,
        config: {
          endpoint: "http://127.0.0.1:8765",
          mode: "observe",
          failOpen: true,
          recordRawTrace: true,
          executionBackend: "managed-wrapper",
          launcherPath: "/absolute/path/to/claw-launch",
          securityBoundaryAccepted: true
        }
      }
    }
  }
}
JSON5
```

```bash
openclaw config get plugins.entries.hardware-scheduler.config --json
```

For debugging, switch `executionBackend` to `hook-only`. Trace records still
exist, but resource usage may be `unattributed`.

## 5. Run OpenClaw

```bash
openclaw models list

openclaw agent --local --agent main --model "vllm/deepseek-v4-flash" \
  --message "Use the shell to run: python -c 'print(\"trace-ok\")'. Then summarize the result."
```

OpenClaw logs should show requests to:

```text
http://127.0.0.1:8765/v1/chat/completions
```

If logs show the upstream provider URL directly, the selected model is
bypassing the sidecar proxy and full LLM content will not be captured.

## 6. Inspect Output

```bash
curl "http://127.0.0.1:8765/v1/tools/recent?limit=5"
curl http://127.0.0.1:8765/metrics
```

Find the trace file:

```bash
ls data/traces
python tools/inspect_trace.py data/traces/<trace-file>.jsonl --all --details
python tools/inspect_trace.py data/traces/<trace-file>.jsonl --all --timeline
```

Look for:

- `record_type: "span_start"` and `record_type: "span_end"`
- LLM spans with `input.messages` and `output.content`
- Tool spans with `input.requested_args` and `output.content`
- Resource fields such as `cpu_time_s`, `rss_peak_bytes`, `scope`, and
  `attribution_status`

## 7. Cgroup Notes

`managed-wrapper` can use Linux cgroup v2 when available. That gives stronger
resource attribution than process-tree sampling. The launcher falls back to PID
sampling when cgroup setup is unavailable.

Useful environment variables:

```bash
CLAW_CGROUP_DEBUG=1
CLAW_CGROUP_REQUIRED=1
CLAW_CGROUP_ROOT=/sys/fs/cgroup/claw
```

Use `CLAW_CGROUP_REQUIRED=1` only when you want missing cgroup support to fail
loudly instead of falling back.

## Troubleshooting

If config patching fails with an unrecognized plugin key, use the documented
shape:

```text
plugins.entries.hardware-scheduler.config
```

If tool args/results are null:

- Confirm `recordRawTrace: true` is in OpenClaw config.
- Rebuild and relink the plugin after TypeScript changes.
- Confirm runtime inspect still shows the four hooks.

If resource usage is `unattributed`:

- Prefer `executionBackend: "managed-wrapper"`.
- Use an absolute `launcherPath`.
- On Linux, enable cgroup debug if you expect cgroup attribution.

If `claw-launch` is not found:

- Reinstall the scheduler package.
- Patch `launcherPath` to an absolute path.

If full LLM content is missing:

- Confirm the selected OpenClaw model uses `http://127.0.0.1:8765/v1`.
- Restart the sidecar after `.env` changes.
