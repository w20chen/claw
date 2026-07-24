# OpenClaw Agent Scheduler

OpenClaw Agent Scheduler is an OpenClaw plugin plus a Python sidecar. It records
OpenClaw model/tool activity, captures full LLM traffic through an
OpenAI-compatible proxy, and samples per-tool CPU, memory, disk, and network
usage when a trusted PID or cgroup scope is available.

The project does not modify OpenClaw core. JSON Schema files in `contracts/`
are the public protocol source of truth.

## Choose Your Path

- Use OpenClaw normally with tracing and resource recording:
  [docs/operator-guide.md](docs/operator-guide.md)
- Run SWE-Rebench batches in containers:
  [swe_rebench/README.md](swe_rebench/README.md)
- Check supported features and validation commands:
  [docs/supported-features.md](docs/supported-features.md)
- Understand sidecar endpoints and configuration:
  [docs/sidecar.md](docs/sidecar.md)
- Understand plugin hook behavior:
  [docs/openclaw-plugin.md](docs/openclaw-plugin.md)

## Normal OpenClaw Quick Start

Install and build:

```bash
python -m pip install -e "services/scheduler[dev]"

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

Start the sidecar:

```bash
cp .env.example .env
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

In another shell, install and enable the plugin:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
```

Configure OpenClaw to send model traffic through the sidecar proxy:

```bash
openclaw onboard --non-interactive --accept-risk --skip-health \
  --mode local \
  --auth-choice vllm \
  --custom-base-url "http://127.0.0.1:8765/v1" \
  --custom-api-key "$LLM_API_KEY" \
  --custom-model-id "deepseek-v4-flash"
```

Configure the plugin. Replace the launcher path with the absolute path printed
by `claw-launch --help` / your shell's command lookup:

```bash
cat <<'JSON5' | openclaw config patch --stdin
{
  plugins: {
    entries: {
      "hardware-scheduler": {
        enabled: true,
        config: {
          endpoint: "http://127.0.0.1:8765",
          mode: "observe",
          failOpen: true,
          recordRawTrace: true,
          executionBackend: "managed-wrapper",
          launcherPath: "/absolute/path/to/claw-launch",
          securityBoundaryAccepted: true
        }
      }
    }
  }
}
JSON5
```

Run an agent and inspect traces:

```bash
openclaw agent --local --agent main --model "vllm/deepseek-v4-flash" \
  --message "Use the shell to run: python -c 'print(\"trace-ok\")'. Then summarize the result."

curl "http://127.0.0.1:8765/v1/tools/recent?limit=5"
ls data/traces
python tools/inspect_trace.py data/traces/<trace-file>.jsonl --all --details
```

For a complete step-by-step flow, including cgroup notes and troubleshooting,
use [docs/operator-guide.md](docs/operator-guide.md).

## SWE-Rebench Quick Start

```bash
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
# Edit llm.api_key, or leave api_key: "${LLM_API_KEY}" and export LLM_API_KEY.

python -m swe_rebench.runner prepare --config swe_rebench/config.yaml

python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --image swebrebench/sweb.eval.x86_64.django:latest \
  --task-id django__example \
  --problem "Fix the bug described by the benchmark task."
```

Batch usage, datasets, exports, and provider examples are documented in
[swe_rebench/README.md](swe_rebench/README.md).

## Important Defaults

- Sidecar URL: `http://127.0.0.1:8765`
- Sidecar trace directory: `data/traces` when using `.env.example`
- LLM proxy upstream: DeepSeek by default
- Plugin mode: `observe`
- Plugin raw trace capture: disabled by package default, enabled in the
  recommended config with `recordRawTrace: true`
- Resource attribution: strongest with `executionBackend: "managed-wrapper"`

## Validation

```bash
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
```

On Windows PowerShell, use `npm.cmd` or `openclaw.cmd` if `.ps1` shims are
blocked.
