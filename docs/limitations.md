# Limitations

- `placement_advice` is not placement enforcement.
- Generic OpenClaw hooks cannot guarantee control over arbitrary tool
  subprocess CPU affinity.
- Real CPU/NUMA/LLC enforcement requires a managed executor, container layer, or
  OpenClaw execution-layer adapter.
- `agent_end` is not registered in the MVP.
- KV cache and GPU serving joint scheduling are not implemented.
- Observe mode never changes agent behavior.
- Hook and HTTP timeouts limit admission-control precision.
- If OpenClaw does not expose a tool PID, resource samples are intentionally
  marked `unattributed`; only duration, prediction, and command-category
  telemetry are available for that tool call.
