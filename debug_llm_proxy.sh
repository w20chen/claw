#!/bin/bash
# debug_llm_proxy.sh — test the sidecar LLM proxy chain inside a swe-rebench container
set -euo pipefail

BUNDLE="/claw"
TRACE_DIR="/tmp/traces"
SIDECAR_PORT=8765
API_KEY="${1:-sk-test}"
MODEL="${2:-deepseek-v4-flash}"
UPSTREAM="${3:-https://api.deepseek.com}"

export PATH="/usr/local/bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

echo "=== 1. Install deps (skip if already done) ==="
bash "$BUNDLE/setup.sh" 2>&1 | tail -3 || true

echo "=== 2. Start sidecar ==="
export AGENT_SCHEDULER_DB_PATH="/tmp/scheduler.sqlite3"
export AGENT_SCHEDULER_TRACE_DIR="$TRACE_DIR"
export AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="$UPSTREAM"
export AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY="$API_KEY"
export AGENT_SCHEDULER_LLM_PROXY_ENABLED="true"
export AGENT_SCHEDULER_LLM_PROXY_EXPOSE_MODEL="$MODEL"

cd "$BUNDLE/scheduler"
PYTHONPATH=src /opt/conda/bin/python3 -m agent_scheduler.main --host 127.0.0.1 --port "$SIDECAR_PORT" &
SIDECAR_PID=$!
echo "sidecar PID=$SIDECAR_PID"

# Wait for sidecar
for i in $(seq 1 15); do
    if curl -sf "http://127.0.0.1:$SIDECAR_PORT/health/ready" >/dev/null 2>&1; then
        echo "sidecar ready after ${i}s"
        break
    fi
    sleep 1
done

echo ""
echo "=== 3. Direct DeepSeek test ==="
echo "POST https://api.deepseek.com/v1/chat/completions"
curl -s --max-time 30 "$UPSTREAM/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi in one word\"}],\"max_tokens\":10}" \
  | python3 -m json.tool 2>/dev/null || echo "(raw output above)"

echo ""
echo "=== 4. Via sidecar proxy (non-streaming) ==="
echo "POST http://127.0.0.1:$SIDECAR_PORT/v1/chat/completions"
curl -s --max-time 30 "http://127.0.0.1:$SIDECAR_PORT/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi in one word\"}],\"max_tokens\":10}" \
  | python3 -m json.tool 2>/dev/null || echo "(raw output above)"

echo ""
echo "=== 5. Via sidecar proxy (streaming) ==="
echo "POST http://127.0.0.1:$SIDECAR_PORT/v1/chat/completions (stream=true)"
curl -s --max-time 30 "http://127.0.0.1:$SIDECAR_PORT/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi in one word\"}],\"max_tokens\":10,\"stream\":true}" \
  | head -20

echo ""
echo "=== 6. Sidecar /v1/models ==="
curl -s "http://127.0.0.1:$SIDECAR_PORT/v1/models" | python3 -m json.tool 2>/dev/null

echo ""
echo "=== 7. Trace output ==="
ls -la "$TRACE_DIR/" 2>/dev/null || echo "(no trace dir)"
cat "$TRACE_DIR/trace.jsonl" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(no trace yet)"

echo ""
echo "=== Done. Cleaning up ==="
kill "$SIDECAR_PID" 2>/dev/null || true
