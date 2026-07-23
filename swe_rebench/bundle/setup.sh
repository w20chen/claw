#!/bin/bash
# ────────────────────────────────────────────────────────────────
# Environment setup inside swe-rebench containers.
# Installs Node.js, npm, OpenClaw CLI, and Python deps if missing.
# Idempotent ── safe to run multiple times.
# ────────────────────────────────────────────────────────────────
set -euo pipefail

SETUP_DONE="/tmp/.claw_setup_done"
if [ -f "$SETUP_DONE" ]; then
    echo "[claw] setup already complete, skipping."
    return 0 2>/dev/null || exit 0
fi

echo "[claw] installing system dependencies..."

# Detect OS / package manager
if command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
elif command -v yum &>/dev/null; then
    PKG_MGR="yum"
elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
elif command -v apk &>/dev/null; then
    PKG_MGR="apk"
else
    PKG_MGR="none"
fi

# ── Python 3 ──
if ! command -v python3 &>/dev/null; then
    echo "[claw] installing python3..."
    case "$PKG_MGR" in
        apt) apt-get update -qq && apt-get install -y -qq python3 python3-pip ;;
        yum) yum install -y -q python3 python3-pip ;;
        dnf) dnf install -y -q python3 python3-pip ;;
        apk) apk add --no-cache python3 py3-pip ;;
        *)  echo "[claw] FATAL: cannot install python3 (no known package manager)" ; exit 1 ;;
    esac
fi

# ── curl (needed for health checks) ──
if ! command -v curl &>/dev/null; then
    echo "[claw] installing curl..."
    case "$PKG_MGR" in
        apt) apt-get install -y -qq curl ;;
        yum) yum install -y -q curl ;;
        dnf) dnf install -y -q curl ;;
        apk) apk add --no-cache curl ;;
    esac
fi

# ── Node.js + npm ──
if ! command -v node &>/dev/null; then
    echo "[claw] installing Node.js..."
    case "$PKG_MGR" in
        apt)
            apt-get update -qq
            apt-get install -y -qq ca-certificates curl gnupg
            curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
            apt-get install -y -qq nodejs
            ;;
        yum|dnf)
            curl -fsSL https://rpm.nodesource.com/setup_22.x | bash -
            $PKG_MGR install -y -q nodejs
            ;;
        apk)
            apk add --no-cache nodejs npm
            ;;
        *)
            echo "[claw] FATAL: cannot install Node.js (no known package manager)"
            exit 1
            ;;
    esac
fi

# ── OpenClaw CLI ──
if ! command -v openclaw &>/dev/null; then
    echo "[claw] installing OpenClaw CLI..."
    npm install -g openclaw@2026.7.1 2>/dev/null ||       npm install -g openclaw 2>/dev/null || {
        echo "[claw] WARNING: openclaw install failed, continuing anyway"
    }
fi

# ── Python dependencies for sidecar ──
echo "[claw] installing Python deps for sidecar..."
cd /claw/scheduler
python3 -m pip install --quiet fastapi uvicorn pydantic psutil httpx prometheus-client 2>/dev/null || true

# ── Mark done ──
touch "$SETUP_DONE"
echo "[claw] environment setup complete."
