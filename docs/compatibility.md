# Compatibility

## Linux Default

The supported operator path assumes Linux with:

- Python 3.12
- Node.js 24 and npm
- OpenClaw 2026.7.1 as the validated baseline
- Docker or Podman only when running `agent-test-bench` benchmarks

Install the validated OpenClaw CLI version:

```bash
npm install -g openclaw@2026.7.1
openclaw --version
```

The plugin package declares `openclaw >=2026.7.1` as a peer dependency, but
newer OpenClaw releases must be revalidated before use because the integration
depends on plugin SDK entrypoints, manifest loading, hook names, and hook
payload shapes. Avoid `openclaw@latest` unless the runtime inspect checks below
are rerun successfully on the target machine.

Expected validation commands:

```bash
python -m pip install -e 'services/scheduler[dev]'

cd packages/openclaw-plugin
npm install
npm run typecheck
npm run build
npm test

cd ../..
python tools/validate_contracts.py
python -m pytest tests/test_agent_test_bench_adapter.py tests/test_import_agent_test_bench_trace.py --basetemp .pytest-tmp-root

cd services/scheduler
python -m pytest

cd ../..
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins inspect hardware-scheduler --runtime --json
```

If `pip install -e 'services/scheduler[dev]'` fails because the build backend
does not expose `build_editable`, upgrade packaging tools or use the
non-editable install path:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install 'services/scheduler[dev]'
```

## OpenClaw SDK

The implementation follows the current public documentation and local
OpenClaw 2026.7.1 shape:

- `openclaw.plugin.json`
- `package.json` with `openclaw.extensions`
- `definePluginEntry` imported from `openclaw/plugin-sdk/plugin-entry`
- typed hooks registered with `api.on(...)`
- hooks: `before_tool_call`, `after_tool_call`, `model_call_started`,
  `model_call_ended`

Do not claim end-to-end OpenClaw runtime compatibility until runtime inspect
confirms the hooks on the target Linux machine.

When upgrading OpenClaw:

```bash
npm install -g openclaw@<target-version>
openclaw --version
openclaw plugins install --link ./packages/openclaw-plugin
openclaw plugins inspect hardware-scheduler --runtime --json
```

Keep `packages/openclaw-plugin/package.json` `peerDependencies.openclaw` in sync
with the oldest OpenClaw version that has passed this runtime inspection.

## Windows Notes

Windows PowerShell may prefer generated `.ps1` npm shims and block them under
the current execution policy. Use `npm.cmd` and `openclaw.cmd` only for manual
Windows validation. The repository Makefile and operator docs intentionally use
Linux commands by default.
