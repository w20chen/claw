# Protocol Reference

Most users do not need this file. Run the project with:

- [operator-guide.md](operator-guide.md)
- [../swe_rebench/README.md](../swe_rebench/README.md)

Public protocol schemas live in `contracts/`.

Validate them:

```bash
python tools/validate_contracts.py
```

Main event families:

- `scheduler.v1` tool before/completed events
- model start/end events
- `scheduler.v2` managed execution registration and scope lookup
- schema v6 trace records written as JSONL
