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

This scheduler is model-provider agnostic. It depends on OpenClaw plugin hooks,
not on a specific model vendor. Hosted APIs, OpenClaw provider plugins,
OpenRouter-style providers, and local OpenAI-compatible providers such as vLLM
are all acceptable as long as OpenClaw can list and run the selected
`provider/model` ref.

OpenClaw agent smoke tests should use a model ID reported by the local
OpenClaw install:

```bash
openclaw models list
openclaw models status
```

Provider API names are not guaranteed to be valid OpenClaw model IDs.

### DeepSeek

DeepSeek support requires OpenClaw's provider plugin:

```bash
openclaw plugins install @openclaw/deepseek-provider
openclaw gateway restart
openclaw onboard --auth-choice deepseek-api-key
openclaw models list --provider deepseek
```

The documented DeepSeek provider ID is `deepseek`, the auth environment
variable is `DEEPSEEK_API_KEY`, and the provider uses an OpenAI-compatible API
at `https://api.deepseek.com`. If Gateway runs as a daemon, the key must be
available to the daemon process, for example through `~/.openclaw/.env`.

Reference: https://docs.openclaw.ai/providers/deepseek

### vLLM

Local vLLM support uses OpenClaw's `vllm` provider and an OpenAI-compatible
HTTP API. The default base URL is `http://127.0.0.1:8000/v1`; it must expose
`/v1/models` and `/v1/chat/completions`.

```bash
export VLLM_API_KEY='vllm-local'
openclaw onboard --non-interactive \
  --mode local \
  --auth-choice vllm \
  --custom-base-url 'http://127.0.0.1:8000/v1' \
  --custom-api-key "$VLLM_API_KEY" \
  --custom-model-id '<your-vllm-model-id>'
openclaw models list --provider vllm
```

If the vLLM server does not enforce auth, any non-empty `VLLM_API_KEY` value is
enough for OpenClaw discovery.

Reference: https://docs.openclaw.ai/providers/vllm

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
