from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(prog="claw-launch")
    sub = parser.add_subparsers(dest="command_name", required=True)
    run = sub.add_parser("run")
    run.add_argument("--execution-id", required=True)
    run.add_argument("--token", required=True)
    run.add_argument(
        "--endpoint",
        default=os.environ.get("CLAW_SCHEDULER_ENDPOINT")
        or os.environ.get("OPENCLAW_SCHEDULER_ENDPOINT")
        or "http://127.0.0.1:8765",
    )
    args = parser.parse_args()

    if args.command_name == "run":
        try:
            raise SystemExit(run_execution(args.endpoint, args.execution_id, args.token))
        except Exception as exc:
            print(f"claw-launch: {exc}", file=sys.stderr)
            raise SystemExit(125) from None
    raise SystemExit(2)


def run_execution(endpoint: str, execution_id: str, token: str) -> int:
    launcher_pid = os.getpid()
    claim = _post_json(
        endpoint,
        "/v2/executions/claim",
        {"execution_id": execution_id, "token": token, "launcher_pid": launcher_pid},
    )
    command = str(claim["command"])
    workdir = claim.get("workdir")
    cwd = str(workdir) if isinstance(workdir, str) and workdir else None
    update_token = str(claim["update_token"])
    placement = claim.get("placement")
    profiling = claim.get("profiling")
    cpu_set = _extract_cpu_set(placement)
    mems = _extract_mems(placement)
    cgroup_path = _prepare_cgroup(execution_id, cpu_set, mems, profiling)
    parsed_affinity = _parse_cpu_list(cpu_set) if _enabled(profiling, "enable_affinity", True) else set()
    affinity_cpus = parsed_affinity or None

    child = _spawn_shell(command, cwd, cgroup_path=cgroup_path, affinity_cpus=affinity_cpus)
    try:
        if not _join_child_cgroup(child.pid, cgroup_path):
            _cleanup_cgroup(cgroup_path)
            cgroup_path = None
        _verify_child_cgroup(child.pid, cgroup_path)
    except Exception:
        _terminate_child_best_effort(child)
        _cleanup_cgroup(cgroup_path)
        raise
    _install_signal_forwarders(child)
    _post_json_best_effort(
        endpoint,
        f"/v2/executions/{execution_id}/started",
        {
            "update_token": update_token,
            "launcher_pid": launcher_pid,
            "child_pid": child.pid,
            "process_starttime_ticks": _read_pid_starttime_ticks(child.pid),
            "cgroup_path": cgroup_path,
            "pid_namespace_inode": _pid_namespace_inode(child.pid),
            "container_id": None,
        },
    )
    returncode = child.wait()
    exit_code = returncode if returncode >= 0 else None
    term_signal = -returncode if returncode < 0 else None
    _post_json_best_effort(
        endpoint,
        f"/v2/executions/{execution_id}/exited",
        {"update_token": update_token, "exit_code": exit_code, "signal": term_signal},
    )
    _cleanup_cgroup(cgroup_path)
    return _shell_exit_code(returncode)


def _spawn_shell(
    command: str,
    cwd: str | None,
    *,
    cgroup_path: str | None = None,
    affinity_cpus: set[int] | None = None,
) -> subprocess.Popen[bytes]:
    if _supports_posix_controls():
        return subprocess.Popen(
            ["/bin/sh", "-lc", command],
            cwd=cwd,
            preexec_fn=_child_preexec(cgroup_path, affinity_cpus),
        )
    return subprocess.Popen(command, cwd=cwd, shell=True)


def _child_preexec(cgroup_path: str | None, affinity_cpus: set[int] | None):
    def preexec() -> None:
        try:
            os.setsid()
        except OSError:
            pass
        if cgroup_path:
            try:
                _write_file(Path(cgroup_path) / "cgroup.procs", str(os.getpid()))
            except OSError:
                pass
        if affinity_cpus and hasattr(os, "sched_setaffinity"):
            try:
                os.sched_setaffinity(0, affinity_cpus)
            except OSError:
                pass

    return preexec


def _install_signal_forwarders(child: subprocess.Popen[bytes]) -> None:
    if not _supports_posix_controls():
        return

    def forward(signum: int, _frame: object) -> None:
        try:
            os.killpg(os.getpgid(child.pid), signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, forward)


def _post_json_best_effort(endpoint: str, path: str, payload: dict[str, Any]) -> None:
    try:
        _post_json(endpoint, path, payload)
    except Exception:
        pass


def _post_json(endpoint: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + path,
        data=data,
        method="POST",
        headers={"content-type": "application/json"},
    )
    bearer = os.environ.get("OPENCLAW_SCHEDULER_TOKEN") or os.environ.get("CLAW_SCHEDULER_TOKEN")
    if bearer:
        request.add_header("authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"sidecar_http_{exc.code}:{detail}") from exc
    return json.loads(raw) if raw else {}


def _read_pid_starttime_ticks(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    if len(fields) <= 19:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _pid_namespace_inode(pid: int) -> int | None:
    try:
        target = os.readlink(f"/proc/{pid}/ns/pid")
    except OSError:
        return None
    prefix = "pid:["
    if target.startswith(prefix) and target.endswith("]"):
        try:
            return int(target[len(prefix) : -1])
        except ValueError:
            return None
    return None


def _explicit_cgroup_path() -> str | None:
    raw = os.environ.get("CLAW_CGROUP_PATH")
    return raw if raw else None


def _prepare_cgroup(
    execution_id: str,
    cpu_set: str | None,
    mems: str | None,
    profiling: object,
) -> str | None:
    required = _env_enabled("CLAW_CGROUP_REQUIRED")
    if not _supports_posix_controls():
        if required:
            raise RuntimeError("cgroup_unavailable: posix_controls_unsupported")
        return _explicit_cgroup_path()
    if not required and not _enabled(profiling, "enable_cgroup", True):
        return _explicit_cgroup_path()
    explicit = _explicit_cgroup_path()
    if explicit:
        return explicit
    root = os.environ.get("CLAW_CGROUP_ROOT")
    if not root:
        if not required and os.environ.get("CLAW_ENABLE_CGROUP") != "1":
            return None
        root = "/sys/fs/cgroup/claw"
    try:
        root_path = Path(root)
        cgroup_path = root_path / _safe_execution_id(execution_id)
        root_path.mkdir(parents=True, exist_ok=True)
        _enable_cgroup_controller(root_path, "cpuset")
        cgroup_path.mkdir(mode=0o700, exist_ok=True)
        if mems:
            _write_file(cgroup_path / "cpuset.mems", mems)
        if cpu_set:
            _write_file(cgroup_path / "cpuset.cpus", cpu_set)
        return str(cgroup_path)
    except OSError as exc:
        if _env_enabled("CLAW_CGROUP_REQUIRED"):
            raise RuntimeError(f"cgroup_unavailable root={root}: {exc}") from exc
        if _env_enabled("CLAW_CGROUP_DEBUG"):
            print(f"claw-launch: cgroup unavailable at {root}: {exc}", file=sys.stderr)
        return None


def _cleanup_cgroup(cgroup_path: str | None) -> None:
    if not cgroup_path:
        return
    root = os.environ.get("CLAW_CGROUP_ROOT")
    explicit = os.environ.get("CLAW_CGROUP_PATH")
    if explicit or not root:
        return
    try:
        Path(cgroup_path).rmdir()
    except OSError:
        pass


def _join_child_cgroup(child_pid: int, cgroup_path: str | None) -> bool:
    if not cgroup_path:
        return False
    try:
        _write_file(Path(cgroup_path) / "cgroup.procs", str(child_pid))
        return True
    except OSError as exc:
        if _env_enabled("CLAW_CGROUP_REQUIRED"):
            raise RuntimeError(f"cgroup_join_failed path={cgroup_path} child_pid={child_pid}: {exc}") from exc
        return False


def _verify_child_cgroup(child_pid: int, cgroup_path: str | None) -> None:
    if not cgroup_path or not _env_enabled("CLAW_CGROUP_REQUIRED"):
        return
    procs = Path(cgroup_path) / "cgroup.procs"
    try:
        pids = {int(line.strip()) for line in procs.read_text(encoding="utf-8").splitlines() if line.strip()}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cgroup_verify_failed path={cgroup_path}: {exc}") from exc
    if child_pid not in pids:
        raise RuntimeError(f"cgroup_join_missing path={cgroup_path} child_pid={child_pid}")


def _terminate_child_best_effort(child: subprocess.Popen[bytes]) -> None:
    try:
        child.terminate()
        child.wait(timeout=1)
    except Exception:
        try:
            child.kill()
        except Exception:
            pass


def _enable_cgroup_controller(cgroup_path: Path, controller: str) -> None:
    subtree = cgroup_path / "cgroup.subtree_control"
    try:
        _write_file(subtree, f"+{controller}")
    except OSError:
        pass


def _write_file(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _extract_cpu_set(placement: object) -> str | None:
    if not isinstance(placement, dict):
        return None
    for key in ("cpu_set", "cpuSet", "cpus"):
        value = placement.get(key)
        if isinstance(value, str):
            cpus = _parse_cpu_list(value)
            return _format_cpu_set(cpus) if cpus else None
        if isinstance(value, list):
            cpus = {int(item) for item in value if isinstance(item, int) and item >= 0}
            return _format_cpu_set(cpus) if cpus else None
    return None


def _extract_mems(placement: object) -> str | None:
    if not isinstance(placement, dict):
        return None
    for key in ("mems", "numa_nodes", "numaNodes"):
        value = placement.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            nodes = {int(item) for item in value if isinstance(item, int) and item >= 0}
            return _format_cpu_set(nodes) if nodes else None
    node = placement.get("numa_node")
    return str(node) if isinstance(node, int) and node >= 0 else None


def _parse_cpu_list(value: str | None) -> set[int]:
    if not value:
        return set()
    cpus: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            try:
                start = int(start_raw)
                end = int(end_raw)
            except ValueError:
                continue
            if start >= 0 and end >= start:
                cpus.update(range(start, end + 1))
            continue
        try:
            cpu = int(part)
        except ValueError:
            continue
        if cpu >= 0:
            cpus.add(cpu)
    return cpus


def _format_cpu_set(values: set[int]) -> str:
    if not values:
        return ""
    ordered = sorted(values)
    ranges: list[str] = []
    start = prev = ordered[0]
    for item in ordered[1:]:
        if item == prev + 1:
            prev = item
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = item
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(ranges)


def _enabled(profiling: object, key: str, default: bool) -> bool:
    if not isinstance(profiling, dict):
        return default
    value = profiling.get(key)
    return value if isinstance(value, bool) else default


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


def _safe_execution_id(execution_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in execution_id)
    return safe[:128] or "exec"


def _supports_posix_controls() -> bool:
    return os.name == "posix"


def _shell_exit_code(returncode: int) -> int:
    if returncode >= 0:
        return returncode
    return 128 + min(127, -returncode)


if __name__ == "__main__":
    main()
