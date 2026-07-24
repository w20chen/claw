# Limits

- The current policy observes and records; it is not a CPU optimizer yet.
- Placement advice is advisory unless the launcher can apply it.
- Resource attribution is best with `executionBackend: "managed-wrapper"`.
- Tools without a trusted PID/cgroup are still traced, but resource fields may
  be null or `unattributed`.
- In SWE-Rebench host sandbox mode, internal tools can be attributed to the
  shared OpenClaw Docker sandbox cgroup. This improves isolation from the host
  runtime, but it is still not an exclusive per-tool PID/cgroup unless OpenClaw
  exposes a dedicated execution scope for that tool call.
- Full LLM content requires routing OpenClaw through the sidecar proxy.
- Docker, real task images, and a valid LLM key are required for live
  SWE-Rebench runs.
