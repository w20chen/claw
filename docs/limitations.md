# Limits

- The current policy observes and records; it is not a CPU optimizer yet.
- Placement advice is advisory unless the launcher can apply it.
- Resource attribution is best with `executionBackend: "managed-wrapper"`.
- Tools without a trusted PID/cgroup are still traced, but resource fields may
  be null or `unattributed`.
- Full LLM content requires routing OpenClaw through the sidecar proxy.
- Docker, real task images, and a valid LLM key are required for live
  SWE-Rebench runs.
