# SWE-Rebench Integration

The `swe_rebench` package runs SWE-Rebench/SWE-Bench style tasks in Docker
containers. Each container gets a generated `/claw` runtime bundle containing
the OpenClaw plugin, scheduler sidecar, setup script, and entrypoint.

Each task writes traces to a dedicated host directory under
`swe_rebench/traces/<task_id>/`.

## Requirements

- Python 3.10+
- Docker daemon access
- Network access from containers
- A valid OpenAI-compatible LLM API key

## Quick Start

```bash
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
# Edit llm.api_key, or use api_key: "${LLM_API_KEY}" and export LLM_API_KEY.

python -m swe_rebench.runner prepare --config swe_rebench/config.yaml

python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --image swebrebench/sweb.eval.x86_64.django:latest \
  --task-id django__example \
  --problem "Fix the bug described by the benchmark task."
```

The runner exits non-zero if any task fails.

## Configure The LLM Provider

Only `llm.api_key` is required for the default DeepSeek path:

```yaml
llm:
  api_key: "${LLM_API_KEY}"
  upstream_base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  openclaw_model_ref: "vllm/deepseek-v4-flash"
```

OpenRouter example:

```yaml
llm:
  api_key: "${LLM_API_KEY}"
  upstream_base_url: "https://openrouter.ai/api/v1"
  model: "deepseek/deepseek-chat"
  openclaw_model_ref: "vllm/deepseek-chat"
```

Custom OpenAI-compatible endpoint:

```yaml
llm:
  api_key: "${LLM_API_KEY}"
  upstream_base_url: "https://your-api.example.com/v1"
  model: "your-model"
  openclaw_model_ref: "vllm/your-model"
```

The sidecar normalizes `/v1/models` for OpenClaw. When the upstream model name
differs from the model OpenClaw should see, the generated entrypoint sets model
translation variables automatically from the config.

## Run Tasks

Single task:

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --image <docker-image> \
  --task-id <id> \
  --problem "<problem statement>"
```

Simple task list:

```json
[
  {
    "instance_id": "django__example",
    "image": "swebrebench/sweb.eval.x86_64.django:latest",
    "problem_statement": "Fix the bug..."
  }
]
```

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --tasks tasks.json \
  --parallelism 4 \
  --export
```

SWE-Bench/SWE-Rebench dataset:

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --prepare \
  --dataset swe-bench.json \
  --sample 10 \
  --parallelism 4 \
  --export
```

Use `--dry-run` to confirm task loading without starting containers:

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --dataset swe-bench.json \
  --sample 3 \
  --dry-run
```

## Discover Tasks

If the optional discovery dependencies and network access are available:

```bash
python -m swe_rebench.discover --sample 10 --out swe-bench.json
python -m swe_rebench.discover --repo django/django --out django-tasks.json
```

## Outputs

Default paths:

```text
swe_rebench/
  traces/<task_id>/*.jsonl
  export/
  report.json
```

The report contains per-task status, exit code, trace files, trace line count,
and duration.

Export traces after a completed run:

```bash
python -m swe_rebench.runner collect --config swe_rebench/config.yaml
```

Inspect traces:

```bash
python tools/inspect_trace.py swe_rebench/traces/<task_id>/<trace-file>.jsonl --all --details
python tools/inspect_trace.py swe_rebench/traces/<task_id>/<trace-file>.jsonl --all --timeline
```

## Main Config Fields

| Field | Default | Purpose |
| --- | --- | --- |
| `llm.api_key` | `${LLM_API_KEY}` | Upstream LLM key. |
| `llm.upstream_base_url` | `https://api.deepseek.com` | OpenAI-compatible upstream URL. |
| `llm.model` | `deepseek-v4-flash` | Upstream model name. |
| `llm.openclaw_model_ref` | `vllm/deepseek-v4-flash` | Model name passed to `openclaw agent`. |
| `docker.memory_limit` | `8g` | Per-container memory limit. |
| `docker.cpus` | `4` | Per-container CPU limit. |
| `docker.network_mode` | `bridge` | Docker network mode. |
| `batch.parallelism` | `4` | Concurrent containers. |
| `batch.task_timeout_seconds` | `1800` | Per-task timeout. |
| `output.trace_root` | `./swe_rebench/traces` | Per-task trace root. |
| `output.flat_export_dir` | `./swe_rebench/export` | Flat trace export destination. |

See `swe_rebench/config.example.yaml` for all fields.

## How It Works

```text
host runner
  -> prepare runtime bundle
  -> start one container per task
  -> /claw/entrypoint.sh installs runtime dependencies
  -> sidecar starts on 127.0.0.1:8765 inside the container
  -> OpenClaw is onboarded to the sidecar LLM proxy
  -> hardware-scheduler plugin is installed and enabled
  -> openclaw agent --local runs the task
  -> traces are written to the mounted /traces directory
```

The integration copies plugin and sidecar source into the bundle. It does not
modify OpenClaw core.
