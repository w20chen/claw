# Compatibility

Expected local tools:

- Python 3.10+
- Node.js and npm
- OpenClaw CLI 2026.7.1 or newer
- Docker for SWE-Rebench

Windows notes:

- Use `npm.cmd` or `openclaw.cmd` if PowerShell blocks `.ps1` shims.
- Use `--basetemp .pytest-tmp-root` for pytest.

Validate:

```bash
python tools/validate_contracts.py
python -m pytest tests -q --basetemp .pytest-tmp-root

cd packages/openclaw-plugin
npm test
npm run typecheck
```
