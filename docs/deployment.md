# Deployment

This project ships two deployable pieces:

- `services/scheduler`: Python sidecar
- `packages/openclaw-plugin`: OpenClaw plugin

For the normal local user flow, start with [operator-guide.md](operator-guide.md).

## Development Build

```bash
python -m pip install -e "services/scheduler[dev]"

cd packages/openclaw-plugin
npm install
npm run build
cd ../..
```

Run validation:

```bash
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root

cd services/scheduler
python -m pytest tests -q

cd ../../packages/openclaw-plugin
npm test
npm run typecheck
```

## Sidecar

Local process:

```bash
cp .env.example .env
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

Docker Compose starts only the sidecar and publishes it on
`127.0.0.1:8765`:

```bash
docker compose up --build scheduler
```

## Plugin Package

Build an npm tarball:

```bash
cd packages/openclaw-plugin
npm pack
```

For local development, link the package directly:

```bash
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins enable hardware-scheduler
```

## Python Package

Build a wheel from the sidecar package:

```bash
cd services/scheduler
python -m build
```

If editable installs are unavailable in the target environment:

```bash
python -m pip install "services/scheduler[dev]"
```

## SWE-Rebench

SWE-Rebench uses a generated runtime bundle instead of a long-lived deployment:

```bash
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
python -m swe_rebench.runner prepare --config swe_rebench/config.yaml
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --prepare --dataset swe-bench.json --sample 10 --parallelism 4 --export
```

See [../swe_rebench/README.md](../swe_rebench/README.md) for task formats,
provider examples, outputs, and trace inspection.
