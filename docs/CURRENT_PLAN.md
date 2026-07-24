# Current Plan

Current objective: keep this repository easy to run as an OpenClaw plugin,
sidecar, and SWE-Rebench batch runner.

## User Commands

Normal OpenClaw:

```bash
python -m pip install -e "services/scheduler[dev]"
cd packages/openclaw-plugin && npm install && npm run build && cd ../..
cp .env.example .env
python -m agent_scheduler.main --host 127.0.0.1 --port 8765
```

SWE-Rebench:

```bash
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
python -m swe_rebench.runner prepare --config swe_rebench/config.yaml
python -m swe_rebench.discover --sample 20 --out swe_rebench/tasks.json
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --dataset swe_rebench/tasks.json --sample 10 --parallelism 4 --export
```

## Validation

```bash
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root
cd services/scheduler && python -m pytest tests -q
cd packages/openclaw-plugin && npm test && npm run typecheck
```

## Not Run Locally

- Live SWE-Rebench Docker task execution requires Docker access, real task
  images, and a valid upstream LLM key/model configuration.
- `cd swe_rebench/bundle/plugin && npm.cmd run build` could not run in this
  Windows workspace because the bundled plugin does not have a local `tsc`
  executable installed.  The current bundled `dist` was validated with
  `node --test test/*.test.mjs`.
- `python -m mypy .` currently fails on pre-existing repository-wide typing
  issues, including missing `types-setuptools`, Windows/POSIX launcher
  attribute checks, and trace helper union-attr errors.
