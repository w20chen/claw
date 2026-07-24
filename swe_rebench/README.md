# SWE-Rebench Batch Runner

Use this when you want to run many SWE-Rebench tasks through OpenClaw with the
hardware-scheduler plugin and sidecar tracing enabled.

## Setup

```bash
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
# Edit llm.api_key, or keep api_key: "${LLM_API_KEY}" and export LLM_API_KEY.

python -m swe_rebench.runner prepare --config swe_rebench/config.yaml
```

Default provider config is DeepSeek:

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

## Discover Tasks

```bash
python -m swe_rebench.discover --sample 20 --out swe_rebench/tasks.json
```

Discovery first checks `AGENT_TEST_BENCH_ROOT/data/swe-rebench/tasks.json` or
`../agent-test-bench/data/swe-rebench/tasks.json`. If no local task file is
found, it falls back to the HuggingFace dataset path.

Useful filters:

```bash
python -m swe_rebench.discover --repo django/django --sample 10 --out django-tasks.json
python -m swe_rebench.discover --instance-ids django__django-12345 --out one-task.json
```

## Run A Batch

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --prepare \
  --dataset swe_rebench/tasks.json \
  --sample 10 \
  --parallelism 4 \
  --export
```

Dry-run task selection:

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --dataset swe_rebench/tasks.json \
  --skip 10 \
  --sample 3 \
  --dry-run
```

Run exact instances:

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --dataset swe_rebench/tasks.json \
  --instance-ids django__django-12345,sympy__sympy-67890 \
  --export
```

Run a repo subset:

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --dataset swe_rebench/tasks.json \
  --repo django/django \
  --sample 5 \
  --parallelism 2
```

## Run One Task

```bash
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --image swebrebench/sweb.eval.x86_64.django:latest \
  --task-id django__example \
  --problem "Fix the bug described by the benchmark task."
```

## Outputs

```text
swe_rebench/
  traces/<task_id>/*.jsonl
  export/
  report.json
```

Inspect:

```bash
python tools/inspect_trace.py swe_rebench/traces/<task_id>/<trace-file>.jsonl --all --details
python tools/inspect_trace.py swe_rebench/traces/<task_id>/<trace-file>.jsonl --all --timeline
```

Collect/export existing traces:

```bash
python -m swe_rebench.runner collect --config swe_rebench/config.yaml
```

## Common Options

| Option | Purpose |
| --- | --- |
| `--sample N` | Run first N selected tasks. |
| `--skip N` | Skip N tasks before sampling. |
| `--instance-ids a,b` | Run exact task IDs. |
| `--repo owner/repo` | Filter by repo. |
| `--parallelism N` | Run N containers concurrently. |
| `--export` | Copy traces to `swe_rebench/export`. |
| `--dry-run` | Print selected tasks without starting containers. |
