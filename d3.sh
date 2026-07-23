#!/bin/bash
docker run --rm --entrypoint /bin/bash swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 -c '
echo "=== pip config ==="
/opt/conda/bin/pip config list 2>&1 || echo no-config
echo "=== pip install fastapi (30s timeout) ==="
timeout 30 /opt/conda/bin/pip install fastapi --quiet 2>&1 && echo OK || echo PIP_FAILED_OR_TIMEOUT
echo "=== check ==="
/opt/conda/bin/python3 -c "import fastapi; print(fastapi.__version__)" 2>&1 || echo FASTAPI_NOT_FOUND
'
