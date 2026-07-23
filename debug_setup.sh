#!/bin/bash
docker run --rm --entrypoint /bin/bash swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 -c '
echo === PATH ===
echo $PATH
echo === python ===
which python3 || echo NO_PYTHON3_IN_PATH
echo === conda python ===
/opt/conda/bin/python3 -c "print(42)"
echo === pip ===
which pip3 2>/dev/null || which pip 2>/dev/null || echo NO_PIP
echo === install scheduler deps ===
/opt/conda/bin/pip install fastapi uvicorn pydantic psutil httpx prometheus-client --quiet 2>&1 | tail -5
echo === install nodejs ===
apt-get update -qq 2>&1 | tail -1
apt-get install -y -qq nodejs npm 2>&1 | tail -3
which node && node --version || echo NODE_FAILED
'
