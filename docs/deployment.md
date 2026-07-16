# Deployment

Development:

```bash
python -m pip install -e 'services/scheduler[dev]'
cd packages/openclaw-plugin && npm install && cd ../..
make dev-sidecar
make build-plugin
make test
```

Python wheel:

```bash
cd services/scheduler
python -m build
```

npm tarball:

```bash
cd packages/openclaw-plugin
npm pack
```

Docker compose starts only the sidecar and does not mount the Docker socket.
The container binds `0.0.0.0:8765` internally and publishes
`127.0.0.1:8765` on the host.

```bash
docker compose up --build scheduler
```
