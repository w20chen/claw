#!/bin/bash
set -euo pipefail
CLAW_ROOT="/claw"
TRACE_DIR="/traces"
SIDECAR_PORT=8765

# Detect python: prefer conda python shipped by swe-rebench images.
if [ -x /opt/conda/bin/python3 ]; then
    _CLW_PYTHON="/opt/conda/bin/python3"
    _CLW_PIP="/opt/conda/bin/pip"
elif command -v python3 &>/dev/null; then
    _CLW_PYTHON="$(command -v python3)"
    _CLW_PIP="$(command -v pip3 2>/dev/null || command -v pip 2>/dev/null)"
else
    _CLW_PYTHON="python3"
    _CLW_PIP="pip3"
fi


echo "[claw] === Phase 1: environment setup ==="
bash "$CLAW_ROOT/setup.sh"

echo "[claw] === Phase 2: start sidecar ==="
export AGENT_SCHEDULER_DB_PATH="/tmp/scheduler.sqlite3"
export AGENT_SCHEDULER_TRACE_DIR="$TRACE_DIR"
export AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="https://api.deepseek.com"
export AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY=""
export AGENT_SCHEDULER_LLM_PROXY_ENABLED="true"
# Model spoofing: the sidecar auto-normalises upstream /v1/models by default.
# Setting both vars explicitly provides a synthetic fallback for cases where
# the upstream /models endpoint is unreachable or returns unparseable data.
# Set UPSTREAM_MODEL to a different value to translate model names.
export AGENT_SCHEDULER_LLM_PROXY_EXPOSE_MODEL="deepseek-v4-flash"
export AGENT_SCHEDULER_LLM_PROXY_UPSTREAM_MODEL="deepseek-v4-flash"
export AGENT_SCHEDULER_POLICY="observe-only"
export AGENT_SCHEDULER_TOOL_PROFILES="$CLAW_ROOT/tool_profiles.json"

cd "$CLAW_ROOT/scheduler"

# Install scheduler package (editable, best-effort)
$_CLW_PIP install -e . --quiet 2>/dev/null || $_CLW_PIP install . --quiet 2>/dev/null || true

# Start sidecar
PYTHONPATH=src $_CLW_PYTHON -m agent_scheduler.main \
    --host 127.0.0.1 --port "$SIDECAR_PORT" &
SIDECAR_PID=$!
echo "[claw] sidecar PID=$SIDECAR_PID"

# Wait for ready
READY=0
for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$SIDECAR_PORT/health/ready" >/dev/null 2>&1; then
        READY=1
        echo "[claw] sidecar ready after ${i}s"
        break
    fi
    sleep 1
done
if [ "$READY" -eq 0 ]; then
    echo "[claw] FATAL: sidecar not ready after 60s"
    kill "$SIDECAR_PID" 2>/dev/null || true
    exit 1
fi

echo "[claw] === Phase 3: configure OpenClaw ==="
# vLLM provider requires VLLM_API_KEY (any value works).
export VLLM_API_KEY="${LLM_API_KEY:-sk-test}"

# Save ALL Phase 3 diagnostics to a log file for debugging.
# Each command handles its own errors so 'set -e' does not abort.
{
echo "=== openclaw onboard ==="
# --skip-health: we use openclaw agent --local, no gateway needed.
# --accept-risk: required for non-interactive mode.
openclaw onboard --non-interactive --accept-risk --skip-health \
    --mode local --auth-choice vllm \
    --custom-base-url "http://127.0.0.1:$SIDECAR_PORT/v1" \
    --custom-api-key "" \
    --custom-model-id "deepseek-v4-flash" || echo "onboard FAILED (exit=$?)"
echo ""

echo "=== openclaw plugins install ==="
# Copy plugin to writable location to avoid "suspicious ownership" error
# from the read-only /claw bind mount (host uid ≠ container root uid).
cp -r "$CLAW_ROOT/plugin" /tmp/plugin
openclaw plugins install --link /tmp/plugin || echo "plugin install FAILED (exit=$?)"
echo "=== openclaw plugins enable ==="
openclaw plugins enable hardware-scheduler || echo "plugin enable FAILED (exit=$?)"
echo ""

if [ -f "$CLAW_ROOT/openclaw-config.json5" ]; then
    echo "=== openclaw config patch ==="
    openclaw config patch --stdin < "$CLAW_ROOT/openclaw-config.json5" || echo "config patch FAILED (exit=$?)"
    echo ""
fi

echo "=== openclaw models list ==="
openclaw models list || echo "models list FAILED (exit=$?)"
echo ""

echo "=== sidecar /v1/models ==="
curl -sS "http://127.0.0.1:$SIDECAR_PORT/v1/models" || echo "/v1/models FAILED (exit=$?)"
echo ""

echo "=== sidecar /health/ready ==="
curl -sS "http://127.0.0.1:$SIDECAR_PORT/health/ready" || echo "/health/ready FAILED (exit=$?)"
echo ""

echo "=== Phase 3 done ==="
} > "$TRACE_DIR/phase3.log" 2>&1 || true

echo "[claw] === Phase 4: run agent ==="
AGENT_EXIT=0
openclaw agent --help 2>&1 > "$TRACE_DIR/agent-help.txt" || true

if [ -n "${PROBLEM_STATEMENT:-}" ]; then
    echo "$PROBLEM_STATEMENT" > /tmp/problem_statement.txt
    echo "[claw] running: openclaw agent --local --agent main --model vllm/deepseek-v4-flash ..."
    openclaw agent --local \
        --agent main \
        --model "vllm/deepseek-v4-flash" \
        --message-file /tmp/problem_statement.txt \
        2>"$TRACE_DIR/agent-stderr.txt" || AGENT_EXIT=$?
else
    echo "[claw] WARNING: PROBLEM_STATEMENT not set"
    bash "$CLAW_ROOT/run_agent.sh" || AGENT_EXIT=$?
fi
echo "[claw] agent exited code=$AGENT_EXIT"

echo "[claw] === Phase 5: stop sidecar ==="
kill "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true
sleep 2

# Log traces
if [ -f "$TRACE_DIR/trace.jsonl" ]; then
    echo "[claw] trace: $TRACE_DIR/trace.jsonl ($(wc -l < "$TRACE_DIR/trace.jsonl") lines)"
elif compgen -G "$TRACE_DIR/*.jsonl" >/dev/null 2>&1; then
    for f in "$TRACE_DIR"/*.jsonl; do
        echo "[claw] trace: $f ($(wc -l < "$f") lines)"
    done
else
    echo "[claw] WARNING: no trace.jsonl found"
fi
exit $AGENT_EXIT
