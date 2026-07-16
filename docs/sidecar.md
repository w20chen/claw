# Scheduler Sidecar

The sidecar package is `services/scheduler`.

Endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/status`
- `GET /metrics`
- `POST /v1/decisions/tool`
- `POST /v1/events/tool-completed`
- `POST /v1/events/model`

SQLite is used for lightweight persistence. Writes are parameterized and use
idempotent keys so duplicate events do not crash the service.
