#!/bin/bash
set -euo pipefail
echo "[claw] running agent (fallback)..."
echo "[claw] TASK_INSTANCE_ID=${TASK_INSTANCE_ID:-unknown}"
exec openclaw agent --local \
    --agent main \
    --model "vllm/deepseek-v4-flash" \
    --message "${PROBLEM_STATEMENT:-Solve the task.}"
