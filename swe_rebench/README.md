# SWE-Rebench Integration

Runs swe-rebench benchmark tasks inside Docker containers with full
OpenClaw + sidecar trace collection.  Each task produces an independent
`trace.jsonl` file capturing all LLM calls, tool executions, and
resource usage.

## Quick Start

```bash
# 1. Copy and edit config
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
# Edit: set llm.api_key to your DeepSeek / OpenAI API key

# 2. Prepare the runtime bundle (one-time)
cd /path/to/claw
python -m swe_rebench.runner prepare --config swe_rebench/config.yaml

# 3. Run a single task
python -m swe_rebench.runner run \
  --config swe_rebench/config.yaml \
  --image swebrebench/sweb.eval.x86_64.django:latest \
  --task-id django__test \
  --problem "Fix the XSS vulnerability in the admin view..."

# 4. Collect and export traces
python -m swe_rebench.runner collect --config swe_rebench/config.yaml
```

## Configuration

Copy and edit the example config:

```bash
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
```

Minimal config (`swe_rebench/config.yaml`):

```yaml
llm:
  api_key: "${LLM_API_KEY}"          # or set LLM_API_KEY in env
  upstream_base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  openclaw_model_ref: "vllm/deepseek-v4-flash"

docker:
  host: "unix:///var/run/docker.sock"
  memory_limit: "8g"
  cpus: 4

batch:
  parallelism: 4
  task_timeout_seconds: 1800

output:
  trace_root: "./swe_rebench/traces"
  flat_export_dir: "./swe_rebench/export"
```

### OpenRouter

```yaml
llm:
  api_key: "sk-or-v1-xxxxxxxx"
  upstream_base_url: "https://openrouter.ai/api/v1"
  model: "deepseek/deepseek-chat"           # OpenRouter model ID
  openclaw_model_ref: "vllm/deepseek-chat"  # clean name for OpenClaw
```

The sidecar automatically normalises `/v1/models` responses and translates
model names so OpenClaw never sees the `provider/model` slash format.

## Discovering Tasks

From HuggingFace parquet datasets:

```bash
# Sample N tasks
python -m swe_rebench.discover --sample 10 --out ./swe-bench.json

# All tasks for a specific repo
python -m swe_rebench.discover --repo django/django --out ./django-tasks.json
```

## Batch Run

```bash
# From a swe-bench dataset JSON file
python -m swe_rebench.runner run \
  --config swe_rebench/config.yaml \
  --prepare \
  --dataset ./swe-bench.json \
  --sample 10 \
  --parallelism 4 \
  --export
```

## Trace Output

Each task writes its trace to `swe_rebench/traces/<task_id>/trace.jsonl`.
After a run, use `--export` to copy all traces to a flat directory:

```
swe_rebench/
├── export/                          # Flat export (--export flag)
│   ├── django__123_trace.jsonl
│   └── flask__456_trace.jsonl
├── traces/                          # Per-task raw output
│   ├── django__123/
│   │   └── trace.jsonl
│   └── flask__456/
│       └── trace.jsonl
└── report.json                      # Batch summary
```

Trace format follows the sidecar's standard `trace.jsonl` schema (v5-shaped
records with `llm_call` and `tool_exec` actions).

## Inspecting Traces

Use the existing trace inspector:

```bash
python tools/inspect_trace.py swe_rebench/traces/django__123/trace.jsonl --all --details
python tools/inspect_trace.py swe_rebench/traces/django__123/trace.jsonl --all --timeline
```

## Architecture

```
Host: swe_rebench/runner.py
  │
  ├─ prepare:  Builds /claw bundle (plugin + sidecar + scripts)
  │
  └─ run:      For each task:
       │
       └─ Container (swe-rebench image)
            │
            ├─ /claw/entrypoint.sh
            │   ├─ setup.sh          (install Node, OpenClaw, Python deps)
            │   ├─ Start sidecar     (port 8765, captures traces)
            │   ├─ Configure plugin  (points at 127.0.0.1:8765)
            │   ├─ openclaw run      (solves the task)
            │   └─ Stop sidecar      (flush traces)
            │
            └─ /traces/trace.jsonl → host volume mount
```

## Independence

This integration is completely independent:
- Does **not** modify `packages/openclaw-plugin/`
- Does **not** modify `services/scheduler/`
- Does **not** modify OpenClaw core
- The bundle copies (not modifies) plugin and scheduler source
- Existing `npm test`, `pytest`, `validate_contracts.py` all continue to pass

## Configuration

See `config.example.yaml` for all options.  Key settings:

| Setting | Description |
|---------|-------------|
| `llm.api_key` | Upstream LLM API key (passed to sidecar proxy) |
| `batch.parallelism` | Max concurrent containers |
| `batch.task_timeout_seconds` | Per-task timeout |
| `output.trace_root` | Where per-task traces are written |
| `output.flat_export_dir` | Flat export directory (set or use `--export`) |

## Requirements

- **Host**: Python 3.10+, Docker daemon running
- **Container**: Ubuntu/Debian-based swe-rebench images work best
  (setup.sh auto-detects apt/yum/dnf/apk)
- **Network**: Container needs internet access (for npm install, API calls)

## Task Definition Format

### Swe-bench Dataset (JSON)

```json
[
  {
    "instance_id": "django__django-12345",
    "docker_image": "swerebench/sweb.eval.x86_64.django:latest",
    "problem_statement": "Fix the bug where...",
    "repo": "django/django",
    "base_commit": "abc123..."
  }
]
```

### Simple Task List

```json
[
  {
    "instance_id": "my-task",
    "image": "swerebench/sweb.eval.x86_64.django:latest",
    "problem_statement": "..."
  }
]
```

### Single Task (CLI)

```bash
python -m swe_rebench.runner run \
  --image <docker-image> \
  --task-id <id> \
  --problem "<statement>"
```
