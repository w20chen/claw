#!/bin/bash
# Debug: test OpenClaw onboarding inside a swe-rebench container
set -euo pipefail
echo "=== Starting debug test ==="

export PATH="/usr/local/bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LLM_API_KEY="sk-test"
export AGENT_SCHEDULER_DB_PATH="/tmp/scheduler.sqlite3"
export AGENT_SCHEDULER_TRACE_DIR="/tmp"
export AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="https://api.deepseek.com"
export AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY="sk-test"
export AGENT_SCHEDULER_LLM_PROXY_ENABLED="true"
export AGENT_SCHEDULER_LLM_PROXY_EXPOSE_MODEL="deepseek-v4-flash"
export AGENT_SCHEDULER_LLM_PROXY_UPSTREAM_MODEL="deepseek-v4-flash"

# 1. Setup
echo "=== Setup ==="
bash /claw/setup.sh 2>&1 | tail -5
echo "openclaw version: $(openclaw --version 2>&1)"

# 2. Start sidecar
echo "=== Start sidecar ==="
cd /claw/scheduler
PYTHONPATH=src /opt/conda/bin/python3 -c "import agent_scheduler.config; c=agent_scheduler.config.SchedulerConfig.from_env(); print(f'expose={c.llm_proxy_expose_model} upstream_model={c.llm_proxy_upstream_model}')" 2>&1

PYTHONPATH=src /opt/conda/bin/python3 -m agent_scheduler.main --host 127.0.0.1 --port 8765 &
SIDECAR_PID=$!
echo "sidecar PID=$SIDECAR_PID"

# 3. Wait for sidecar
for i in $(seq 1 10); do
    if curl -sf http://127.0.0.1:8765/health/ready >/dev/null 2>&1; then
        echo "sidecar ready after ${i}s"
        break
    fi
    sleep 1
done

# 4. Test /v1/models
echo "=== /v1/models ==="
curl -s http://127.0.0.1:8765/v1/models 2>&1 | head -5
echo ""

# 5. Onboard
echo "=== Onboard ==="
export VLLM_API_KEY="sk-test"
openclaw onboard --non-interactive \
    --mode local --auth-choice vllm \
    --custom-base-url "http://127.0.0.1:8765/v1" \
    --custom-api-key "sk-test" \
    --custom-model-id "deepseek-v4-flash" 2>&1
echo "onboard exit: $?"

# 6. List models
echo "=== Models ==="
openclaw models list 2>&1

# 7. Try agent
echo "=== Agent ==="
openclaw agent --local --agent main --model "vllm/deepseek-v4-flash" \
    --message "Say hello in one word." 2>&1

kill $SIDECAR_PID 2>/dev/null || true
echo "=== Done ==="
