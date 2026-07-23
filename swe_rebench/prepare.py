"""
Runtime bundle preparation.

Assembles a self-contained directory that is volume-mounted into every
swe-rebench container at ``/claw``.  The bundle includes:

- The OpenClaw plugin source (``plugin/``)
- The scheduler sidecar source (``scheduler/``)
- Generated entrypoint and setup scripts
- Generated OpenClaw plugin config (pointing at localhost:8765)
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from swe_rebench.config import RunnerConfig


# ── plugin config that gets written into the bundle ────────────────
_PLUGIN_CONFIG: dict[str, Any] = {
    "endpoint": "http://127.0.0.1:8765",
    "mode": "observe",
    "decisionTimeoutMs": 800,
    "reportTimeoutMs": 800,
    "failOpen": True,
    "sendRawParams": False,
    "recordRawTrace": True,
    "authTokenEnv": "OPENCLAW_SCHEDULER_TOKEN",
    "logLevel": "info",
    "executionBackend": "marker",
    "launcherPath": "/opt/claw/bin/claw-launch",
    "instrumentHosts": ["gateway"],
    "instrumentTools": ["exec"],
    "enableCgroup": False,
    "enableAffinity": False,
    "enableNuma": False,
    "profilingMode": "off",
    "securityBoundaryAccepted": False,
}


def build_bundle(config: RunnerConfig) -> Path:
    """Assemble the runtime bundle and return its path."""
    repo = config.repo_root
    bundle_dir = repo / config.bundle.output_dir

    # Clean and recreate
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    _copy_plugin(repo, bundle_dir, config)
    _copy_scheduler(repo, bundle_dir, config)
    _copy_tool_profiles(repo, bundle_dir, config)
    _write_entrypoint(bundle_dir, config)
    _write_setup_script(bundle_dir)
    _write_plugin_config(bundle_dir)
    _write_run_agent(bundle_dir, config)

    _log(f"Bundle assembled at {bundle_dir}")
    _log(f"  plugin/     ← {repo / config.bundle.plugin_source}")
    _log(f"  scheduler/  ← {repo / config.bundle.scheduler_source}")
    return bundle_dir


def _copy_plugin(repo: Path, bundle_dir: Path, config: RunnerConfig) -> None:
    src = repo / config.bundle.plugin_source
    dst = bundle_dir / "plugin"
    _copytree_selective(src, dst, skip={"node_modules", ".git", "__pycache__", "dist"})
    # Also run npm install + build if we can, but for the container we
    # only need the source because the container runs its own npm install.
    _log(f"  Copied plugin source ({_count_files(dst)} files)")


def _copy_scheduler(repo: Path, bundle_dir: Path, config: RunnerConfig) -> None:
    src = repo / config.bundle.scheduler_source
    dst = bundle_dir / "scheduler"
    _copytree_selective(src, dst, skip={"__pycache__", ".pytest_cache", "*.egg-info", "traces", "scheduler.sqlite3*", "dist", "*.whl", "*.tar.gz"})
    _log(f"  Copied scheduler source ({_count_files(dst)} files)")


def _copy_tool_profiles(repo: Path, bundle_dir: Path, config: RunnerConfig) -> None:
    src = repo / config.bundle.tool_profiles
    if not src.exists():
        _log(f"  [warn] tool profiles not found: {src}")
        return
    dst = bundle_dir / "tool_profiles.json"
    shutil.copy2(src, dst)
    _log(f"  Copied tool profiles")


def _write_entrypoint(bundle_dir: Path, config: RunnerConfig) -> None:
    """Write the container entrypoint script.

    Uses placeholders (``__TOKEN__``) instead of f-strings to avoid
    conflicts between Python formatting and bash syntax (``$var``,
    ``${var}``, ``#`` comments, etc.).
    """
    llm_key = config.llm.api_key
    upstream = config.llm.upstream_base_url
    model_full = config.llm.openclaw_model_ref       # e.g. "vllm/deepseek-v4-flash"
    model_short = config.llm.model                    # e.g. "deepseek-v4-flash"
    max_turns = config.agent.max_turns
    extra = " ".join(config.agent.extra_args)

    template = """#!/bin/bash
# ────────────────────────────────────────────────────────────────
# OpenClaw + Sidecar entrypoint for swe-rebench containers.
# Mounted at /claw/entrypoint.sh, invoked as the container ENTRYPOINT.
# ────────────────────────────────────────────────────────────────
set -euo pipefail

CLAW_ROOT="/claw"
TRACE_DIR="/traces"
SIDECAR_PORT=8765

# ── Phase 1: Environment setup ─────────────────────────────────
echo "[claw] setting up environment..."
bash "$CLAW_ROOT/setup.sh"

# ── Phase 2: Start sidecar ─────────────────────────────────────
echo "[claw] starting scheduler sidecar on :$SIDECAR_PORT ..."

export AGENT_SCHEDULER_DB_PATH="/tmp/scheduler.sqlite3"
export AGENT_SCHEDULER_TRACE_DIR="$TRACE_DIR"
export AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="__UPSTREAM__"
export AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY="__LLM_KEY__"
export AGENT_SCHEDULER_LLM_PROXY_ENABLED="true"
export AGENT_SCHEDULER_POLICY="observe-only"
export AGENT_SCHEDULER_TOOL_PROFILES="$CLAW_ROOT/tool_profiles.json"

cd "$CLAW_ROOT/scheduler"

# Install scheduler deps (quiet, fail gracefully if already installed)
python3 -m pip install -e . --quiet 2>/dev/null || \\
  python3 -m pip install . --quiet 2>/dev/null || true

# Start sidecar in background
PYTHONPATH=src python3 -m agent_scheduler.main \\
    --host 127.0.0.1 --port "$SIDECAR_PORT" &
SIDECAR_PID=$!
echo "[claw] sidecar PID=$SIDECAR_PID"

# Wait for sidecar to be ready
READY=0
for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$SIDECAR_PORT/health/ready" >/dev/null 2>&1; then
        READY=1
        echo "[claw] sidecar ready after ${i}s"
        break
    fi
    sleep 1
done

if [ "$READY" -eq 0 ]; then
    echo "[claw] ERROR: sidecar failed to start within 60s"
    kill "$SIDECAR_PID" 2>/dev/null || true
    exit 1
fi

# ── Phase 3: Configure OpenClaw ─────────────────────────────────
echo "[claw] configuring OpenClaw..."

# Onboard via sidecar proxy (captures all LLM traffic)
openclaw onboard --non-interactive \\
    --mode local \\
    --auth-choice vllm \\
    --custom-base-url "http://127.0.0.1:$SIDECAR_PORT/v1" \\
    --custom-api-key "__LLM_KEY__" \\
    --custom-model-id "__MODEL_SHORT__" 2>/dev/null || true

# Install and enable the hardware-scheduler plugin
openclaw plugins install --link "$CLAW_ROOT/plugin" 2>/dev/null || true
openclaw plugins enable hardware-scheduler 2>/dev/null || true

# Patch plugin config (recordRawTrace=true so tool args/results are captured)
if [ -f "$CLAW_ROOT/openclaw-config.json5" ]; then
    openclaw config patch --stdin < "$CLAW_ROOT/openclaw-config.json5" 2>/dev/null || true
fi

# ── Phase 4: Run the agent ──────────────────────────────────────
echo "[claw] running agent (max_turns=__MAX_TURNS__)..."

# PROBLEM_STATEMENT and TASK_INSTANCE_ID are passed as env vars by the runner.
AGENT_EXIT=0

if [ -n "${PROBLEM_STATEMENT:-}" ]; then
    echo "$PROBLEM_STATEMENT" > /tmp/problem_statement.txt
    openclaw run \\
        --prompt-file /tmp/problem_statement.txt \\
        --model "__MODEL_FULL__" \\
        --max-turns __MAX_TURNS__ \\
        --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \\
        __EXTRA__ || AGENT_EXIT=$?
else
    echo "[claw] WARNING: PROBLEM_STATEMENT not set, running default agent entry"
    bash "$CLAW_ROOT/run_agent.sh" || AGENT_EXIT=$?
fi

echo "[claw] agent exited with code $AGENT_EXIT"

# ── Phase 5: Stop sidecar ───────────────────────────────────────
echo "[claw] stopping sidecar..."
kill "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true

# Flush: small sleep to let any pending writes complete
sleep 2

# Log trace output
if [ -f "$TRACE_DIR/trace.jsonl" ]; then
    echo "[claw] trace written: $TRACE_DIR/trace.jsonl ($(wc -l < "$TRACE_DIR/trace.jsonl") lines)"
elif compgen -G "$TRACE_DIR/*.jsonl" > /dev/null 2>&1; then
    for f in "$TRACE_DIR"/*.jsonl; do
        echo "[claw] trace found: $f ($(wc -l < "$f") lines)"
    done
else
    echo "[claw] WARNING: no trace.jsonl found in $TRACE_DIR"
fi

exit $AGENT_EXIT
"""

    # Substitute placeholders
    script = (template
              .replace("__UPSTREAM__", upstream)
              .replace("__LLM_KEY__", llm_key)
              .replace("__MODEL_FULL__", model_full)
              .replace("__MODEL_SHORT__", model_short)
              .replace("__MAX_TURNS__", str(max_turns))
              .replace("__EXTRA__", extra))

    dest = bundle_dir / "entrypoint.sh"
    dest.write_text(script, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    _log(f"  Wrote entrypoint.sh ({len(script)} bytes)")


def _write_setup_script(bundle_dir: Path) -> None:
    """Write the container environment setup script."""
    script = '''#!/bin/bash
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
    npm install -g openclaw@2026.7.1 2>/dev/null || \
      npm install -g openclaw 2>/dev/null || {
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
'''
    dest = bundle_dir / "setup.sh"
    dest.write_text(script, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    _log(f"  Wrote setup.sh ({len(script)} bytes)")


def _write_run_agent(bundle_dir: Path, config: RunnerConfig) -> None:
    """Write the fallback agent runner used when PROBLEM_STATEMENT is absent."""
    model_full = config.llm.openclaw_model_ref
    max_turns = config.agent.max_turns
    extra = " ".join(config.agent.extra_args)

    template = """#!/bin/bash
# Fallback agent runner -- invoked when no PROBLEM_STATEMENT env var is set.
# Override this script in your task definitions if you need custom logic.
set -euo pipefail

echo "[claw] running agent (fallback mode)..."
echo "[claw] TASK_INSTANCE_ID=${TASK_INSTANCE_ID:-unknown}"

# By default, run OpenClaw in interactive mode so the agent can explore.
openclaw run \\
    --model "__MODEL_FULL__" \\
    --max-turns __MAX_TURNS__ \\
    --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \\
    __EXTRA__
"""
    script = (template
              .replace("__MODEL_FULL__", model_full)
              .replace("__MAX_TURNS__", str(max_turns))
              .replace("__EXTRA__", extra))

    dest = bundle_dir / "run_agent.sh"
    dest.write_text(script, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    _log(f"  Wrote run_agent.sh ({len(script)} bytes)")


def _write_plugin_config(bundle_dir: Path) -> None:
    """Write the OpenClaw plugin config referencing the in-container sidecar."""
    config_str = json.dumps({"plugins": {"entries": {"hardware-scheduler": {"enabled": True, "config": _PLUGIN_CONFIG}}}}, indent=2)
    dest = bundle_dir / "openclaw-config.json5"
    dest.write_text(config_str, encoding="utf-8")
    _log(f"  Wrote openclaw-config.json5")


# ── helpers ──────────────────────────────────────────────────────

def _copytree_selective(src: Path, dst: Path, skip: set[str]) -> None:
    """Copy src to dst, skipping any file/dir whose name is in *skip*."""
    if not src.exists():
        _log(f"  [warn] source not found: {src}")
        return

    def _ignore(directory: str, names: list[str]) -> set[str]:
        import fnmatch
        ignored: set[str] = set()
        for name in names:
            if name in skip:
                ignored.add(name)
            else:
                for pattern in skip:
                    if "*" in pattern and fnmatch.fnmatch(name, pattern):
                        ignored.add(name)
                        break
        return ignored

    shutil.copytree(str(src), str(dst), ignore=_ignore, dirs_exist_ok=True)


def _count_files(directory: Path) -> int:
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ── CLI entry point ──────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build the swe-rebench runtime bundle.")
    parser.add_argument("--config", default="swe_rebench/config.example.yaml", help="Path to config YAML.")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: auto-detect).")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else _detect_repo_root()
    cfg = RunnerConfig.from_yaml(args.config, repo_root=repo_root)
    bundle_path = build_bundle(cfg)
    print(f"Bundle ready: {bundle_path}")


def _detect_repo_root() -> Path:
    p = Path(__file__).resolve()
    for _ in range(6):
        if (p / "AGENTS.md").exists():
            return p
        p = p.parent
    return Path.cwd()


if __name__ == "__main__":
    main()
