#!/bin/bash
# Quick test: install node from tarball, install openclaw, check commands
docker run --rm --entrypoint /bin/bash \
  swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 \
  -c '
# Install Node.js from tarball
curl -fsSL "https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt" 2>/dev/null
LATEST=$(curl -fsSL "https://nodejs.org/dist/latest-v24.x/" 2>/dev/null | grep -oP "node-v24\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz" | head -1)
echo "Downloading $LATEST..."
curl -fsSL "https://nodejs.org/dist/latest-v24.x/${LATEST}" -o /tmp/node.tar.xz
tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
node --version
# Install openclaw
npm install -g openclaw@2026.7.1 2>&1 | tail -2
echo ===COMMANDS===
openclaw --help 2>&1
'
