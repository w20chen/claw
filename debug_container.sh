#!/bin/bash
# Debug script for swe-rebench container environment
docker run --rm --entrypoint /bin/bash swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 -c '
echo === network ===
curl -sI https://deb.nodesource.com 2>&1 | head -3
curl -sI https://registry.npmjs.org 2>&1 | head -3
echo === python ===
/opt/conda/bin/python3 --version
/opt/conda/bin/python3 -c "import fastapi" 2>&1 || echo NO_FASTAPI
/opt/conda/bin/pip list 2>/dev/null | grep -iE "fastapi|uvicorn|psutil|pydantic|httpx" || echo NO_SCHEDULER_DEPS
echo === testbed ===
ls /testbed/ 2>/dev/null | head -5
which node || echo NO_NODE
echo === mount ===
ls -la /claw/ 2>&1 || echo NO_CLAW_MOUNT
'
