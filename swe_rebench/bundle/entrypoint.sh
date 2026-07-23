#!/bin/bash
# ────────────────────────────────────────────────────────────────
# OpenClaw + Sidecar entrypoint for swe-rebench containers.
# Mounted at /claw/entrypoint.sh, invoked as the container ENTRYPOINT.
# ────────────────────────────────────────────────────────────────
set -euo pipefail

CLAW_ROOT="/claw"
TRACE_DIR="/traces"
SIDECAR_PORT=8765

# ── Phase 1: Environment setup ─────────────────────────────────
echo "[claw] setting up environment..."
bash "$CLAW_ROOT/setup.sh"

# ── Phase 2: Start sidecar ─────────────────────────────────────
echo "[claw] starting scheduler sidecar on :$SIDECAR_PORT ..."

export AGENT_SCHEDULER_DB_PATH="/tmp/scheduler.sqlite3"
export AGENT_SCHEDULER_TRACE_DIR="$TRACE_DIR"
export AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="https://api.deepseek.com"
export AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY=""
export AGENT_SCHEDULER_LLM_PROXY_ENABLED="true"
export AGENT_SCHEDULER_POLICY="observe-only"
export AGENT_SCHEDULER_TOOL_PROFILES="$CLAW_ROOT/tool_profiles.json"

cd "$CLAW_ROOT/scheduler"

# Install scheduler deps (quiet, fail gracefully if already installed)
python3 -m pip install -e . --quiet 2>/dev/null || \
  python3 -m pip install . --quiet 2>/dev/null || true

# Start sidecar in background
PYTHONPATH=src python3 -m agent_scheduler.main \
    --host 127.0.0.1 --port "$SIDECAR_PORT" &
SIDECAR_PID=$!
echo "[claw] sidecar PID=$SIDECAR_PID"

# Wait for sidecar to be ready
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
    echo "[claw] ERROR: sidecar failed to start within 60s"
    kill "$SIDECAR_PID" 2>/dev/null || true
    exit 1
fi

# ── Phase 3: Configure OpenClaw ─────────────────────────────────
echo "[claw] configuring OpenClaw..."

# Onboard via sidecar proxy (captures all LLM traffic)
openclaw onboard --non-interactive \
    --mode local \
    --auth-choice vllm \
    --custom-base-url "http://127.0.0.1:$SIDECAR_PORT/v1" \
    --custom-api-key "" \
    --custom-model-id "deepseek-v4-flash" 2>/dev/null || true

# Install and enable the hardware-scheduler plugin
openclaw plugins install --link "$CLAW_ROOT/plugin" 2>/dev/null || true
openclaw plugins enable hardware-scheduler 2>/dev/null || true

# Patch plugin config (recordRawTrace=true so tool args/results are captured)
if [ -f "$CLAW_ROOT/openclaw-config.json5" ]; then
    openclaw config patch --stdin < "$CLAW_ROOT/openclaw-config.json5" 2>/dev/null || true
fi

# ── Phase 4: Run the agent ──────────────────────────────────────
echo "[claw] running agent (max_turns=50)..."

# PROBLEM_STATEMENT and TASK_INSTANCE_ID are passed as env vars by the runner.
AGENT_EXIT=0

if [ -n "${PROBLEM_STATEMENT:-}" ]; then
    echo "$PROBLEM_STATEMENT" > /tmp/problem_statement.txt
    openclaw run \
        --prompt-file /tmp/problem_statement.txt \
        --model "vllm/deepseek-v4-flash" \
        --max-turns 50 \
        --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \
         || AGENT_EXIT=$?
else
    echo "[claw] WARNING: PROBLEM_STATEMENT not set, running default agent entry"
    bash "$CLAW_ROOT/run_agent.sh" || AGENT_EXIT=$?
fi

echo "[claw] agent exited with code $AGENT_EXIT"

# ── Phase 5: Stop sidecar ───────────────────────────────────────
echo "[claw] stopping sidecar..."
kill "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true

# Flush: small sleep to let any pending writes complete
sleep 2

# Log trace output
if [ -f "$TRACE_DIR/trace.jsonl" ]; then
    echo "[claw] trace written: $TRACE_DIR/trace.jsonl ($(wc -l < "$TRACE_DIR/trace.jsonl") lines)"
elif compgen -G "$TRACE_DIR/*.jsonl" > /dev/null 2>&1; then
    for f in "$TRACE_DIR"/*.jsonl; do
        echo "[claw] trace found: $f ($(wc -l < "$f") lines)"
    done
else
    echo "[claw] WARNING: no trace.jsonl found in $TRACE_DIR"
fi

exit $AGENT_EXIT
