# Compatibility

## Local Checks

- `node --version`: `v24.18.0`
- `npm.cmd --version`: `11.16.0`
- Official OpenClaw installed with `npm.cmd install -g openclaw@latest`.
- Official CLI path: `C:\Users\29068\AppData\Roaming\npm\openclaw.cmd`.
- `openclaw.cmd --version`: `OpenClaw 2026.7.1 (2d2ddc4)`.
- `openclaw.cmd plugins list`: succeeds and loads stock plugins.
- `openclaw.cmd plugins install --link C:\Users\29068\Desktop\claw\packages\openclaw-plugin`: succeeds.
- `openclaw.cmd plugins inspect hardware-scheduler --runtime --json`: succeeds
  with `hookCount: 4` and typed hooks:
  - `before_tool_call`
  - `after_tool_call`
  - `model_call_started`
  - `model_call_ended`
- Bare `openclaw` in PowerShell may be blocked by the generated `openclaw.ps1`
  shim under the current script execution policy. Use `openclaw.cmd` unless the
  user explicitly chooses to relax PowerShell execution policy.

## OpenClaw SDK

The implementation follows the current public documentation and local
OpenClaw 2026.7.1 shape:

- `openclaw.plugin.json`
- `package.json` with `openclaw.extensions`
- `definePluginEntry` imported from `openclaw/plugin-sdk/plugin-entry`
- typed hooks registered with `api.on(...)`
- hooks: `before_tool_call`, `after_tool_call`, `model_call_started`,
  `model_call_ended`

Before release, install the official OpenClaw SDK and run:

```bash
cd packages/openclaw-plugin
npm install
npm run typecheck
npm run build
openclaw.cmd plugins install --link . --force
openclaw.cmd plugins inspect hardware-scheduler --runtime --json
```

Do not claim end-to-end OpenClaw runtime compatibility until that runtime
inspect confirms the hooks.
