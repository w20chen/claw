# Review Log

## 2026-07-24 swe_rebench Integration Review

Completed:
- swe_rebench batch runner: `prepare` / `run` / `collect` / `cleanup`.
- Sidecar LLM proxy auto-normalises `/v1/models` (always-on, no config).
- Model name spoofing (`EXPOSE_MODEL` / `UPSTREAM_MODEL`) for OpenRouter etc.
- CLI `--config` works before or after subcommand.
- HuggingFace parquet task discovery via `swe_rebench.discover`.
- OpenRouter upstream support verified (docs + config).

Validation:
- All 33 scheduler tests pass (1 Windows xfail).
- All 33 plugin tests pass.
- All contract validations pass.
- TypeScript typecheck passes.

## 2026-07-16 Initial Self Review

Checks performed:

- Protocol fields avoid fabricated IDs.
- Raw params default to `null`.
- Placement is documented as advisory.
- Observe mode fail behavior does not block tools.
- Sidecar writes use parameterized SQLite statements.
