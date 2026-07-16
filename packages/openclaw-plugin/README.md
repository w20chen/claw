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

Observe a live run:

```powershell
openclaw.cmd agent --local --agent main --model deepseek/deepseek-v4-flash --message "Reply with exactly: openclaw-ok"
curl http://127.0.0.1:8765/v1/tools/recent
curl http://127.0.0.1:8765/metrics
```

The plugin reports tool lifecycle events to the sidecar. It sends
privacy-preserving `operation_hint` values for `exec` commands when possible,
and forwards PID/container metadata as `resource_scope` if OpenClaw exposes it.
The sidecar stores recent runtime samples and exposes Prometheus metrics for
tool counts, durations, attribution status, active monitor windows, and
resource measurements.
