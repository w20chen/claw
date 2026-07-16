# Real OpenClaw Trace + Resource Recorder Guide

This guide is for the real target path:

```text
OpenClaw agent task
  -> hardware-scheduler OpenClaw plugin hooks
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
{"type":"action","action_type":"tool_exec","data":{"tool_name":"exec","tool_args":{"command":"..."},"tool_result":"...","resource_usage":{"cpu_time_delta_s":0.1,"memory_footprint_bytes":12345678,"disk_read_bytes_delta":0,"disk_write_bytes_delta":4096,"net_rx_bytes_delta":0,"net_tx_bytes_delta":0}}}
```

`recordRawTrace: true` is the important plugin switch. It tells the plugin to
send the OpenClaw hook-visible model input/output, tool args/results, and raw
hook payloads to the sidecar. If OpenClaw does not expose a specific internal
field to plugin hooks, the plugin cannot record that field without changing
OpenClaw itself.

In the currently observed OpenClaw `2026.7.1` model hooks, provider/model,
duration, token budget, request/response byte counts, and transport metadata
are visible, but full `messages_in` and model `content` may not be exposed to
the plugin hook. Tool hooks do expose `params` and `result`, so `tool_args` and
`tool_result` should be populated when `recordRawTrace=true`.

Resource fields are strongest for `exec` in `managed-wrapper` mode because
`claw-launch` gives the sidecar a trusted PID or cgroup scope. Without a
trusted scope, the trace still records the tool action, but resource attribution
is `unattributed`.

## 1. Install And Build

```bash
cd ~/claw
python -m pip install -e 'services/scheduler[dev]'

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

Confirm `claw-launch` is available:

```bash
claw-launch --help
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
export CLAW_LAUNCHER_PATH="$(python -c 'import shutil; p=shutil.which("claw-launch"); assert p, "claw-launch not found"; print(p)')"
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

## 4. Start The Sidecar Trace Writer

Terminal 1:

```bash
cd ~/claw/services/scheduler
export PYTHONPATH=src
export AGENT_SCHEDULER_DB_PATH=../../data/openclaw-trace.sqlite3
export AGENT_SCHEDULER_TRACE_PATH=../../data/trace.jsonl
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Check health from another shell:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

## 5. Export Plugin Runtime Overrides

Your latest run showed that OpenClaw accepted the config patch but the hook-only
plugin still behaved as if it had default config. To make the real run
unambiguous, export these variables in the shell that runs `openclaw agent`.
The plugin reads them directly as a fallback when `api.pluginConfig` is not
populated:

```bash
export OPENCLAW_HARDWARE_SCHEDULER_ENDPOINT=http://127.0.0.1:8765
export OPENCLAW_HARDWARE_SCHEDULER_RECORD_RAW_TRACE=true
export OPENCLAW_HARDWARE_SCHEDULER_EXECUTION_BACKEND=managed-wrapper
export OPENCLAW_HARDWARE_SCHEDULER_LAUNCHER_PATH="$CLAW_LAUNCHER_PATH"
export OPENCLAW_HARDWARE_SCHEDULER_SECURITY_BOUNDARY_ACCEPTED=true
```

For a long-lived Gateway service, put equivalent values into the Gateway
environment before restarting it. For `openclaw agent --local`, exporting them
in the current shell is enough.

## 6. Run A Real OpenClaw Task

Choose a model that your OpenClaw install can actually run:

```bash
openclaw models list
openclaw models status
export OPENCLAW_TEST_MODEL='<provider/model-from-openclaw-models-list>'
```

Run a task that forces a shell tool call:

```bash
cd ~/claw
openclaw agent --local --agent main --model "$OPENCLAW_TEST_MODEL" \
  --message 'Use the shell to run: python -c "import pathlib, time; pathlib.Path(\"openclaw_trace_probe.txt\").write_text(\"trace-probe\\n\"); print(2 + 2); time.sleep(1)". Then summarize the result.'
```

This should create a real OpenClaw model turn and a real OpenClaw `exec` tool
call. The plugin observes those hooks and the sidecar writes the trace.

## 7. Inspect The Real Trace

```bash
tail -n 20 data/trace.jsonl
curl 'http://127.0.0.1:8765/v1/tools/recent?limit=5'
curl http://127.0.0.1:8765/metrics
```

For easier reading:

```bash
python - <<'PY'
import json
from pathlib import Path

for line in Path("data/trace.jsonl").read_text(encoding="utf-8").splitlines():
    rec = json.loads(line)
    if rec.get("type") != "action":
        continue
    print("\n==", rec.get("action_type"), rec.get("action_id"), "==")
    data = rec.get("data", {})
    if rec.get("action_type") == "llm_call":
        print("messages_in:", json.dumps(data.get("messages_in"), ensure_ascii=False)[:1000])
        print("content:", json.dumps(data.get("content"), ensure_ascii=False)[:1000])
    if rec.get("action_type") == "tool_exec":
        print("tool_name:", data.get("tool_name"))
        print("tool_args:", json.dumps(data.get("tool_args"), ensure_ascii=False)[:1000])
        print("tool_result:", json.dumps(data.get("tool_result"), ensure_ascii=False)[:1000])
        print("resource_usage:", json.dumps(data.get("resource_usage"), indent=2, ensure_ascii=False))
PY
```

You are looking for:

- `llm_call.data.messages_in`
- `llm_call.data.content`
- `tool_exec.data.tool_args`
- `tool_exec.data.tool_result`
- `tool_exec.data.resource_usage.attribution_status`
- CPU/RSS/disk/network fields inside `resource_usage`

## 8. Optional cgroup Scope

On Linux, managed-wrapper can use cgroup-v2 counters if you provide a writable
root:

```bash
sudo mkdir -p /sys/fs/cgroup/claw
sudo chown "$USER":"$USER" /sys/fs/cgroup/claw
export CLAW_CGROUP_ROOT=/sys/fs/cgroup/claw
```

Then rerun the OpenClaw task. `resource_usage.monitor_source` should become
`cgroup-v2` when the launcher successfully registers a cgroup scope.

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
  `python -c 'import shutil; print(shutil.which("claw-launch"))'`.
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
`OPENCLAW_HARDWARE_SCHEDULER_LAUNCHER_PATH` as shown above, rebuild/relink the
plugin, and rerun.

If no model can run:

- Fix OpenClaw model auth first with `openclaw models status` and the provider
  setup flow for your environment.

## 10. Sidecar-Only Smoke Test

This is not the target path. It does not run OpenClaw. Keep it only as a quick
sidecar sanity check when model auth is unavailable:

```bash
cd ~/claw
python tools/demo_trace_recorder.py
```

The real validation is the OpenClaw task path above.
