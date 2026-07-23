from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any


def read_topology() -> dict[str, Any]:
    if os.name != "posix":
        return {
            "available": False,
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "online_cpus": [],
            "numa_nodes": [],
            "llc_clusters": [],
            "reason": "procfs/sysfs topology is only available on Linux-like systems",
        }
    online = _read_cpu_list(Path("/sys/devices/system/cpu/online"))
    nodes = []
    for node in sorted(Path("/sys/devices/system/node").glob("node*")) if Path("/sys/devices/system/node").exists() else []:
        cpulist = _read_text(node / "cpulist")
        nodes.append({"node": int(node.name.replace("node", "")), "cpulist": cpulist})
    return {
        "available": True,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "online_cpus": online,
        "numa_nodes": nodes,
        "llc_clusters": _read_llc_clusters(),
    }


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_cpu_list(path: Path) -> list[int]:
    text = _read_text(path)
    if not text:
        return list(range(os.cpu_count() or 0))
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            out.extend(range(int(start), int(end) + 1))
        else:
            out.append(int(part))
    return out


def _read_llc_clusters() -> list[dict[str, str]]:
    clusters: dict[str, dict[str, str]] = {}
    root = Path("/sys/devices/system/cpu")
    for cache in root.glob("cpu*/cache/index*"):
        level = _read_text(cache / "level")
        shared = _read_text(cache / "shared_cpu_list")
        if level == "3" and shared:
            clusters[shared] = {"shared_cpu_list": shared}
    return list(clusters.values())
