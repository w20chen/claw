# Operator Guide

This guide assumes Windows PowerShell and the local paths used on this machine:

- project: `C:\Users\29068\Desktop\claw`
- benchmark repo: `C:\Users\29068\Desktop\agent-test-bench`
- OpenClaw CLI: `openclaw.cmd`

Use `openclaw.cmd`, not bare `openclaw`, because PowerShell may block the npm
`openclaw.ps1` shim under the current execution policy.

## 1. Build The Plugin

```powershell
cd C:\Users\29068\Desktop\claw\packages\openclaw-plugin
npm.cmd install
npm.cmd run typecheck
npm.cmd run build
```

The build output is `packages/openclaw-plugin/dist/index.js`. OpenClaw loads
that file through the plugin manifest.

## 2. Link It Into OpenClaw

```powershell
openclaw.cmd plugins install --link C:\Users\29068\Desktop\claw\packages\openclaw-plugin
openclaw.cmd plugins inspect hardware-scheduler --runtime --json
```

A healthy runtime inspect reports:

```text
status: loaded
hookCount: 4
typedHooks: before_tool_call, after_tool_call, model_call_started, model_call_ended
```

Those hooks are the entire online integration point. The plugin does not patch
OpenClaw core and does not replace the OpenClaw agent loop.

## 3. Start The Scheduler Sidecar

In a separate PowerShell window:

```powershell
cd C:\Users\29068\Desktop\claw\services\scheduler
$env:PYTHONPATH = "src"
$env:AGENT_SCHEDULER_DB_PATH = "C:\Users\29068\Desktop\claw\data\scheduler.sqlite3"
$env:AGENT_SCHEDULER_POLICY = "observe-only"
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Check that it is alive:

```powershell
curl.exe http://127.0.0.1:8765/health/live
curl.exe http://127.0.0.1:8765/health/ready
```

The sidecar owns persistence, prediction, admission policy, runtime samples,
and metrics. The OpenClaw plugin talks to it over local HTTP.

## 4. Run OpenClaw With The Plugin Active

If you use DeepSeek, configure the key outside this repository:

```powershell
$env:DEEPSEEK_API_KEY = "<your-key>"
```

Then run a small OpenClaw agent call:

```powershell
openclaw.cmd agent --local --agent main --model deepseek/deepseek-v4-flash --message "Reply with exactly: openclaw-ok"
```

For plugin observation, run a task that actually uses tools. For example:

```powershell
openclaw.cmd agent --local --agent main --model deepseek/deepseek-v4-flash --message "Use the shell to print the current working directory, then summarize it in one sentence."
```

After the run, inspect the scheduler:

```powershell
curl.exe http://127.0.0.1:8765/v1/tools/recent
curl.exe http://127.0.0.1:8765/metrics
```

If OpenClaw exposes a tool PID, the sample can include PID-attributed CPU, RSS,
I/O, and context-switch deltas. If not, the sample is still useful for tool
duration, prediction, and scheduling state, but it is marked:

```json
"attribution_status": "unattributed"
```

That is intentional. The sidecar does not pretend its own process metrics are
the tool's metrics.

## 5. What Happens During A Tool Call

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

The sidecar uses `operation_hint` to match static profiles. For example, an
`exec` command that looks like `python -m pytest` can match an `exec-pytest`
profile generated from `agent-test-bench`.

## 6. Use Tool Profiles

Profiles are JSON files matching `contracts/tool-profile.schema.json`.

Example sidecar startup with profiles:

```powershell
cd C:\Users\29068\Desktop\claw\services\scheduler
$env:PYTHONPATH = "src"
$env:AGENT_SCHEDULER_TOOL_PROFILES = "C:\Users\29068\Desktop\claw\artifacts\agent-test-bench-tool-profiles.json"
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

When a matching tool request arrives, the sidecar returns predicted duration,
resource class, and advisory placement metadata in the decision response.

## 7. Run agent-test-bench Through The Adapter

The benchmark adapter does not change `agent-test-bench`. It runs the original
entry point from the benchmark repo:

```text
PYTHONPATH=src python -m trace_collect.cli ...
```

Preview the delegated command:

```powershell
cd C:\Users\29068\Desktop\claw
python tools\run_agent_test_bench.py --dry-run -- `
  --provider deepseek --model deepseek-chat `
  --benchmark swe-rebench --scaffold openclaw `
  --container docker --mcp-config none `
  --sample 1
```

Run the benchmark for real:

```powershell
cd C:\Users\29068\Desktop\claw
python tools\run_agent_test_bench.py -- `
  --provider deepseek --model deepseek-chat `
  --benchmark swe-rebench --scaffold openclaw `
  --container docker --mcp-config none `
  --sample 1
```

Everything after `--` is passed unchanged to `agent-test-bench`. That means
task selection, trace layout, Docker/Podman choice, fixed-image preparation,
mirrors, resource monitoring, resume behavior, and `trace.jsonl` format remain
owned by `agent-test-bench`.

## 8. Validate An Existing Benchmark Run

```powershell
python tools\validate_agent_test_bench_run.py <run-dir> `
  --events-out artifacts\agent-test-bench-events.jsonl `
  --profiles-out artifacts\agent-test-bench-tool-profiles.json
```

The validator checks:

- `trace.jsonl` files exist
- `trace_metadata.trace_format_version` is `5`
- `tool_exec` records exist unless `--allow-empty-tools` is set
- image metadata can be discovered from `run_manifest.json` or `results.json`
- scheduler-compatible events and profiles can be generated

The original trace files are not modified.

## 9. How agent-test-bench And This Plugin Work Together

There are two paths:

```text
Online path:
OpenClaw runtime -> plugin hooks -> sidecar -> SQLite/metrics
```

Use this when you want to observe live OpenClaw tool calls.

```text
Offline benchmark path:
agent-test-bench -> canonical trace.jsonl -> validator/importer -> profiles/events
```

Use this when you want benchmark-scale data while preserving the existing
benchmark command line, trace format, and container images.

The bridge between the two paths is the profile file. `agent-test-bench`
produces canonical traces; this project turns those traces into scheduler tool
profiles; the sidecar uses those profiles during live OpenClaw runs.

## 10. Validation Commands

Run these before trusting a local change:

```powershell
cd C:\Users\29068\Desktop\claw
python tools\validate_contracts.py
python -m pytest tests\test_agent_test_bench_adapter.py tests\test_import_agent_test_bench_trace.py --basetemp .pytest-tmp-root

cd C:\Users\29068\Desktop\claw\services\scheduler
python -m pytest

cd C:\Users\29068\Desktop\claw\packages\openclaw-plugin
npm.cmd test
npm.cmd run typecheck
npm.cmd run build

openclaw.cmd plugins inspect hardware-scheduler --runtime --json
```
