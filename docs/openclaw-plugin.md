# OpenClaw Plugin

The plugin package is `packages/openclaw-plugin`.

It is linked into the local OpenClaw installation:

```powershell
openclaw.cmd plugins install --link C:\Users\29068\Desktop\claw\packages\openclaw-plugin
openclaw.cmd plugins inspect hardware-scheduler --runtime --json
```

The verified local runtime reports `hookCount: 4`.

It registers:

- `before_tool_call`
- `after_tool_call`
- `model_call_started`
- `model_call_ended`

It does not register `agent_end`, `llm_input`, `llm_output`,
`before_agent_run`, or `registerAgentHarness` in the MVP.

The plugin sends only allowlisted metadata and parameter features by default.
Set `sendRawParams=true` only when explicitly required; recursive redaction is
still applied before transport.
