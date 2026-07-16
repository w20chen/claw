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
If OpenClaw does not pass `api.pluginConfig` to this hook-only plugin shape,
the plugin also accepts these environment overrides:

```bash
export OPENCLAW_HARDWARE_SCHEDULER_ENDPOINT=http://127.0.0.1:8765
export OPENCLAW_HARDWARE_SCHEDULER_RECORD_RAW_TRACE=true
export OPENCLAW_HARDWARE_SCHEDULER_EXECUTION_BACKEND=managed-wrapper
export OPENCLAW_HARDWARE_SCHEDULER_LAUNCHER_PATH=claw-launch
export OPENCLAW_HARDWARE_SCHEDULER_SECURITY_BOUNDARY_ACCEPTED=true
```

For stronger `exec` resource attribution, use `managed-wrapper`:

```json5
{
  plugins: {
    entries: {
      "hardware-scheduler": {
        enabled: true,
        config: {
          endpoint: "http://127.0.0.1:8765",
          recordRawTrace: true,
          executionBackend: "managed-wrapper",
          launcherPath: "claw-launch",
          securityBoundaryAccepted: true
        }
      }
    }
  }
}
```

The plugin remains a normal OpenClaw plugin. It does not modify OpenClaw core.
