# Operator Guide

This guide assumes a Linux host with Bash, Python 3.12, Node.js 24, and npm.

Example paths used below:

- project: `~/claw`
- benchmark repo: `~/agent-test-bench`

Adjust the paths for your machine. Do not modify OpenClaw core or the
`agent-test-bench` checkout.

## 1. Install OpenClaw CLI

The plugin is version-coupled to OpenClaw's plugin SDK and hook names. The
package declares `openclaw >=2026.7.1` as its peer dependency, and this
repository was validated against OpenClaw `2026.7.1`.

Install the validated baseline version first:

```bash
npm install -g openclaw@2026.7.1
openclaw --version
```

The version output should be `OpenClaw 2026.7.1` or a patch-compatible build.
Do not use `openclaw@latest` for production installs unless you also rerun the
runtime compatibility checks in this guide. Newer OpenClaw versions may change
plugin SDK import paths, manifest handling, or hook payload shapes.

## 2. Install Development Dependencies

From the project root:

```bash
cd ~/claw
python -m pip install -e 'services/scheduler[dev]'

cd packages/openclaw-plugin
npm install
```

The Python dev extra includes the sidecar test dependencies and `jsonschema`
for contract validation.

If editable install fails with a missing `build_editable` hook, either upgrade
the packaging tools or install non-editable. The sidecar commands in this guide
set `PYTHONPATH=src`, so non-editable install is sufficient for local
development dependencies:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install 'services/scheduler[dev]'
```

## 3. Build The Plugin

```bash
cd ~/claw/packages/openclaw-plugin
npm run typecheck
npm run build
```

The build output is `packages/openclaw-plugin/dist/index.js`. OpenClaw loads
that file through `packages/openclaw-plugin/openclaw.plugin.json`.

## 4. Link It Into OpenClaw

```bash
cd ~/claw
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

OpenClaw 2026.7.1 does not support `--force` together with `--link`. If you
need to replace an existing link, remove or uninstall the existing plugin first,
then rerun the `plugins install --link` command.

A healthy runtime inspect reports the plugin as loaded with these hooks:

```text
before_tool_call
after_tool_call
model_call_started
model_call_ended
```

Those hooks are the entire online integration point. The plugin does not patch
OpenClaw core and does not replace the OpenClaw agent loop.

## 5. Start The Scheduler Sidecar

In a separate shell:

```bash
cd ~/claw/services/scheduler
export PYTHONPATH=src
export AGENT_SCHEDULER_DB_PATH=../../data/scheduler.sqlite3
export AGENT_SCHEDULER_POLICY=observe-only
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Check that it is alive:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
```

The sidecar owns persistence, prediction, admission policy, runtime samples,
and metrics. The OpenClaw plugin talks to it over local HTTP.

## 6. Optional Docker Compose Sidecar

Docker Compose starts only the sidecar. It does not mount the Docker socket and
does not run OpenClaw or `agent-test-bench`:

```bash
cd ~/claw
docker compose up --build scheduler
```

The service listens on `127.0.0.1:8765` on the host. Inside the container it
binds `0.0.0.0` so Docker port publishing can reach it.

## 7. Run OpenClaw With The Plugin Active

Configure model credentials outside this repository. For example:

```bash
export DEEPSEEK_API_KEY='<your-key>'
```

Run a small agent call:

```bash
openclaw agent --local --agent main --model deepseek/deepseek-v4-flash --message 'Reply with exactly: openclaw-ok'
```

For plugin observation, run a task that actually uses tools:

```bash
openclaw agent --local --agent main --model deepseek/deepseek-v4-flash --message 'Use the shell to print the current working directory, then summarize it in one sentence.'
```

After the run, inspect the scheduler:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
```

If OpenClaw exposes a tool PID, the sample can include PID-attributed CPU, RSS,
I/O, and context-switch deltas. If not, the sample is still useful for tool
duration, prediction, and scheduling state, but it is marked:

```json
"attribution_status": "unattributed"
```

That is intentional. The sidecar does not pretend its own process metrics are
the tool's metrics.

## 8. What Happens During A Tool Call

The live path is:

```text
OpenClaw tool hook
  -> hardware-scheduler plugin
  -> POST /v1/decisions/tool
  -> sidecar prediction + policy
  -> OpenClaw runs or blocks the tool
  -> POST /v1/events/tool-completed
  -> SQLite sample + Prometheus metrics
```

The plugin sends metadata, feature counts, a parameter digest, and an
`operation_hint` such as `pytest`, `grep`, or `git`. It does not send full
prompts, model responses, tool output, credentials, or raw tool parameters by
default.

## 9. Use Tool Profiles

Profiles are JSON files matching `contracts/tool-profile.schema.json`.

Example sidecar startup with profiles:

```bash
cd ~/claw/services/scheduler
export PYTHONPATH=src
export AGENT_SCHEDULER_TOOL_PROFILES=../../artifacts/agent-test-bench-tool-profiles.json
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

When a matching tool request arrives, the sidecar returns predicted duration,
resource class, and advisory placement metadata in the decision response.

## 10. Run agent-test-bench Through The Adapter

The benchmark adapter does not change `agent-test-bench`. It runs the original
entry point from the benchmark repo:

```text
PYTHONPATH=src python -m trace_collect.cli ...
```

Set the benchmark checkout path once:

```bash
export AGENT_TEST_BENCH_ROOT=~/agent-test-bench
```

Preview the delegated command:

```bash
cd ~/claw
python tools/run_agent_test_bench.py --dry-run -- \
  --provider deepseek --model deepseek-chat \
  --benchmark swe-rebench --scaffold openclaw \
  --container docker --mcp-config none \
  --sample 1
```

Run the benchmark for real:

```bash
cd ~/claw
python tools/run_agent_test_bench.py -- \
  --provider deepseek --model deepseek-chat \
  --benchmark swe-rebench --scaffold openclaw \
  --container docker --mcp-config none \
  --sample 1
```

Everything after `--` is passed unchanged to `agent-test-bench`. Task
selection, trace layout, Docker/Podman choice, fixed-image preparation,
mirrors, resource monitoring, resume behavior, and `trace.jsonl` format remain
owned by `agent-test-bench`.

## 11. Validate An Existing Benchmark Run

```bash
cd ~/claw
python tools/validate_agent_test_bench_run.py <run-dir> \
  --events-out artifacts/agent-test-bench-events.jsonl \
  --profiles-out artifacts/agent-test-bench-tool-profiles.json
```

The validator checks:

- `trace.jsonl` files exist
- `trace_metadata.trace_format_version` is `5`
- `tool_exec` records exist unless `--allow-empty-tools` is set
- image metadata can be discovered from `run_manifest.json` or `results.json`
- scheduler-compatible events and profiles can be generated

The original trace files are not modified.

## 12. Validation Commands

Run these before trusting a local change:

```bash
cd ~/claw
python tools/validate_contracts.py
python -m pytest tests/test_agent_test_bench_adapter.py tests/test_import_agent_test_bench_trace.py --basetemp .pytest-tmp-root

cd ~/claw/services/scheduler
python -m pytest

cd ~/claw/packages/openclaw-plugin
npm test
npm run typecheck
npm run build

cd ~/claw
openclaw --version
openclaw plugins inspect hardware-scheduler --runtime --json
```

For OpenClaw upgrades, also rerun the plugin link step:

```bash
cd ~/claw
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins inspect hardware-scheduler --runtime --json
```
