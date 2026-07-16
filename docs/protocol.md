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
