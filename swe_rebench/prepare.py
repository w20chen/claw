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
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from swe_rebench.config import RunnerConfig


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

# ── Shared bash snippet: detect correct python/pip for swe-rebench images ──
# swe-rebench images ship conda python at /opt/conda/bin/python3.
# We prefer it over any system python for package consistency.
_BASH_PYTHON_DETECT = '''
# Detect python: prefer conda python shipped by swe-rebench images.
if [ -x /opt/conda/bin/python3 ]; then
    _CLW_PYTHON="/opt/conda/bin/python3"
    _CLW_PIP="/opt/conda/bin/pip"
elif command -v python3 &>/dev/null; then
    _CLW_PYTHON="$(command -v python3)"
    _CLW_PIP="$(command -v pip3 2>/dev/null || command -v pip 2>/dev/null)"
else
    _CLW_PYTHON="python3"
    _CLW_PIP="pip3"
fi
'''


def build_bundle(config: RunnerConfig) -> Path:
    repo = config.repo_root
    bundle_dir = repo / config.bundle.output_dir
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
    _log(f"  plugin/     <- {repo / config.bundle.plugin_source}")
    _log(f"  scheduler/  <- {repo / config.bundle.scheduler_source}")
    return bundle_dir


def _copy_plugin(repo: Path, bundle_dir: Path, config: RunnerConfig) -> None:
    src = repo / config.bundle.plugin_source
    dst = bundle_dir / "plugin"
    _copytree_selective(src, dst, skip={"node_modules", ".git", "__pycache__", "dist"})
    _log(f"  Copied plugin source ({_count_files(dst)} files)")


def _copy_scheduler(repo: Path, bundle_dir: Path, config: RunnerConfig) -> None:
    src = repo / config.bundle.scheduler_source
    dst = bundle_dir / "scheduler"
    _copytree_selective(src, dst, skip={
        "__pycache__", ".pytest_cache", "*.egg-info", "traces",
        "scheduler.sqlite3*", "dist", "*.whl", "*.tar.gz",
    })
    _log(f"  Copied scheduler source ({_count_files(dst)} files)")


def _copy_tool_profiles(repo: Path, bundle_dir: Path, config: RunnerConfig) -> None:
    src = repo / config.bundle.tool_profiles
    if not src.exists():
        _log(f"  [warn] tool profiles not found: {src}")
        return
    shutil.copy2(src, bundle_dir / "tool_profiles.json")
    _log("  Copied tool profiles")


# ══════════════════════════════════════════════════════════════════
#  entrypoint.sh
# ══════════════════════════════════════════════════════════════════

_ENTRYPOINT_TEMPLATE = r"""#!/bin/bash
set -euo pipefail
CLAW_ROOT="/claw"
TRACE_DIR="/traces"
SIDECAR_PORT=8765
""" + _BASH_PYTHON_DETECT + r"""

echo "[claw] === Phase 1: environment setup ==="
bash "$CLAW_ROOT/setup.sh"

echo "[claw] === Phase 2: start sidecar ==="
export AGENT_SCHEDULER_DB_PATH="/tmp/scheduler.sqlite3"
export AGENT_SCHEDULER_TRACE_DIR="$TRACE_DIR"
export AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL="__UPSTREAM__"
export AGENT_SCHEDULER_LLM_UPSTREAM_API_KEY="__LLM_KEY__"
export AGENT_SCHEDULER_LLM_PROXY_ENABLED="true"
export AGENT_SCHEDULER_POLICY="observe-only"
export AGENT_SCHEDULER_TOOL_PROFILES="$CLAW_ROOT/tool_profiles.json"

cd "$CLAW_ROOT/scheduler"

# Install scheduler package (editable, best-effort)
$_CLW_PIP install -e . --quiet 2>/dev/null || $_CLW_PIP install . --quiet 2>/dev/null || true

# Start sidecar
PYTHONPATH=src $_CLW_PYTHON -m agent_scheduler.main \
    --host 127.0.0.1 --port "$SIDECAR_PORT" &
SIDECAR_PID=$!
echo "[claw] sidecar PID=$SIDECAR_PID"

# Wait for ready
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
    echo "[claw] FATAL: sidecar not ready after 60s"
    kill "$SIDECAR_PID" 2>/dev/null || true
    exit 1
fi

echo "[claw] === Phase 3: configure OpenClaw ==="
openclaw onboard --non-interactive \
    --mode local --auth-choice vllm \
    --custom-base-url "http://127.0.0.1:$SIDECAR_PORT/v1" \
    --custom-api-key "__LLM_KEY__" \
    --custom-model-id "__MODEL_SHORT__" 2>/dev/null || true

openclaw plugins install --link "$CLAW_ROOT/plugin" 2>/dev/null || true
openclaw plugins enable hardware-scheduler 2>/dev/null || true
if [ -f "$CLAW_ROOT/openclaw-config.json5" ]; then
    openclaw config patch --stdin < "$CLAW_ROOT/openclaw-config.json5" 2>/dev/null || true
fi

echo "[claw] === Phase 4: run agent (max_turns=__MAX_TURNS__) ==="
AGENT_EXIT=0
if [ -n "${PROBLEM_STATEMENT:-}" ]; then
    echo "$PROBLEM_STATEMENT" > /tmp/problem_statement.txt
    openclaw run \
        --prompt-file /tmp/problem_statement.txt \
        --model "__MODEL_FULL__" \
        --max-turns __MAX_TURNS__ \
        --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \
        __EXTRA__ || AGENT_EXIT=$?
else
    echo "[claw] WARNING: PROBLEM_STATEMENT not set"
    bash "$CLAW_ROOT/run_agent.sh" || AGENT_EXIT=$?
fi
echo "[claw] agent exited code=$AGENT_EXIT"

echo "[claw] === Phase 5: stop sidecar ==="
kill "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true
sleep 2

# Log traces
if [ -f "$TRACE_DIR/trace.jsonl" ]; then
    echo "[claw] trace: $TRACE_DIR/trace.jsonl ($(wc -l < "$TRACE_DIR/trace.jsonl") lines)"
elif compgen -G "$TRACE_DIR/*.jsonl" >/dev/null 2>&1; then
    for f in "$TRACE_DIR"/*.jsonl; do
        echo "[claw] trace: $f ($(wc -l < "$f") lines)"
    done
else
    echo "[claw] WARNING: no trace.jsonl found"
fi
exit $AGENT_EXIT
"""


def _write_entrypoint(bundle_dir: Path, config: RunnerConfig) -> None:
    model_full = config.llm.openclaw_model_ref
    model_short = config.llm.model
    script = (_ENTRYPOINT_TEMPLATE
              .replace("__UPSTREAM__", config.llm.upstream_base_url)
              .replace("__LLM_KEY__", config.llm.api_key)
              .replace("__MODEL_FULL__", model_full)
              .replace("__MODEL_SHORT__", model_short)
              .replace("__MAX_TURNS__", str(config.agent.max_turns))
              .replace("__EXTRA__", " ".join(config.agent.extra_args)))
    dest = bundle_dir / "entrypoint.sh"
    dest.write_text(script, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    _log(f"  Wrote entrypoint.sh ({len(script)} bytes)")


# ══════════════════════════════════════════════════════════════════
#  setup.sh
# ══════════════════════════════════════════════════════════════════

_SETUP_TEMPLATE = r"""#!/bin/bash
# ────────────────────────────────────────────────────────────────
# Environment setup inside swe-rebench containers.
# Installs Node.js, npm, OpenClaw CLI, and Python deps.
# Idempotent -- safe to run multiple times.
# ────────────────────────────────────────────────────────────────
set -euo pipefail

SETUP_DONE="/tmp/.claw_setup_done"
if [ -f "$SETUP_DONE" ]; then
    echo "[claw] setup already complete, skipping."
    return 0 2>/dev/null || exit 0
fi
""" + _BASH_PYTHON_DETECT + r"""

echo "[claw] installing system dependencies..."

# ── Detect package manager ──────────────────────────────────────
if command -v apt-get &>/dev/null; then PKG_MGR="apt"
elif command -v yum &>/dev/null; then PKG_MGR="yum"
elif command -v dnf &>/dev/null; then PKG_MGR="dnf"
elif command -v apk &>/dev/null; then PKG_MGR="apk"
else PKG_MGR="none"
fi

case "$PKG_MGR" in
    apt) apt-get update -qq ;;
    apk) apk update ;;
esac

# ── curl (needed for health checks + nodesource) ────────────────
if ! command -v curl &>/dev/null; then
    echo "[claw] installing curl..."
    case "$PKG_MGR" in
        apt) apt-get install -y -qq curl ;;
        yum) yum install -y -q curl ;;
        dnf) dnf install -y -q curl ;;
        apk) apk add --no-cache curl ;;
    esac
fi

# ── Python 3 (system fallback -- usually conda is already present) ──
if ! $_CLW_PYTHON --version &>/dev/null 2>&1; then
    echo "[claw] installing python3..."
    case "$PKG_MGR" in
        apt) apt-get install -y -qq python3 python3-pip ;;
        yum) yum install -y -q python3 python3-pip ;;
        dnf) dnf install -y -q python3 python3-pip ;;
        apk) apk add --no-cache python3 py3-pip ;;
        *)  echo "[claw] FATAL: cannot install python3" ; exit 1 ;;
    esac
    _CLW_PYTHON="$(command -v python3)"
    _CLW_PIP="$(command -v pip3 2>/dev/null || command -v pip 2>/dev/null)"
fi
echo "[claw] python=$_CLW_PYTHON"

# ── Node.js 22 (nodesource) ─────────────────────────────────────
NODE_OK=0
if command -v node &>/dev/null && node --version &>/dev/null 2>&1; then
    NODE_OK=1
fi
if [ "$NODE_OK" -eq 0 ]; then
    echo "[claw] installing Node.js 22.x..."
    case "$PKG_MGR" in
        apt)
            apt-get install -y -qq ca-certificates gnupg
            curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
            apt-get install -y -qq nodejs
            # Node 22 on Debian 12 may need libicu72 (not always auto-installed)
            apt-get install -y -qq libicu72 2>/dev/null || true
            ;;
        yum|dnf)
            curl -fsSL https://rpm.nodesource.com/setup_22.x | bash -
            $PKG_MGR install -y -q nodejs
            ;;
        apk)
            apk add --no-cache nodejs npm icu
            ;;
        *)  echo "[claw] FATAL: cannot install Node.js" ; exit 1 ;;
    esac
fi

# Verify node actually works (not just installed with broken libs)
if node --version &>/dev/null 2>&1; then
    echo "[claw] node $(node --version) OK"
else
    echo "[claw] FATAL: node installed but does not run (missing libicu?)"
    ldd "$(command -v node)" 2>&1 | grep "not found" || true
    exit 1
fi

# ── OpenClaw CLI ─────────────────────────────────────────────────
if ! command -v openclaw &>/dev/null; then
    echo "[claw] installing openclaw CLI..."
    npm install -g openclaw@2026.7.1 2>/dev/null || npm install -g openclaw 2>/dev/null || {
        echo "[claw] FATAL: openclaw install failed"
        exit 1
    }
fi
echo "[claw] openclaw $(openclaw --version 2>&1 | head -1)"

# ── Sidecar Python deps ─────────────────────────────────────────
echo "[claw] installing sidecar Python deps..."
$_CLW_PIP install --quiet \
    fastapi uvicorn pydantic psutil httpx prometheus-client \
    2>&1 | tail -1
$_CLW_PYTHON -c "import fastapi, uvicorn, pydantic, psutil; print('[claw] sidecar deps OK')"

# ── Done ────────────────────────────────────────────────────────
touch "$SETUP_DONE"
echo "[claw] setup complete."
"""


def _write_setup_script(bundle_dir: Path) -> None:
    dest = bundle_dir / "setup.sh"
    dest.write_text(_SETUP_TEMPLATE, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    _log(f"  Wrote setup.sh ({len(_SETUP_TEMPLATE)} bytes)")


# ══════════════════════════════════════════════════════════════════
#  run_agent.sh (fallback)
# ══════════════════════════════════════════════════════════════════

_RUN_AGENT_TEMPLATE = r"""#!/bin/bash
set -euo pipefail
echo "[claw] running agent (fallback)..."
echo "[claw] TASK_INSTANCE_ID=${TASK_INSTANCE_ID:-unknown}"
openclaw run \
    --model "__MODEL_FULL__" \
    --max-turns __MAX_TURNS__ \
    --allowed-tools "exec,read,write,edit,grep,glob,bash,ls" \
    __EXTRA__
"""


def _write_run_agent(bundle_dir: Path, config: RunnerConfig) -> None:
    model_full = config.llm.openclaw_model_ref
    script = (_RUN_AGENT_TEMPLATE
              .replace("__MODEL_FULL__", model_full)
              .replace("__MAX_TURNS__", str(config.agent.max_turns))
              .replace("__EXTRA__", " ".join(config.agent.extra_args)))
    dest = bundle_dir / "run_agent.sh"
    dest.write_text(script, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    _log(f"  Wrote run_agent.sh ({len(script)} bytes)")


# ── helpers ──────────────────────────────────────────────────────

def _write_plugin_config(bundle_dir: Path) -> None:
    cfg = json.dumps({
        "plugins": {"entries": {"hardware-scheduler": {"enabled": True, "config": _PLUGIN_CONFIG}}}
    }, indent=2)
    dest = bundle_dir / "openclaw-config.json5"
    dest.write_text(cfg, encoding="utf-8")
    _log("  Wrote openclaw-config.json5")


def _copytree_selective(src: Path, dst: Path, skip: set[str]) -> None:
    if not src.exists():
        _log(f"  [warn] source not found: {src}")
        return
    import fnmatch
    def _ignore(_dir: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name in skip:
                ignored.add(name)
                continue
            for pat in skip:
                if "*" in pat and fnmatch.fnmatch(name, pat):
                    ignored.add(name)
                    break
        return ignored
    shutil.copytree(str(src), str(dst), ignore=_ignore, dirs_exist_ok=True)


def _count_files(directory: Path) -> int:
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ── CLI ──────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build the swe-rebench runtime bundle.")
    parser.add_argument("--config", default="swe_rebench/config.example.yaml")
    parser.add_argument("--repo-root", default=None)
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
