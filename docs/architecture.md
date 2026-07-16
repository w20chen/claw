# Architecture

The system has two online components:

1. A TypeScript OpenClaw plugin that registers typed hooks, redacts tool
   metadata, calls the sidecar, and applies observe/enforce behavior.
2. A Python sidecar that owns scheduling policy, persistence, prediction,
   calibration, hardware inventory, and metrics.

`agent-test-bench` is deliberately offline-only. It can export traces and
profiles consumed by this repository, but the runtime sidecar does not import
its agent scaffold or benchmark runner.
