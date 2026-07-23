# Real OpenClaw Trace + Resource Recorder Guide

This guide is for the real target path:

```text
OpenClaw agent task
  -> hardware-scheduler OpenClaw plugin hooks
  -> sidecar LLM proxy for full LLM request/response capture
  -> scheduler sidecar
  -> agent-test-bench-style trace.jsonl
  -> per-tool CPU / memory / network / disk I/O resource usage
```

The project must remain an OpenClaw plugin plus sidecar. It does not modify
OpenClaw core.

## What You Should Expect

For a real OpenClaw run, the sidecar writes `trace.jsonl` records like:

```json
{"type":"trace_metadata","trace_format_version":5,"scaffold":"openclaw","mode":"collect"}
{"type":"action","action_type":"llm_call","data":{"messages_in":[...],"content":"...","llm_latency_ms":1234.0}}
{"type":"action","action_type":"tool_exec","data":{"tool_name":"exec","tool_args":{"command":"..."},"tool_result":"...","resource_usage":{"cpu_time_delta_s":0.1,"cpu_utilization_avg_cores":0.2,"memory_rss_bytes_peak":12345678,"disk_write_bytes_per_s":4096.0,"net_tx_bytes_per_s":0.0,"sampling_quality":"ok","timeline":[...]}}}
```

The default full-trace path uses the sidecar as an OpenAI-compatible LLM proxy.
Onboard an OpenClaw OpenAI-compatible local provider with `vllm` mode and set
its custom base URL to `http://127.0.0.1:8765/v1`. Then the sidecar records
full LLM request messages and response content.

`recordRawTrace: true` is still important for tool trace capture. It tells the
plugin to send hook-visible tool args/results and raw hook payloads to the
sidecar. OpenClaw model hooks are retained as fallback metadata, but full LLM
input/output comes from the LLM proxy path.

Resource fields are strongest for `exec` in `managed-wrapper` mode because
`claw-launch` gives the sidecar a trusted PID or cgroup scope. Without a
trusted scope, the trace still records the tool action, but resource attribution
is `unattributed`.

## 1. Install And Build

```bash
cd ~/claw
python3 -m pip install -e 'services/scheduler[dev]'
command -v claw-launch
claw-launch --help

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

If `command -v claw-launch` prints nothing, the scheduler package was not
installed into the Python environment used by this shell. Rerun:

```bash
python3 -m pip install -e 'services/scheduler[dev]'
```

## 2. Link The Plugin Into OpenClaw

```bash
cd ~/claw
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

The inspect output must show these hooks:

```text
before_tool_call
after_tool_call
model_call_started
model_call_ended
```

## 3. Configure The Plugin For Real Raw Trace Recording

Find the absolute `claw-launch` path first. Do not rely on `launcherPath:
"claw-launch"`; OpenClaw's exec environment may have a narrower `PATH` than
your interactive shell.

```bash
export CLAW_LAUNCHER_PATH="$(command -v claw-launch)"
test -n "$CLAW_LAUNCHER_PATH"
echo "$CLAW_LAUNCHER_PATH"
```

Patch OpenClaw config non-interactively. In OpenClaw `2026.7.1`, plugin runtime
config lives under `plugins.entries.<plugin-id>.config`, not directly under
`plugins.<plugin-id>`:

```bash
cat <<JSON5 | openclaw config patch --stdin
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
          launcherPath: "$CLAW_LAUNCHER_PATH",
          securityBoundaryAccepted: true
        }
      }
    }
  }
}
JSON5
```

Validate config:

```bash
openclaw config validate
openclaw config get plugins.entries.hardware-scheduler.config --json
```

If you run agents through a long-lived Gateway, restart it after plugin
install/config changes:

```bash
openclaw gateway restart
```

For `openclaw agent --local`, the new process should read the current config
when the command starts.

If `managed-wrapper` causes trouble while debugging, temporarily switch to
`executionBackend: "hook-only"`. That still records model/tool trace content,
but OS resource usage may be `unattributed`.

## When To Rebuild Or Restart

- TypeScript plugin changes: run `cd packages/openclaw-plugin && npm run build`,
  then `openclaw plugins install --link ./packages/openclaw-plugin`. Restart a
  long-lived Gateway with `openclaw gateway restart`.
- Python sidecar changes under `services/scheduler/src`: restart the sidecar
  process. Editable install means source changes are picked up by the next
  process.
- Launcher command missing or stale: rerun
  `python3 -m pip install -e 'services/scheduler[dev]'`, then re-export
  `CLAW_LAUNCHER_PATH="$(command -v claw-launch)"`.
- Config changes: rerun `openclaw config patch --stdin` for plugin settings,
  or edit `.env` and restart the sidecar for sidecar/proxy settings. Gateway
  users should restart Gateway after plugin config changes.

## 4. Start The Sidecar Trace Writer

Terminal 1:

```bash
cd ~/claw
cp .env.example .env

cd ~/claw/services/scheduler
python3 -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

The sidecar loads `.env` automatically from the repository root. The default
`.env.example` writes to `data/openclaw-trace.sqlite3` and `data/trace.jsonl`.
DeepSeek is the built-in upstream default. For the most explicit proxy setup,
put the DeepSeek key in `.env` so the sidecar always sends the correct upstream
authorization:

```bash
AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL=https://api.deepseek.com
AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY=<your-deepseek-api-key>
```

DeepSeek's built-in default is `https://api.deepseek.com`. Do not add `/v1`
unless your chosen upstream actually expects it.

Check health from another shell:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

Configure OpenClaw's local OpenAI-compatible provider to use the sidecar proxy:

```bash
export DEEPSEEK_API_KEY='<your-deepseek-api-key>'
openclaw onboard --non-interactive \
  --mode local \
  --auth-choice vllm \
  --custom-base-url 'http://127.0.0.1:8765/v1' \
  --custom-api-key "$DEEPSEEK_API_KEY" \
  --custom-model-id 'deepseek-v4-flash'
```

For OpenAI-compatible providers, the sidecar exposes `/v1/models` and
`/v1/chat/completions`, forwards requests to
`AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL`, and records the full request/response
into `trace.jsonl`.

## 5. Confirm Persistent Plugin Config

The plugin settings are stored in OpenClaw config by section 3. Confirm them
before running:

```bash
openclaw config get plugins.entries.hardware-scheduler.config --json
```

If your OpenClaw runtime still ignores plugin config, use
`OPENCLAW_HARDWARE_SCHEDULER_*` environment overrides as a fallback. The normal
path should not require repeating those exports.

## 6. Run A Real OpenClaw Task

Choose a model that your OpenClaw install can actually run:

```bash
openclaw models list
openclaw models status
export OPENCLAW_TEST_MODEL='vllm/deepseek-v4-flash'
```

Run a task that forces a shell tool call:

```bash
cd ~/claw
openclaw agent --local --agent main --model "$OPENCLAW_TEST_MODEL" \
  --message 'Use the shell to run: python3 -c "from pathlib import Path; import hashlib, math, os, time; p=Path(\"openclaw_trace_probe.bin\"); blob=bytearray(os.urandom(16*1024*1024)); total=sum(math.sqrt(i) for i in range(2000000)); digest=hashlib.sha256(blob).hexdigest()[:16]; p.write_bytes(blob); data=p.read_bytes(); time.sleep(0.5); print(\"heavy-ok\", len(data), int(total), digest)". Then summarize the result.'
```

This should create a real OpenClaw model turn and a real OpenClaw `exec` tool
call with visible CPU, memory, and disk activity. The plugin observes those
hooks and the sidecar writes the trace.

Confirm the OpenClaw log shows:

```text
url=http://127.0.0.1:8765/v1/chat/completions
```

If it shows `https://api.deepseek.com/chat/completions`, the run used the
direct DeepSeek provider instead of the proxy provider.

## 7. Inspect The Real Trace

```bash
tail -n 20 data/trace.jsonl
curl 'http://127.0.0.1:8765/v1/tools/recent?limit=5'
curl http://127.0.0.1:8765/metrics
```

For CLI visualization:

```bash
python3 tools/inspect_trace.py data/trace.jsonl --tail 20
python3 tools/inspect_trace.py data/trace.jsonl --tail 20 --details
python3 tools/inspect_trace.py data/trace.jsonl --type tool_exec --tail 10 --details --timeline
```

You are looking for:

- `llm_call.data.messages_in`
- `llm_call.data.content`
- `tool_exec.data.tool_args`
- `tool_exec.data.tool_result`
- `tool_exec.data.resource_usage.attribution_status`
- `cpu_utilization_avg_cores`, `memory_rss_bytes_peak`, disk/network
  `*_bytes_per_s`, and `sampling_quality` inside `resource_usage`
- `resource_usage.timeline`, a compact list of sampled points attached to the
  final tool action. Timeline I/O and network columns are per-interval rates,
  not raw cumulative kernel counters.

The default run creates or appends these files under `~/claw/data`:

- `openclaw-trace.sqlite3`: SQLite persistence used by the sidecar for
  decisions, completions, model events, and resource samples.
- `trace.jsonl`: append-only trace. Proxy-backed `llm_call` records contain
  `messages_in`, `content`, `raw_request`, and `raw_response`; `tool_exec`
  records contain `tool_args`, `tool_result`, and `resource_usage`.

## 8. Cgroup Resource Monitoring (Default)

The sidecar uses Linux cgroup v2 for per-execution resource monitoring by
default: CPU time, memory RSS, disk I/O, and context switches are read from
`cpu.stat`, `memory.current`, and `io.stat` inside a per-execution cgroup
directory.  cgroup monitoring provides more accurate and complete resource
attribution than PID process-tree sampling alone.

### Automatic Cgroup Root Selection

`claw-launch` tries candidate cgroup roots in priority order until one succeeds:

| Priority | Path | Works when |
|----------|------|------------|
| 1 (env) | `CLAW_CGROUP_ROOT` | Explicitly configured |
| 2 | `/sys/fs/cgroup/claw` | Root process or pre-delegated by admin |
| 3 | `/sys/fs/cgroup/user.slice/user-<UID>.slice/user@<UID>.service/claw` | systemd, non-root user (default) |

On any modern Linux distribution with systemd (Ubuntu 20.04+, Debian 11+,
Fedora, Arch, etc.), the **user manager slice fallback (priority 3) works out
of the box** — no root privileges required.  systemd delegates
`user@<UID>.service` to the user at login; the parent `user-<UID>.slice` is
root-owned, so the cgroup must be created under `user@<UID>.service`, not
directly under the slice.

### Verify cgroup Is Active

After a run, check the tool span in `trace.jsonl`:

```json
"execution": {
  "cgroup_path": "/sys/fs/cgroup/user.slice/user-1000.slice/claw/exec_abc123"
},
"resources": {
  "scope": "cgroup"
}
```

If `cgroup_path` is `null` and `scope` is `"process_tree"`, the launcher fell
back to PID monitoring.  Enable debug logging to see why:

```bash
export CLAW_CGROUP_DEBUG=1
```

This prints each candidate root and its error to stderr.

### Disable cgroup

```bash
export CLAW_ENABLE_CGROUP=0
```

### Force cgroup (Fail Hard)

```bash
export CLAW_CGROUP_REQUIRED=1
```

With this set, `claw-launch` exits with a visible `cgroup_unavailable` error
instead of silently falling back to PID monitoring.

### Custom cgroup Root

Point to a pre-created delegated cgroup:

```bash
sudo mkdir -p /sys/fs/cgroup/claw
sudo chown -R "$USER":"$USER" /sys/fs/cgroup/claw
echo "$$" | sudo tee /sys/fs/cgroup/claw/cgroup.procs >/dev/null
export CLAW_CGROUP_ROOT=/sys/fs/cgroup/claw
```

The `tee` line moves the current shell into the delegated cgroup root so that
cgroup-v2 allows moving child processes into sub-cgroups.

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `cgroup_path: null` everywhere | Non-systemd host or ancient kernel | Pre-create `/sys/fs/cgroup/claw` with `sudo` |
| `Permission denied` on `cgroup.procs` | Delegation incomplete | Rerun the `echo "$$" \| sudo tee` delegation line |
| `Operation not supported` (Errno 95) | cgroup controller not available in parent | Choose a different cgroup root or disable cgroup |
| `scope: "process_tree"` despite cgroup | `CLAW_ENABLE_CGROUP=0` or profiling disabled | Check env vars; set `CLAW_CGROUP_DEBUG=1` |

## 9. Troubleshooting

If `openclaw config patch --stdin` fails with:

```text
Config validation failed: plugins: Unrecognized key: "hardware-scheduler"
```

you used the wrong config shape. Use
`plugins.entries.hardware-scheduler.config`, as shown in section 3. Also run
`openclaw plugins install --link ./packages/openclaw-plugin` and
`openclaw plugins enable hardware-scheduler` before patching so the entry
exists in OpenClaw's plugin registry.

If `trace.jsonl` contains `tool_args: null` or `tool_result: null`:

- Confirm `openclaw config get plugins.entries.hardware-scheduler.config --json`
  shows `recordRawTrace: true`.
- Rebuild and relink the plugin after code changes:
  `cd packages/openclaw-plugin && npm run build`, then rerun
  `openclaw plugins install --link ./packages/openclaw-plugin`.
- Confirm `openclaw plugins inspect hardware-scheduler --runtime --json`
  still shows the four hooks.

If resource usage is `unattributed`:

- Prefer `executionBackend: "managed-wrapper"` for `exec`.
- Use an absolute launcher path. Confirm:
  `command -v claw-launch`.
- On Linux, optionally set `CLAW_CGROUP_ROOT` before the OpenClaw run.

If OpenClaw reports:

```text
Security Violation: blocked override keys: BASH_ENV, ENV
```

rebuild/relink the plugin. Current instrumentation filters those keys before
returning modified `exec` params.

If OpenClaw reports:

```text
/bin/bash: line 1: claw-launch: command not found
```

the launcher path is not absolute or not visible to the exec environment. Set
`CLAW_LAUNCHER_PATH` and
`OPENCLAW_HARDWARE_SCHEDULER_LAUNCHER_PATH` from `command -v claw-launch`, then
rerun.

If no model can run:

- Fix OpenClaw model auth first with `openclaw models status` and the provider
  setup flow for your environment.
- For full LLM input/output, confirm the selected provider is using
  `http://127.0.0.1:8765/v1` as its base URL. If it bypasses the sidecar proxy,
  model hook records may contain metadata only.
- If OpenClaw logs show `https://api.deepseek.com/chat/completions`, it is
  bypassing the sidecar proxy. After proxy routing is correct, the request URL
  in OpenClaw logs should point at `http://127.0.0.1:8765/...`.

## 10. Sidecar-Only Smoke Test

This is not the target path. It does not run OpenClaw. Keep it only as a quick
sidecar sanity check when model auth is unavailable:

```bash
cd ~/claw
python3 tools/demo_trace_recorder.py
```

The real validation is the OpenClaw task path above.
