# OpenClaw Trace Recorder Plugin

Build:

```bash
npm install
npm run build
npm pack
```

Key config:

- `endpoint=http://127.0.0.1:8765`
- `mode=observe`
- `recordRawTrace=false`
- `executionBackend=hook-only`

Set `recordRawTrace=true` to send OpenClaw hook-visible model input/output,
tool args/results, and raw hook payloads to the sidecar trace writer.

For stronger `exec` resource attribution, use `managed-wrapper`:

```json5
{
  plugins: {
    "hardware-scheduler": {
      endpoint: "http://127.0.0.1:8765",
      recordRawTrace: true,
      executionBackend: "managed-wrapper",
      launcherPath: "claw-launch",
      securityBoundaryAccepted: true
    }
  }
}
```

The plugin remains a normal OpenClaw plugin. It does not modify OpenClaw core.
