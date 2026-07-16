from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description="Import agent-test-bench trace.jsonl into scheduler.v1 offline events.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--profiles-out",
        type=Path,
        help="Optional scheduler tool-profiles.json generated from tool_exec durations.",
    )
    args = parser.parse_args()

    stats = {"read": 0, "written": 0, "unmapped": 0}
    outputs: list[dict[str, Any]] = []
    profile_samples: dict[tuple[str, str | None], list[int]] = {}
    metadata: dict[str, Any] = {}

    for line in args.input.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        stats["read"] += 1
        record = json.loads(line)
        if record.get("type") == "trace_metadata":
            metadata = record
            continue
        if record.get("action_type") != "tool_exec":
            stats["unmapped"] += 1
            continue
        event = map_tool_exec(record, metadata)
        if event is None:
            stats["unmapped"] += 1
            continue
        outputs.append(event)
        operation = infer_operation(record)
        profile_samples.setdefault((event["tool_name"], operation), []).append(event["duration_ms"])
        stats["written"] += 1

    print(json.dumps(stats, indent=2, sort_keys=True))
    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(json.dumps(item, sort_keys=True) for item in outputs) + ("\n" if outputs else ""), encoding="utf-8")
        if args.profiles_out:
            args.profiles_out.parent.mkdir(parents=True, exist_ok=True)
            args.profiles_out.write_text(
                json.dumps(build_profiles(profile_samples), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def map_tool_exec(record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any] | None:
    data = record.get("data")
    if not isinstance(data, dict):
        return None
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    start = as_float(record.get("ts_start") or data.get("ts_start"))
    end = as_float(record.get("ts_end") or data.get("ts_end"))
    duration_ms = 0 if start is None or end is None or end < start else int((end - start) * 1000)
    return {
        "schema_version": "scheduler.v1",
        "event_id": f"import-{uuid4()}",
        "occurred_at": datetime.fromtimestamp(end or start or datetime.now(timezone.utc).timestamp(), timezone.utc).isoformat().replace("+00:00", "Z"),
        "plugin_version": "import-agent-test-bench",
        "run_id": metadata.get("run_id"),
        "session_id": None,
        "session_key": None,
        "agent_id": record.get("agent_id"),
        "tool_call_id": record.get("action_id"),
        "decision_id": None,
        "lease_id": None,
        "tool_name": tool_name,
        "duration_ms": duration_ms,
        "succeeded": not bool(data.get("error")),
        "error_type": "tool_error" if data.get("error") else None,
        "error_digest": None,
        "result_size_bytes": None,
    }


def as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def infer_operation(record: dict[str, Any]) -> str | None:
    data = record.get("data")
    if not isinstance(data, dict):
        return None
    tool_name = data.get("tool_name")
    if isinstance(tool_name, str) and "-" in tool_name:
        base, operation = tool_name.split("-", 1)
        if base == "exec" and operation:
            return operation
    tool_args = data.get("tool_args")
    if isinstance(tool_args, str):
        stripped = tool_args.strip()
        if not stripped:
            return None
        first = stripped.split(maxsplit=1)[0]
        return first[:64]
    return None


def build_profiles(samples: dict[tuple[str, str | None], list[int]]) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    for (tool_name, operation), durations in sorted(samples.items()):
        clean = sorted(duration for duration in durations if duration >= 0)
        if not clean:
            continue
        profiles.append(
            {
                "tool_name": tool_name,
                "operation": operation,
                "resource_class": infer_resource_class(tool_name, operation),
                "duration_p50_ms": percentile(clean, 0.50),
                "duration_p90_ms": percentile(clean, 0.90),
            }
        )
    return {"profile_version": "1", "profiles": profiles}


def percentile(values: list[int], q: float) -> int:
    if len(values) == 1:
        return values[0]
    index = min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))
    return values[index]


def infer_resource_class(tool_name: str, operation: str | None) -> str:
    text = f"{tool_name} {operation or ''}".lower()
    if any(token in text for token in ("pytest", "python", "pip", "npm", "build", "compile")):
        return "cpu_memory_mixed"
    if any(token in text for token in ("curl", "wget", "git", "http")):
        return "network_io"
    if any(token in text for token in ("grep", "rg", "find", "ls", "cat")):
        return "filesystem_io"
    return "unknown"


if __name__ == "__main__":
    main()
