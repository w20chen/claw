# Deployment

Development:

```bash
python3 -m pip install -e 'services/scheduler[dev]'
cd packages/openclaw-plugin && npm install && cd ../..
make dev-sidecar
make build-plugin
make test
```

If editable install is unavailable in the target Python environment, use:

```bash
python3 -m pip install 'services/scheduler[dev]'
```

Python wheel:

```bash
cd services/scheduler
python3 -m build
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

## SWE-Rebench

See `swe_rebench/README.md` for the full guide. Quick setup:

```bash
# 1. Config
cp swe_rebench/config.example.yaml swe_rebench/config.yaml
# Edit llm.api_key (required), model, upstream URL

# 2. Prepare the runtime bundle
python -m swe_rebench.runner prepare --config swe_rebench/config.yaml

# 3. Discover tasks from HuggingFace (optional)
python -m swe_rebench.discover --sample 10 --out ./swe-bench.json

# 4. Run (single task or batch)
python -m swe_rebench.runner run --config swe_rebench/config.yaml \
  --prepare --dataset ./swe-bench.json --sample 10 --parallelism 4 --export
```

### OpenRouter

Set in `swe_rebench/config.yaml`:

```yaml
llm:
  api_key: "sk-or-v1-xxxxxxxx"
  upstream_base_url: "https://openrouter.ai/api/v1"
  model: "deepseek/deepseek-chat"
  openclaw_model_ref: "vllm/deepseek-chat"
```

The sidecar automatically normalises `/v1/models` responses and translates
model names (e.g. `deepseek-chat` → `deepseek/deepseek-chat`) when
`AGENT_SCHEDULER_LLM_PROXY_EXPOSE_MODEL` and
`AGENT_SCHEDULER_LLM_PROXY_UPSTREAM_MODEL` are set in the entrypoint.
