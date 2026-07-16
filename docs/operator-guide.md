# Operator Guide

This guide is the shortest end-to-end path for running the plugin and sidecar.
It assumes Linux, Python 3.12, Node.js 24, npm, and OpenClaw `2026.7.1`.

Use `npm.cmd` and `openclaw.cmd` on Windows PowerShell if `.ps1` shims are
blocked.

## Install

```bash
cd ~/claw
npm install -g openclaw@2026.7.1
python -m pip install -e 'services/scheduler[dev]'

cd packages/openclaw-plugin
npm install
npm run typecheck
npm run build
cd ../..
```

If editable Python install fails:

```bash
python -m pip install 'services/scheduler[dev]'
```

## Link Plugin

```bash
cd ~/claw
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

Expected hooks:

```text
before_tool_call
after_tool_call
model_call_started
model_call_ended
```

## Start Sidecar

```bash
cd ~/claw/services/scheduler
export PYTHONPATH=src
export AGENT_SCHEDULER_DB_PATH=../../data/scheduler.sqlite3
export AGENT_SCHEDULER_POLICY=observe-only
export AGENT_SCHEDULER_TRACE_PATH=../../data/trace.jsonl
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Health checks:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

## Run A Local Demo

From another shell:

```bash
cd ~/claw
python tools/demo_supported_features.py --run-launcher
```

Inspect sidecar output:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
tail -n 20 data/trace.jsonl
```

## Run With OpenClaw

Choose a model that your OpenClaw installation can actually run:

```bash
openclaw models list
openclaw models status
export OPENCLAW_TEST_MODEL='<provider/model-from-openclaw-models-list>'
```

Run a task that uses shell tools:

```bash
openclaw agent --local --agent main --model "$OPENCLAW_TEST_MODEL" \
  --message 'Use the shell to print the current working directory, then summarize it.'
```

Then inspect:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
tail -n 20 ~/claw/data/trace.jsonl
```

## Exec Backends

`executionBackend` controls built-in `exec` handling:

- `hook-only`: observe/report only.
- `marker`: preserve command and add correlation env vars.
- `managed-wrapper`: register original command with the sidecar, then rewrite
  OpenClaw's command to `claw-launch`.

Minimal managed-wrapper config:

```json5
{
  plugins: {
    "hardware-scheduler": {
      endpoint: "http://127.0.0.1:8765",
      executionBackend: "managed-wrapper",
      launcherPath: "claw-launch",
      securityBoundaryAccepted: true
    }
  }
}
```

For cgroup-v2 CPU placement experiments on Linux:

```bash
sudo mkdir -p /sys/fs/cgroup/claw
sudo chown "$USER":"$USER" /sys/fs/cgroup/claw
export CLAW_CGROUP_ROOT=/sys/fs/cgroup/claw
```

Placement remains advisory policy-wise; the reference launcher applies cpuset
only when it receives placement metadata and has a writable cgroup root.

## What The Trace Contains

Set `AGENT_SCHEDULER_TRACE_PATH` to append agent-test-bench v5-shaped JSONL:

```json
{"type":"trace_metadata","trace_format_version":5,"scaffold":"openclaw","mode":"collect"}
{"type":"action","action_type":"tool_exec","action_id":"...","data":{"tool_name":"exec","tool_args":null,"tool_result":null,"resource_usage":{}}}
```

`tool_args` and `tool_result` are intentionally `null`. Resource usage is filled
only when the sidecar has a trusted PID or cgroup scope.

## Validate

```bash
cd ~/claw
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
npm run build
```

For OpenClaw upgrades, rerun:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins inspect hardware-scheduler --runtime --json
```
