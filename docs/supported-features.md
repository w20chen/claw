# Supported Features And Observable Commands

This page lists what the project supports today and how to observe each feature
with concrete commands. Commands assume the repository root is `~/claw` on
Linux Bash. PowerShell equivalents are included for the sidecar startup because
Windows development uses `npm.cmd` and PowerShell environment syntax.

## 1. Contract Validation

Run:

```bash
cd ~/claw
python tools/validate_contracts.py
```

Expected result:

```text
validated tool-before-request.json against tool-before-request.schema.json
validated tool-decision.json against tool-decision.schema.json
validated tool-completed-event.json against tool-completed-event.schema.json
validated model-event.json against model-event.schema.json
validated tool-profiles.example.json against tool-profile.schema.json
validated execution-registration.json against execution-registration.schema.json
validated execution-claim.json against execution-claim.schema.json
validated execution-started.json against execution-started.schema.json
validated execution-exited.json against execution-exited.schema.json
```

What happened: the JSON Schema files under `contracts/` were used as the public
protocol source of truth, and every checked example matched its schema.

## 2. Sidecar Health And Metrics

Start the sidecar in terminal 1:

```bash
cd ~/claw/services/scheduler
PYTHONPATH=src python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

PowerShell:

```powershell
cd C:\Users\29068\Desktop\claw\services\scheduler
$env:PYTHONPATH = "src"
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

In terminal 2:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/health/ready
curl http://127.0.0.1:8765/metrics
```

Expected result:

```json
{"live":true}
{"ready":true}
```

The metrics output should include names such as:

```text
scheduler_tool_requests_total
scheduler_tool_decisions_total
scheduler_tool_runtime_samples_total
```

What happened: FastAPI started the scheduler sidecar, opened the SQLite-backed
runtime state, and exposed Prometheus-style metrics.

## 3. Decision, Completion, And Recent Runtime Sample

With the sidecar still running, execute from the repository root:

```bash
cd ~/claw
python tools/demo_supported_features.py
```

Expected visible sections:

```text
== sidecar health ==
...
== v1 decision/completion/runtime sample ==
decision:
  "action": "allow"
completion:
  "stored": true
latest runtime sample:
  "attribution_status": "unattributed"
```

What happened:

- The demo sent `POST /v1/decisions/tool`.
- The observe-only policy returned `allow`.
- The demo sent `POST /v1/events/tool-completed`.
- The sidecar wrote an idempotent completion row and a runtime sample.
- `GET /v1/tools/recent` returned the newest sample.

The sample is `unattributed` because this synthetic v1 demo does not provide a
trusted PID or cgroup scope. That is deliberate: the sidecar does not pretend
its own process metrics belong to the tool.

## 4. Managed Execution Registration And Launcher Scope

Run the same demo with the launcher enabled:

```bash
cd ~/claw
python tools/demo_supported_features.py --run-launcher
```

Expected additional output:

```text
== v2 execution registration ==
registration:
  "execution_id": "demo-exec-..."
  "one_time_token": "..."
claw-launch-ok
launcher exit code: 0
execution scope:
  "execution_scope": {
    "execution_id": "demo-exec-...",
    "pid": ...,
    "source": "claw-launch"
  }
```

What happened:

- The demo called `POST /v2/executions` with the original command.
- The sidecar stored that execution spec in memory and returned a one-time
  token.
- `claw-launch` called `POST /v2/executions/claim`, consuming that token.
- `claw-launch` ran the original command through `/bin/sh -lc` on POSIX hosts.
- `claw-launch` reported `started` and `exited`.
- The sidecar returned a trusted execution scope for the execution ID.

This is the same protocol used by plugin `executionBackend: "managed-wrapper"`;
the demo just runs it without needing a live OpenClaw agent turn.

## 5. OpenClaw Plugin Hook Registration

Build and inspect the plugin:

```bash
cd ~/claw/packages/openclaw-plugin
npm run build

cd ~/claw
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

PowerShell should use `npm.cmd` if `npm.ps1` is blocked:

```powershell
cd C:\Users\29068\Desktop\claw\packages\openclaw-plugin
npm.cmd run build
```

Expected result from runtime inspect:

```text
before_tool_call
after_tool_call
model_call_started
model_call_ended
```

What happened: OpenClaw loaded the TypeScript plugin entrypoint. The plugin can
observe tool/model lifecycle hooks and, for `exec`, can keep params unchanged,
inject markers, or rewrite the command to `claw-launch`.

## 6. Marker Mode For Built-In `exec`

Configure the plugin:

```json5
{
  plugins: {
    "hardware-scheduler": {
      endpoint: "http://127.0.0.1:8765",
      executionBackend: "marker"
    }
  }
}
```

Run an OpenClaw task that uses shell/exec. Then inspect:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
```

What happened: `before_tool_call` left the original shell command intact and
added these environment markers to `exec.params.env`:

```text
CLAW_EXECUTION_ID
CLAW_TOOL_CALL_ID
CLAW_RUN_ID
CLAW_SESSION_KEY_HASH
CLAW_COMMAND_DIGEST
```

This mode is useful when you want correlation with minimal interference in the
OpenClaw native `exec` path.

## 7. Managed-Wrapper Mode For Built-In `exec`

Configure the plugin:

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

Run an OpenClaw task that uses shell/exec, then inspect:

```bash
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
```

What happened:

- The plugin registered the original command with `POST /v2/executions`.
- The actual OpenClaw `exec.params.command` became:

```text
claw-launch run --execution-id <id> --token <one-time-token>
```

- The original command did not travel as a shell argument.
- `claw-launch` claimed the spec locally, ran the original command, and
  reported scope/exit.

## 8. Linux CPU Placement With cgroup cpuset

This feature is Linux-only and requires a writable cgroup v2 root for the
launcher. On a test machine:

```bash
sudo mkdir -p /sys/fs/cgroup/claw
sudo chown "$USER":"$USER" /sys/fs/cgroup/claw
export CLAW_CGROUP_ROOT=/sys/fs/cgroup/claw
```

Run the managed execution demo with placement:

```bash
cd ~/claw
python tools/demo_supported_features.py \
  --run-launcher \
  --cpu-set 0 \
  --numa-node 0 \
  --command "python -c \"import os; print('affinity', sorted(os.sched_getaffinity(0)))\""
```

Expected result includes:

```text
affinity [0]
execution scope:
  "kind": "cgroup-v2"
  "cgroup_path": "/sys/fs/cgroup/claw/demo-exec-..."
```

What happened:

- The execution spec included placement metadata.
- `claw-launch` created a per-execution cgroup under `CLAW_CGROUP_ROOT`.
- It wrote `cpuset.mems` before `cpuset.cpus`.
- It moved the child into the cgroup before executing the shell command.
- It called `sched_setaffinity` as a second CPU-placement guard.
- The sidecar stored a cgroup-v2 scope and can read cgroup resource counters.

If the cgroup root is unavailable or not writable, `claw-launch` falls back to
PID scope. The command still runs, but the scope will not show a cgroup path.

## 9. agent-test-bench Offline Integration

Preview the delegated benchmark command without changing the benchmark repo:

```bash
cd ~/claw
python tools/run_agent_test_bench.py --bench-root ~/agent-test-bench --dry-run -- \
  --provider deepseek \
  --model deepseek-chat \
  --benchmark swe-rebench \
  --scaffold openclaw \
  --container docker \
  --mcp-config none \
  --sample 1
```

Validate/import an existing run:

```bash
python tools/validate_agent_test_bench_run.py <run-dir> \
  --events-out artifacts/agent-test-bench-events.jsonl \
  --profiles-out artifacts/agent-test-bench-tool-profiles.json
```

What happened: this repository reads `agent-test-bench` traces and can generate
scheduler-compatible events/profiles. It does not modify OpenClaw core and does
not modify the external `agent-test-bench` checkout.

## 10. Test Suite For The Supported Surface

Run:

```bash
cd ~/claw
python tools/validate_contracts.py
pytest tests -q --basetemp .pytest-tmp-root

cd ~/claw/services/scheduler
pytest tests -q

cd ~/claw/packages/openclaw-plugin
npm test
npm run typecheck
```

Expected result in the current tree:

```text
contracts validate
root tests pass
scheduler tests pass
plugin tests pass
TypeScript typecheck passes
```

What happened: these commands verify the public protocol examples, offline
adapter/importer, sidecar API/launcher/sampler behavior, and TypeScript plugin
instrumentation.
