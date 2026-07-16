from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.import_agent_test_bench_trace import (  # noqa: E402
    build_profiles,
    infer_operation,
    map_tool_exec,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate agent-test-bench trace output without changing its benchmark format.",
    )
    parser.add_argument("path", type=Path, help="agent-test-bench run directory or one trace.jsonl file.")
    parser.add_argument("--events-out", type=Path, help="Optional scheduler event JSONL output.")
    parser.add_argument("--profiles-out", type=Path, help="Optional scheduler tool profile JSON output.")
    parser.add_argument("--allow-empty-tools", action="store_true")
    args = parser.parse_args()

    report = validate_path(
        args.path,
        events_out=args.events_out,
        profiles_out=args.profiles_out,
        allow_empty_tools=args.allow_empty_tools,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        sys.exit(1)


def validate_path(
    path: Path,
    *,
    events_out: Path | None = None,
    profiles_out: Path | None = None,
    allow_empty_tools: bool = False,
) -> dict[str, Any]:
    traces = find_traces(path)
    failures: list[str] = []
    warnings: list[str] = []
    if not traces:
        failures.append(f"no trace.jsonl files found under {path}")

    trace_reports = [validate_trace(trace, allow_empty_tools=allow_empty_tools) for trace in traces]
    for trace_report in trace_reports:
        failures.extend(trace_report["failures"])
        warnings.extend(trace_report["warnings"])

    events: list[dict[str, Any]] = []
    profile_samples: dict[tuple[str, str | None], list[int]] = {}
    for trace_report in trace_reports:
        metadata = trace_report["metadata"]
        for record in trace_report["tool_exec_records"]:
            event = map_tool_exec(record, metadata)
            if event is None:
                continue
            events.append(event)
            operation = infer_operation(record)
            profile_samples.setdefault((event["tool_name"], operation), []).append(event["duration_ms"])

    if events_out is not None:
        events_out.parent.mkdir(parents=True, exist_ok=True)
        events_out.write_text(
            "\n".join(json.dumps(item, sort_keys=True) for item in events) + ("\n" if events else ""),
            encoding="utf-8",
        )
    if profiles_out is not None:
        profiles_out.parent.mkdir(parents=True, exist_ok=True)
        profiles_out.write_text(
            json.dumps(build_profiles(profile_samples), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    public_trace_reports = []
    for trace_report in trace_reports:
        item = dict(trace_report)
        item.pop("tool_exec_records", None)
        public_trace_reports.append(item)

    return {
        "ok": not failures,
        "path": str(path),
        "trace_count": len(traces),
        "tool_exec_count": sum(item["tool_exec_count"] for item in trace_reports),
        "event_count": len(events),
        "images": sorted({image for item in trace_reports for image in item["images"]}),
        "traces": public_trace_reports,
        "warnings": warnings,
        "failures": failures,
    }


def find_traces(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.name == "trace.jsonl" else []
    if not path.exists():
        return []
    return sorted(path.glob("**/trace.jsonl"))


def validate_trace(trace: Path, *, allow_empty_tools: bool) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}
    tool_exec_records: list[dict[str, Any]] = []
    action_count = 0
    summary_count = 0
    bad_json_count = 0

    try:
        lines = trace.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return _trace_report(trace, {}, [], [], [f"{trace}: cannot read: {exc}"], 0, 0, 0, 0)

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            bad_json_count += 1
            failures.append(f"{trace}:{index}: invalid JSON")
            continue
        if not metadata and record.get("type") == "trace_metadata":
            metadata = record
        if record.get("type") == "action":
            action_count += 1
        if record.get("action_type") == "tool_exec":
            tool_exec_records.append(record)
        if record.get("type") == "summary":
            summary_count += 1

    if not metadata:
        failures.append(f"{trace}: missing trace_metadata record")
    elif metadata.get("trace_format_version") != 5:
        failures.append(
            f"{trace}: expected trace_format_version 5, got {metadata.get('trace_format_version')!r}"
        )
    if not tool_exec_records and not allow_empty_tools:
        failures.append(f"{trace}: no tool_exec actions found")

    images = images_for_attempt(trace.parent)
    if not images and looks_like_container_attempt(trace.parent):
        warnings.append(f"{trace.parent}: no image metadata found in run_manifest/results")

    return _trace_report(
        trace,
        metadata,
        tool_exec_records,
        warnings,
        failures,
        action_count,
        summary_count,
        bad_json_count,
        len(lines),
        images=images,
    )


def _trace_report(
    trace: Path,
    metadata: dict[str, Any],
    tool_exec_records: list[dict[str, Any]],
    warnings: list[str],
    failures: list[str],
    action_count: int,
    summary_count: int,
    bad_json_count: int,
    line_count: int,
    *,
    images: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "trace": str(trace),
        "metadata": metadata,
        "trace_format_version": metadata.get("trace_format_version"),
        "benchmark": metadata.get("benchmark"),
        "scaffold": metadata.get("scaffold"),
        "action_count": action_count,
        "tool_exec_count": len(tool_exec_records),
        "summary_count": summary_count,
        "bad_json_count": bad_json_count,
        "line_count": line_count,
        "images": images or [],
        "tool_exec_records": tool_exec_records,
        "warnings": warnings,
        "failures": failures,
    }


def images_for_attempt(attempt_dir: Path) -> list[str]:
    images: set[str] = set()
    for filename in ("run_manifest.json", "results.json"):
        path = attempt_dir / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        collect_images(payload, images)
    return sorted(images)


def collect_images(value: Any, images: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if isinstance(item, str) and (
                lowered in {"docker_image", "image", "source_image", "fixed_image_name"}
                or lowered.endswith("_image")
            ):
                images.add(item)
            else:
                collect_images(item, images)
    elif isinstance(value, list):
        for item in value:
            collect_images(item, images)


def looks_like_container_attempt(attempt_dir: Path) -> bool:
    return (attempt_dir / "container_stdout.txt").exists() or (attempt_dir / "resources.json").exists()


if __name__ == "__main__":
    main()
