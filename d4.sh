#!/bin/bash
# Test: build a proper Node.js + sidecar deps inside container
docker run --rm --entrypoint /bin/bash swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 -c '
echo "=== Fix nodejs (nodesource 22.x) ==="
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg 2>&1 | tail -1
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>&1 | tail -3
apt-get install -y -qq nodejs 2>&1 | tail -3
node --version && echo NODE_OK

echo "=== pip deps (conda) ==="
/opt/conda/bin/pip install fastapi uvicorn pydantic psutil httpx prometheus-client -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet 2>&1 | tail -2
/opt/conda/bin/python3 -c "import fastapi; print(fastapi.__version__)" && echo FASTAPI_OK

echo "=== openclaw CLI ==="
npm install -g openclaw 2>&1 | tail -2
which openclaw && openclaw --version && echo OPENCLAW_OK
'
