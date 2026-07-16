# OpenClaw Plugin

The plugin package is `packages/openclaw-plugin`.

Link it into the local OpenClaw installation from the project root:

```bash
openclaw plugins install --link ./packages/openclaw-plugin --force
openclaw plugins enable hardware-scheduler
openclaw plugins inspect hardware-scheduler --runtime --json
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
