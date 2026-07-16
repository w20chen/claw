from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH_ROOT = Path(r"C:\Users\29068\Desktop\agent-test-bench")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_agent_test_bench_run import validate_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run agent-test-bench through its original trace_collect.cli entry point, "
            "then validate/import the produced traces."
        )
    )
    parser.add_argument("--bench-root", type=Path, default=DEFAULT_BENCH_ROOT)
    parser.add_argument("--python", default=sys.executable, help="Python executable used for agent-test-bench.")
    parser.add_argument("--dry-run", action="store_true", help="Print the delegated command without running it.")
    parser.add_argument("--no-validate", action="store_true", help="Skip post-run trace validation.")
    parser.add_argument("--allow-empty-tools", action="store_true")
    parser.add_argument("--events-out", type=Path, help="Optional scheduler event JSONL output.")
    parser.add_argument("--profiles-out", type=Path, help="Optional scheduler profile JSON output.")
    parser.add_argument(
        "benchmark_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed verbatim to `python -m trace_collect.cli` after `--`.",
    )
    args = parser.parse_args()

    benchmark_args = list(args.benchmark_args)
    if benchmark_args and benchmark_args[0] == "--":
        benchmark_args = benchmark_args[1:]

    command = [args.python, "-m", "trace_collect.cli", *benchmark_args]
    env = build_env(args.bench_root)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "cwd": str(args.bench_root),
                    "command": command,
                    "PYTHONPATH": env.get("PYTHONPATH"),
                },
                indent=2,
            )
        )
        return

    if not args.bench_root.exists():
        raise SystemExit(f"agent-test-bench root does not exist: {args.bench_root}")

    completed = subprocess.run(
        command,
        cwd=args.bench_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    run_dir = parse_run_dir(completed.stdout, args.bench_root)
    if run_dir is None:
        raise SystemExit("agent-test-bench completed but did not print `Traces written to:`")
    if args.no_validate:
        print(json.dumps({"run_dir": str(run_dir), "validated": False}, indent=2, sort_keys=True))
        return

    report = validate_path(
        run_dir,
        events_out=args.events_out,
        profiles_out=args.profiles_out,
        allow_empty_tools=args.allow_empty_tools,
    )
    report["run_dir"] = str(run_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(1)


def build_env(bench_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    src = str(bench_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
    return env


def parse_run_dir(output: str, bench_root: Path) -> Path | None:
    match = re.search(r"Traces written to:\s*(.+?)/?\s*$", output, flags=re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip().rstrip("/")
    path = Path(value)
    if not path.is_absolute():
        path = bench_root / path
    return path


if __name__ == "__main__":
    main()
