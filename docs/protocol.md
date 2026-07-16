# Protocol

The public tool/model event protocol version is `scheduler.v1`. Execution
registration uses `scheduler.v2` endpoints because it changes the runtime
execution boundary for `exec`.

All messages include common fields:

- `schema_version`
- `event_id`
- `occurred_at`
- `plugin_version`
- `run_id`
- `session_id`
- `session_key`
- `agent_id`

Missing OpenClaw IDs are represented as explicit `null` values. The sidecar
does not fabricate IDs.

Tool request messages may include:

- `operation_hint`: a privacy-preserving category derived from tool arguments,
  for example `pytest`, `grep`, or `git`. This lets the sidecar match
  agent-test-bench style `exec-*` profiles without transporting the full shell
  command.
- `resource_scope`: optional execution metadata such as `pid`,
  `process_start_time`, `container_id`, or cgroup-v2 fields such as
  `execution_id`, `root_pid`, and `cgroup_path`. PID metrics are only
  attributed when this scope is present and readable.

The plugin only trusts fixed `resource_scope` / `execution_scope` fields. It
does not recursively search arbitrary hook payloads for `pid`-like keys.

## Execution Registration

`POST /v2/executions` registers an `exec` invocation before it runs. The request
contains an `execution_id`, IDs/digests for correlation, the original command,
workdir/host, placement/profiling metadata, and backend:

- `marker`: the OpenClaw command is preserved and env markers are injected.
- `managed-wrapper`: OpenClaw runs `claw-launch`; the original command is
  retrieved from the sidecar by one-time token.

The response includes a one-time token and expiry timestamp. Tokens and raw
commands are held in sidecar memory in this snapshot; they are not written to
SQLite.

`POST /v2/executions/claim` is called by `claw-launch` with the one-time token.
The claim consumes that token and returns:

- original command
- workdir/host
- placement/profiling metadata
- `update_token` for later lifecycle updates

`POST /v2/executions/{execution_id}/started` records the trusted execution
scope. A Python reference launcher currently sends PID scope fields. A future
cgroup-capable launcher should also send `cgroup_path`, making the scope
`kind: "cgroup-v2"`.

`POST /v2/executions/{execution_id}/exited` records the original process exit
code or terminating signal.

`GET /v2/executions/{execution_id}/scope` returns the trusted execution scope
once a launcher/collector has registered it.
