# OpenClaw Plugin

The plugin package is `packages/openclaw-plugin`.

Link it into the local OpenClaw installation from the project root:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

The verified local runtime reports `hookCount: 4`.

It registers:

- `before_tool_call`
- `after_tool_call`
- `model_call_started`
- `model_call_ended`

It does not register `agent_end`, `llm_input`, `llm_output`,
`before_agent_run`, or `registerAgentHarness` in the MVP.

The plugin records tool lifecycle events and can send hook-visible raw
tool args/results when configured with `recordRawTrace=true`. Full LLM
request/response capture is not taken from model hooks; the default full-trace
path routes OpenClaw's OpenAI-compatible provider through the sidecar LLM proxy.

## Exec Instrumentation

`executionBackend` controls whether `before_tool_call` modifies built-in
`exec` params:

- `hook-only`: default observer behavior. No params are rewritten.
- `marker`: injects `CLAW_EXECUTION_ID`, `CLAW_TOOL_CALL_ID`, `CLAW_RUN_ID`,
  `CLAW_SESSION_KEY_HASH`, and `CLAW_COMMAND_DIGEST` into `params.env`.
- `managed-wrapper`: registers a one-time execution spec with the sidecar and
  rewrites `params.command` to run `launcherPath`.

`managed-wrapper` requires `securityBoundaryAccepted=true`. The Python
reference `claw-launch` installed by the scheduler package preserves stdio,
forwards common POSIX signals, returns the original exit code, and registers a
trusted PID or cgroup-v2 scope. On Linux it can create a per-execution cgroup
under `CLAW_CGROUP_ROOT`, write `cpuset.mems` before `cpuset.cpus`, move the
child before `exec`, and apply `sched_setaffinity`. A later static host
launcher should harden cleanup, NUMA memory policy, and PMU/ksys/VTune
wrapping.

The plugin no longer recursively searches event/context payloads for PID-like
keys. `after_tool_call` uses a fixed hook-provided `resource_scope` /
`execution_scope` when present, or asks the sidecar for the scope associated
with the correlated `execution_id`.
