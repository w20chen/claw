#!/bin/bash
set -euo pipefail
echo "[claw] running agent (fallback)..."
echo "[claw] TASK_INSTANCE_ID=${TASK_INSTANCE_ID:-unknown}"
openclaw run \
    --model "vllm/deepseek-v4-flash" \
    --max-turns 50 \
    --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \
    
