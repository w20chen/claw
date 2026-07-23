#!/bin/bash
# Install Node.js + openclaw in a swe-rebench container and list all commands.
docker run --rm --entrypoint /bin/bash \
  swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 \
  -c '
# Install Node.js from latest v24 tarball
LATEST=$(curl -fsSL https://nodejs.org/dist/latest-v24.x/ 2>/dev/null | grep -oP "node-v24\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz" | head -1)
echo "Node tarball: $LATEST"
curl -fsSL "https://nodejs.org/dist/latest-v24.x/${LATEST}" -o /tmp/node.tar.xz
tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
node --version

# Install openclaw
npm install -g openclaw@2026.7.1 --quiet 2>/dev/null
echo "openclaw installed"

# List ALL subcommands
echo "=== OPENCLAW HELP ==="
openclaw --help 2>&1

echo "=== OPENCLAW VERSION ==="
openclaw --version 2>&1
'
