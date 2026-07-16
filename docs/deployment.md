# Deployment

Development:

```bash
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
