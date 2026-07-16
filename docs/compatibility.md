# Compatibility

## Local Checks

- `node --version`: `v24.18.0`
- `npm.cmd --version`: `11.16.0`
- `openclaw --version`: failed because the local command resolves to the
  `agent-test-bench` OpenClaw agent harness and does not support plugin CLI
  version inspection.

## OpenClaw SDK

The implementation follows the current public documentation shape:

- `openclaw.plugin.json`
- `definePluginEntry`
- `api.on(...)`
- hooks: `before_tool_call`, `after_tool_call`, `model_call_started`,
  `model_call_ended`

Before release, install the official OpenClaw SDK and run:

```bash
cd packages/openclaw-plugin
npm install
npm run typecheck
npm run build
openclaw plugins install --link . --force
openclaw plugins inspect hardware-scheduler --runtime --json
```

Do not claim end-to-end OpenClaw runtime compatibility until that runtime
inspect confirms the hooks.
