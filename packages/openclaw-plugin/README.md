# OpenClaw Hardware Scheduler Plugin

Build:

```bash
npm install
npm run build
npm pack
```

Runtime config defaults:

- `endpoint=http://127.0.0.1:8765`
- `mode=observe`
- `failOpen=true`
- `sendRawParams=false`

Observe a live run with any model provider OpenClaw can list and run:

```bash
openclaw models list
export OPENCLAW_TEST_MODEL='<provider/model-from-openclaw-models-list>'
openclaw agent --local --agent main --model "$OPENCLAW_TEST_MODEL" --message 'Reply with exactly: openclaw-ok'
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
```

DeepSeek is optional. If you want it, install OpenClaw's provider plugin first:

```bash
openclaw plugins install @openclaw/deepseek-provider
openclaw gateway restart
openclaw onboard --auth-choice deepseek-api-key
openclaw models list --provider deepseek
```

Local vLLM is also optional and uses OpenClaw's `vllm` provider:

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

The plugin reports tool lifecycle events to the sidecar. It sends
privacy-preserving `operation_hint` values for `exec` commands when possible,
and forwards PID/container metadata as `resource_scope` if OpenClaw exposes it.
The sidecar stores recent runtime samples and exposes Prometheus metrics for
tool counts, durations, attribution status, active monitor windows, and
resource measurements.
