# Architecture

The system has three online components:

1. A TypeScript OpenClaw plugin that registers typed hooks, redacts tool
   metadata, calls the sidecar, applies observe/enforce behavior, and can
   instrument built-in `exec` calls.
2. A Python sidecar that owns scheduling policy, persistence, prediction,
   calibration, hardware inventory, execution registration, metrics, and
   optional agent-test-bench-style `trace.jsonl` output.
3. A host launcher/collector path. This snapshot includes a Python reference
   `claw-launch` that owns process creation, signal forwarding, exit-code
   preservation, PID/cgroup scope registration, and Linux CPU placement via
   cpuset plus `sched_setaffinity`. NUMA memory policy and PMU profiling remain
   planned.

The plugin no longer treats PID discovery inside arbitrary hook payloads as a
reliable execution boundary. The trusted path is:

```text
before_tool_call
  -> scheduler decision
  -> execution_id generation
  -> marker env injection or managed-wrapper command rewrite
  -> launcher/collector registers cgroup-backed execution scope
```

`marker` mode keeps the original command unchanged and only adds environment
markers. `managed-wrapper` mode stores a one-time execution spec in the sidecar
and changes the OpenClaw `exec` command to invoke `claw-launch`. The Python
reference launcher claims that spec over local HTTP, runs the original command,
and registers a trusted PID or cgroup-v2 scope. The same protocol is intended
for a later Rust/Go launcher with stronger cleanup and profiling support.

Every observed tool completion can be recorded as a `tool_exec` trace action.
CPU, memory, disk, network, and context-switch measurements are precise only
when that action has a trusted PID or cgroup scope. Network I/O is currently a
best-effort Linux namespace counter read from `/proc/<pid>/net/dev`; exact
per-tool network accounting is future cgroup/eBPF collector work.

`agent-test-bench` is deliberately offline-only. It can export traces and
profiles consumed by this repository, and this sidecar can now emit compatible
v5-shaped live traces, but the runtime sidecar does not import its agent
scaffold or benchmark runner.
