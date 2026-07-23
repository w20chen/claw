#!/bin/bash
# Fallback agent runner -- invoked when no PROBLEM_STATEMENT env var is set.
# Override this script in your task definitions if you need custom logic.
set -euo pipefail

echo "[claw] running agent (fallback mode)..."
echo "[claw] TASK_INSTANCE_ID=${TASK_INSTANCE_ID:-unknown}"

# By default, run OpenClaw in interactive mode so the agent can explore.
openclaw run \
    --model "vllm/deepseek-v4-flash" \
    --max-turns 50 \
    --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \
    
