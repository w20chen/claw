# Security Notes

- The plugin runs as a normal OpenClaw plugin.
- This project does not modify OpenClaw core.
- Use `mode: "observe"` unless you intentionally want enforcement behavior.
- `managed-wrapper` rewrites `exec` commands and therefore requires
  `securityBoundaryAccepted: true`.
- Do not store provider API keys in committed config files. Prefer
  `${LLM_API_KEY}` in `swe_rebench/config.yaml` and `.env` for local sidecar
  overrides.
