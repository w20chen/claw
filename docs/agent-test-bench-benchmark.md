# agent-test-bench Benchmark Adapter

This project integrates `agent-test-bench` benchmarks as an external harness.
It does not copy benchmark runners into the OpenClaw plugin and does not modify
OpenClaw core or the `agent-test-bench` checkout.

## Run

Use the wrapper when you want one command to run the original benchmark and
then validate/import the produced traces:

```bash
export AGENT_TEST_BENCH_ROOT=~/agent-test-bench
python3 tools/run_agent_test_bench.py -- \
  --provider deepseek --model deepseek-chat \
  --benchmark swe-rebench --scaffold openclaw \
  --container docker --mcp-config none \
  --sample 1
```

Everything after `--` is passed verbatim to:

```bash
PYTHONPATH=src python3 -m trace_collect.cli ...
```

The wrapper sets `PYTHONPATH` to `<agent-test-bench>/src`, runs from the
`agent-test-bench` root, and lets `agent-test-bench` keep ownership of task
selection, image choice, fixed-image preparation, container lifecycle, trace
layout, and resume behavior.

Preview the delegated command without running a benchmark:

```bash
python3 tools/run_agent_test_bench.py --dry-run -- \
  --provider deepseek --model deepseek-chat \
  --benchmark swe-rebench --scaffold openclaw \
  --container docker --mcp-config none \
  --sample 1
```

## Validate Existing Runs

Validate an existing run directory or one `trace.jsonl` file:

```bash
python3 tools/validate_agent_test_bench_run.py ~/agent-test-bench/traces/.../run
```

Generate scheduler-compatible offline artifacts while validating:

```bash
python3 tools/validate_agent_test_bench_run.py <run-dir> \
  --events-out artifacts/agent-test-bench-events.jsonl \
  --profiles-out artifacts/agent-test-bench-tool-profiles.json
```

The validator checks:

- canonical `trace.jsonl` files exist
- `trace_metadata.trace_format_version == 5`
- `tool_exec` actions are present unless `--allow-empty-tools` is used
- image metadata is discoverable from `run_manifest.json` / `results.json`
- scheduler event/profile exports can be generated from the original trace

## Boundary

The adapter is intentionally outside the online plugin runtime. Benchmark
containers, datasets, mirrors, task images, and trace files remain governed by
`agent-test-bench`. The OpenClaw plugin still focuses on live hook observation
and sidecar scheduling.
