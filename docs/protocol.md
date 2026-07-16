# Protocol

The public protocol version is `scheduler.v1`.

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
  `process_start_time`, and `container_id`. PID metrics are only attributed
  when this scope is present and readable.
