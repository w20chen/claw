from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an agent-test-bench-style trace.jsonl in the CLI.")
    parser.add_argument("trace", type=Path, nargs="?", default=Path("data/trace.jsonl"))
    parser.add_argument("--tail", type=int, default=30, help="Show the last N actions. Use 0 with --all.")
    parser.add_argument("--all", action="store_true", help="Show all actions.")
    parser.add_argument("--run-id", help="Only show actions for one run_id.")
    parser.add_argument("--type", choices=["llm_call", "tool_exec"], help="Only show one action type.")
    parser.add_argument("--details", action="store_true", help="Print expanded action details below the table.")
    parser.add_argument("--timeline", action="store_true", help="With --details, print resource timeline points.")
    parser.add_argument("--width", type=int, default=120, help="Maximum preview width.")
    args = parser.parse_args()

    trace = load_trace(args.trace)
    actions = trace.actions
    if args.run_id:
        actions = [item for item in actions if run_id(item, trace.metadata) == args.run_id]
    if args.type:
        actions = [item for item in actions if item.get("action_type") == args.type]
    if not args.all and args.tail > 0:
        actions = actions[-args.tail :]

    print_header(args.trace, trace, actions)
    if not actions:
        print("No actions matched.")
        return
    print_table(actions, metadata=trace.metadata, width=max(60, args.width))
    if args.details:
        print_details(
            actions,
            metadata=trace.metadata,
            show_timeline=args.timeline,
            width=max(60, args.width),
        )


class Trace:
    def __init__(
        self,
        *,
        metadata: dict[str, Any] | None,
        actions: list[dict[str, Any]],
        bad_lines: list[tuple[int, str]],
    ) -> None:
        self.metadata = metadata
        self.actions = actions
        self.bad_lines = bad_lines


def load_trace(path: Path) -> Trace:
    metadata: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = []
    bad_lines: list[tuple[int, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            bad_lines.append((line_no, exc.msg))
            continue
        if metadata is None and record.get("type") == "trace_metadata":
            metadata = record
        if record.get("type") == "action" or record.get("action_type") is not None:
            actions.append(record)
    return Trace(metadata=metadata, actions=actions, bad_lines=bad_lines)


def print_header(path: Path, trace: Trace, shown_actions: list[dict[str, Any]]) -> None:
    counts = Counter(item.get("action_type", "unknown") for item in trace.actions)
    metadata = trace.metadata or {}
    print(f"Trace: {path}")
    if metadata:
        print(
            "Format: "
            f"v{metadata.get('trace_format_version', '?')} "
            f"scaffold={metadata.get('scaffold', '?')} "
            f"mode={metadata.get('mode', '?')}"
        )
    else:
        print("Format: missing trace_metadata")
    print(
        "Actions: "
        f"total={len(trace.actions)} "
        f"shown={len(shown_actions)} "
        f"llm_call={counts.get('llm_call', 0)} "
        f"tool_exec={counts.get('tool_exec', 0)} "
        f"bad_json={len(trace.bad_lines)}"
    )
    print()


def print_table(
    actions: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None,
    width: int,
) -> None:
    rows = [
        timeline_row(index, action, metadata=metadata, width=width)
        for index, action in enumerate(actions, start=1)
    ]
    columns = [
        ("#", 4),
        ("time", 19),
        ("run", 10),
        ("type", 9),
        ("name", 18),
        ("dur", 8),
        ("resources", 42),
        ("preview", max(20, width - 110)),
    ]
    print(format_row([name for name, _ in columns], [size for _, size in columns]))
    print(format_row(["-" * size for _, size in columns], [size for _, size in columns]))
    for row in rows:
        print(format_row(row, [size for _, size in columns]))


def timeline_row(
    index: int,
    action: dict[str, Any],
    *,
    metadata: dict[str, Any] | None,
    width: int,
) -> list[str]:
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    action_type = str(action.get("action_type") or "?")
    if action_type == "tool_exec":
        name = str(data.get("tool_name") or "?")
        preview = tool_preview(data)
        resources = resource_summary(data.get("resource_usage"))
    elif action_type == "llm_call":
        provider = data.get("provider")
        model = data.get("model")
        name = "/".join(str(item) for item in (provider, model) if item) or "llm"
        preview = llm_preview(data)
        resources = "-"
    else:
        name = "?"
        preview = preview_value(data, width)
        resources = "-"
    return [
        str(index),
        format_time(action.get("ts_start")),
        short(run_id(action, metadata), 10),
        action_type,
        short(name, 18),
        format_duration(data.get("duration_ms"), action),
        short(resources, 42),
        short(preview, max(20, width - 110)),
    ]


def print_details(
    actions: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None,
    show_timeline: bool,
    width: int,
) -> None:
    print("\nDetails")
    print("=======")
    for index, action in enumerate(actions, start=1):
        data = action.get("data") if isinstance(action.get("data"), dict) else {}
        action_type = action.get("action_type")
        print(f"\n[{index}] {action_type} {action.get('action_id', '')}")
        print(f"run_id: {run_id(action, metadata) or '-'}")
        print(f"time:   {format_time(action.get('ts_start'))} -> {format_time(action.get('ts_end'))}")
        if action_type == "tool_exec":
            print(f"tool:   {data.get('tool_name')}")
            print(f"args:   {preview_value(data.get('tool_args'), width)}")
            print(f"result: {preview_value(data.get('tool_result'), width)}")
            print(f"res:    {resource_summary(data.get('resource_usage'), verbose=True)}")
            if show_timeline:
                print_timeline(data.get("resource_usage"))
        elif action_type == "llm_call":
            print(f"model:  {data.get('provider')}/{data.get('model')}")
            print(f"in:     {availability(data.get('messages_in'))} {preview_value(data.get('messages_in'), width)}")
            print(f"out:    {availability(data.get('content'))} {preview_value(data.get('content'), width)}")
            raw = data.get("openclaw_ended_event") or data.get("openclaw_started_event")
            print(f"hook:   {preview_value(raw, width)}")
        else:
            print(preview_value(data, width))


def print_timeline(resource_usage: Any) -> None:
    if not isinstance(resource_usage, dict):
        return
    timeline = resource_usage.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        print("timeline: -")
        return
    suffix = " truncated" if resource_usage.get("timeline_truncated") else ""
    print(f"timeline:{suffix}")
    print("  time                 cpu_s      rss        rd         wr         net_rx     net_tx     proc")
    for point in timeline:
        if not isinstance(point, dict):
            continue
        print(
            "  "
            f"{format_time(point.get('ts'))}  "
            f"{format_float(point.get('cpu_time_s')).rjust(8)}  "
            f"{format_bytes(point.get('rss_bytes')).rjust(9)}  "
            f"{format_bytes(point.get('read_bytes')).rjust(9)}  "
            f"{format_bytes(point.get('write_bytes')).rjust(9)}  "
            f"{format_bytes(point.get('net_rx_bytes')).rjust(9)}  "
            f"{format_bytes(point.get('net_tx_bytes')).rjust(9)}  "
            f"{str(point.get('process_count') or '-').rjust(4)}"
        )


def tool_preview(data: dict[str, Any]) -> str:
    args = data.get("tool_args")
    result = data.get("tool_result")
    command = args.get("command") if isinstance(args, dict) else args
    result_text = result_text_preview(result)
    if command and result_text:
        return f"{command} => {result_text}"
    if command:
        return str(command)
    return result_text or "-"


def llm_preview(data: dict[str, Any]) -> str:
    content = data.get("content")
    messages = data.get("messages_in")
    if content is not None:
        return f"content={preview_value(content, 80)}"
    if messages is not None:
        return f"messages={preview_value(messages, 80)}"
    ended = data.get("openclaw_ended_event")
    if isinstance(ended, dict):
        bits = []
        if ended.get("requestPayloadBytes") is not None:
            bits.append(f"req={ended.get('requestPayloadBytes')}B")
        if ended.get("responseStreamBytes") is not None:
            bits.append(f"resp={ended.get('responseStreamBytes')}B")
        if ended.get("timeToFirstByteMs") is not None:
            bits.append(f"ttfb={ended.get('timeToFirstByteMs')}ms")
        if bits:
            return " ".join(bits)
    return "messages/content unavailable"


def resource_summary(value: Any, *, verbose: bool = False) -> str:
    if not isinstance(value, dict):
        return "-"
    parts = [
        f"attr={value.get('attribution_status') or '?'}",
        f"q={value.get('sampling_quality') or '?'}",
        f"cpu_avg={format_cores(value.get('cpu_utilization_avg_cores'))}",
        f"rss_max={format_bytes(value.get('memory_rss_bytes_peak') or value.get('memory_footprint_bytes'))}",
        f"rd_avg={format_bytes_per_s(value.get('disk_read_bytes_per_s'))}",
        f"wr_avg={format_bytes_per_s(value.get('disk_write_bytes_per_s'))}",
        f"net_avg={format_bytes_per_s(value.get('net_rx_bytes_per_s'))}/{format_bytes_per_s(value.get('net_tx_bytes_per_s'))}",
    ]
    if verbose:
        parts.extend(
            [
                f"cpu_total={format_seconds(value.get('cpu_time_delta_s'))}",
                f"rd_total={format_bytes(value.get('disk_read_bytes_delta'))}",
                f"wr_total={format_bytes(value.get('disk_write_bytes_delta'))}",
                f"net_total={format_bytes(value.get('net_rx_bytes_delta'))}/{format_bytes(value.get('net_tx_bytes_delta'))}",
                f"points={format_number(value.get('sampling_point_count'))}",
                f"interval={format_number(value.get('sampling_interval_ms'))}ms",
                f"ctx={format_number(value.get('context_switches_delta'))}",
                f"pid={value.get('target_pid') or '-'}",
                f"source={value.get('monitor_source') or '-'}",
            ]
        )
    return " ".join(parts)


def result_text_preview(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        details = value.get("details")
        if isinstance(details, dict) and details.get("aggregated") is not None:
            return str(details.get("aggregated"))
        content = value.get("content")
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("text") is not None:
                    texts.append(str(item["text"]))
            if texts:
                return " ".join(texts)
    return preview_value(value, 80) if value is not None else ""


def format_row(values: list[str], widths: list[int]) -> str:
    return "  ".join(short(value, width).ljust(width) for value, width in zip(values, widths))


def format_time(value: Any) -> str:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(value: Any, action: dict[str, Any]) -> str:
    if value is None:
        start = action.get("ts_start")
        end = action.get("ts_end")
        try:
            value = max(0.0, (float(end) - float(start)) * 1000)
        except (TypeError, ValueError):
            return "-"
    try:
        return f"{float(value):.0f}ms"
    except (TypeError, ValueError):
        return "-"


def format_seconds(value: Any) -> str:
    try:
        return f"{float(value):.3f}s"
    except (TypeError, ValueError):
        return "-"


def format_float(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "-"


def format_cores(value: Any) -> str:
    try:
        return f"{float(value):.2f}c"
    except (TypeError, ValueError):
        return "-"


def format_bytes_per_s(value: Any) -> str:
    formatted = format_bytes(value)
    return "-" if formatted == "-" else f"{formatted}/s"


def format_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(number) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(number)}B"
            return f"{number:.1f}{unit}"
        number /= 1024
    return f"{number:.1f}TB"


def format_number(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def run_id(action: dict[str, Any], metadata: dict[str, Any] | None = None) -> str | None:
    if action.get("run_id"):
        return str(action["run_id"])
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    for key in ("openclaw_before_event", "openclaw_after_event", "openclaw_started_event", "openclaw_ended_event"):
        raw = data.get(key)
        if isinstance(raw, dict) and raw.get("runId"):
            return str(raw["runId"])
    if metadata and metadata.get("run_id"):
        return str(metadata["run_id"])
    return None


def availability(value: Any) -> str:
    return "present" if value is not None else "missing"


def preview_value(value: Any, width: int) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        text = value.replace("\n", "\\n")
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return short(text, width)


def short(value: Any, width: int) -> str:
    text = str(value)
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "~"


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
