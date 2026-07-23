"""
SWE-Rebench Batch Runner
========================

Orchestrates batch execution of swe-rebench tasks with OpenClaw + sidecar
trace collection inside Docker containers.

Usage::

    # 1. Prepare the runtime bundle (once)
    python -m swe_rebench.runner prepare

    # 2. Run tasks from a swe-bench dataset
    python -m swe_rebench.runner run --dataset ./swe-bench.json --sample 5

    # 3. Collect and export traces
    python -m swe_rebench.runner collect

    # 4. Clean up
    python -m swe_rebench.runner cleanup

Or all-in-one::

    python -m swe_rebench.runner run \\
        --prepare \\
        --dataset ./swe-bench.json \\
        --sample 10 \\
        --export
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swe_rebench.config import RunnerConfig
from swe_rebench.docker import ContainerResult, get_docker_client, pull_image, run_container
from swe_rebench.prepare import build_bundle
from swe_rebench.task_source import TaskDef, create_single_task, load_tasks_from_swebench_dataset


# ── Report helpers ────────────────────────────────────────────────

@dataclass
class BatchReport:
    config_path: str
    total_tasks: int
    completed: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config_path,
            "total_tasks": self.total_tasks,
            "completed": self.completed,
            "failed": self.failed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "results": self.results,
        }


def _result_dict(r: ContainerResult) -> dict[str, Any]:
    return {
        "task_id": r.task_id,
        "image": r.image,
        "exit_code": r.exit_code,
        "error": r.error,
        "trace_dir": str(r.trace_dir) if r.trace_dir else None,
        "trace_files": [str(tf) for tf in r.trace_files],
        "trace_lines": sum(_count_lines(tf) for tf in r.trace_files),
        "duration_seconds": round(r.duration_seconds, 1),
    }


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in open(path, encoding="utf-8"))
    except Exception:
        return 0


# ── Lock for thread-safe logging ──────────────────────────────────

_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


# ── Core orchestration ────────────────────────────────────────────

def run_batch(
    config: RunnerConfig,
    tasks: list[TaskDef],
    bundle_dir: Path,
    *,
    export_after: bool = False,
) -> BatchReport:
    """Run a batch of tasks and return a summary report."""
    _log(f"\n{'='*60}")
    _log(f"Batch run: {len(tasks)} tasks, parallelism={config.batch.parallelism}")
    _log(f"Trace root: {config.output.trace_root}")
    _log(f"{'='*60}\n")

    client = get_docker_client(config.docker)
    report = BatchReport(
        config_path="",
        total_tasks=len(tasks),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    start_wall = time.monotonic()

    # Pre-pull images in parallel (best-effort)
    _pre_pull_images(client, tasks, config.docker.pull_policy)

    max_workers = max(1, config.batch.parallelism)
    completed_count = 0
    failed_count = 0
    futures_map: dict[Any, TaskDef] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for task in tasks:
            trace_dir = _task_trace_dir(config, task)
            future = executor.submit(
                _run_one,
                client, task, bundle_dir, trace_dir, config,
            )
            futures_map[future] = task

        for future in as_completed(futures_map):
            task = futures_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = ContainerResult(
                    task_id=task.instance_id,
                    image=task.image,
                    exit_code=-1,
                    error=str(exc),
                )

            result_dict = _result_dict(result)
            report.results.append(result_dict)

            if result.exit_code == 0 and not result.error:
                completed_count += 1
                status = "OK"
            else:
                failed_count += 1
                status = "FAIL"

            progress = completed_count + failed_count
            _log(
                f"[{progress}/{len(tasks)}] {status} "
                f"task={result.task_id} "
                f"exit={result.exit_code} "
                f"traces={len(result.trace_files)} "
                f"lines={result_dict['trace_lines']} "
                f"time={result.duration_seconds:.0f}s"
            )
            if result.error:
                _log(f"       error: {result.error}")

    report.completed = completed_count
    report.failed = failed_count
    report.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report.duration_seconds = time.monotonic() - start_wall

    _log(f"\n{'='*60}")
    _log(f"Done: {completed_count} OK, {failed_count} FAIL, {report.duration_seconds:.0f}s total")
    _log(f"{'='*60}\n")

    # Write report
    report_path = config.output.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _log(f"Report written to {report_path}")

    # Export traces if requested
    if export_after:
        _export_traces(config, report)

    return report


def _run_one(
    client: Any,
    task: TaskDef,
    bundle_dir: Path,
    trace_dir: Path,
    config: RunnerConfig,
) -> ContainerResult:
    """Execute a single task container (called in worker thread)."""
    retries = config.batch.retry_failed + 1
    last_result: ContainerResult | None = None

    for attempt in range(1, retries + 1):
        if attempt > 1:
            _log(f"[{task.instance_id}] retry {attempt}/{retries}")

        # Pull image if needed
        if not pull_image(client, task.image, config.docker.pull_policy):
            return ContainerResult(
                task_id=task.instance_id, image=task.image,
                exit_code=-1, error=f"Failed to pull image: {task.image}",
                trace_dir=trace_dir,
            )

        result = run_container(
            client=client,
            image=task.image,
            task_id=task.instance_id,
            bundle_dir=bundle_dir,
            trace_dir=trace_dir,
            problem_statement=task.problem_statement,
            config=config.docker,
            llm_api_key=config.llm.api_key,
            llm_upstream_url=config.llm.upstream_base_url,
            timeout_seconds=config.batch.task_timeout_seconds,
            env_extra=task.extra_env,
        )
        last_result = result

        # Success ── don't retry
        if result.exit_code == 0 and not result.error:
            return result

    return last_result or ContainerResult(
        task_id=task.instance_id, image=task.image,
        exit_code=-1, error="All retries exhausted",
        trace_dir=trace_dir,
    )


def _pre_pull_images(client: Any, tasks: list[TaskDef], policy: str) -> None:
    """Pre-pull all unique images in parallel."""
    unique = list({t.image for t in tasks if t.image})
    if not unique:
        return
    _log(f"Pre-pulling {len(unique)} unique images...")
    with ThreadPoolExecutor(max_workers=min(4, len(unique))) as executor:
        futures = {executor.submit(pull_image, client, img, policy): img for img in unique}
        for future in as_completed(futures):
            img = futures[future]
            try:
                ok = future.result()
                _log(f"  pull {img}: {'OK' if ok else 'FAIL'}")
            except Exception as exc:
                _log(f"  pull {img}: {exc}")


def _task_trace_dir(config: RunnerConfig, task: TaskDef) -> Path:
    """Compute the per-task trace output directory."""
    safe_id = task.instance_id.replace("/", "_").replace(":", "_")
    return config.output.trace_root / safe_id


# ── Trace export ──────────────────────────────────────────────────

def _export_traces(config: RunnerConfig, report: BatchReport) -> None:
    """Copy trace files into a flat export directory keyed by task ID."""
    export_dir = config.output.flat_export_dir
    if export_dir is None:
        return
    export_dir.mkdir(parents=True, exist_ok=True)
    exported = 0
    for entry in report.results:
        task_id = entry["task_id"]
        trace_files = entry.get("trace_files", [])
        for tf_path_str in trace_files:
            src = Path(tf_path_str)
            if not src.exists():
                continue
            # Name: {task_id}_{original_name}
            dst_name = f"{task_id}_{src.name}"
            dst = export_dir / dst_name
            shutil.copy2(src, dst)
            exported += 1
    _log(f"Exported {exported} trace files to {export_dir}")


def collect_traces(config: RunnerConfig) -> BatchReport:
    """Scan trace_root for existing trace files and export them.

    Does not run containers ── only collects traces from previous runs.
    """
    trace_root = config.output.trace_root
    if not trace_root.exists():
        _log(f"Trace root not found: {trace_root}")
        return BatchReport(config_path="", total_tasks=0)

    results: list[dict[str, Any]] = []
    task_dirs = sorted(trace_root.iterdir())
    for task_dir in task_dirs:
        if not task_dir.is_dir():
            continue
        traces = sorted(task_dir.glob("*.jsonl"))
        if not traces:
            continue
        results.append({
            "task_id": task_dir.name,
            "image": "",
            "exit_code": 0,
            "error": None,
            "trace_dir": str(task_dir),
            "trace_files": [str(t) for t in traces],
            "trace_lines": sum(_count_lines(t) for t in traces),
            "duration_seconds": 0.0,
        })

    report = BatchReport(
        config_path="",
        total_tasks=len(results),
        completed=len(results),
        results=results,
    )
    _log(f"Found {len(results)} task directories with traces")

    if config.output.flat_export_dir:
        _export_traces(config, report)

    report_path = config.output.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _log(f"Report written to {report_path}")

    return report


# ── CLI ───────────────────────────────────────────────────────────

def _detect_repo_root() -> Path:
    p = Path(__file__).resolve()
    for _ in range(6):
        if (p / "AGENTS.md").exists():
            return p
        p = p.parent
    return Path.cwd()


def _resolve_path(value: str, repo_root: Path) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return repo_root / p


def main() -> None:
    repo_root = _detect_repo_root()
    default_config = str(repo_root / "swe_rebench" / "config.example.yaml")

    parser = argparse.ArgumentParser(
        description="SWE-Rebench batch runner with OpenClaw + sidecar trace collection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", default=default_config,
        help=f"Path to config YAML (default: {default_config})",
    )
    sub = parser.add_subparsers(dest="command", help="Sub-command")

    # Share --config across all subcommands so it can be placed before
    # OR after the subcommand (argparse limitation workaround).
    config_arg = lambda p: p.add_argument(
        "--config", default=None,
        help=f"Path to config YAML (default: {default_config})",
    )

    # ── prepare ──
    prep = sub.add_parser("prepare", help="Build the runtime bundle")
    config_arg(prep)
    prep.add_argument("--bundle-dir", default=None, help="Override bundle output directory")

    # ── run ──
    run_p = sub.add_parser("run", help="Run swe-rebench tasks")
    config_arg(run_p)
    run_p.add_argument("--prepare", action="store_true", dest="do_prepare",
                       help="Run prepare step before executing tasks")
    run_p.add_argument("--dataset", default=None,
                       help="Path to swe-bench dataset JSON/JSONL file")
    run_p.add_argument("--tasks", default=None,
                       help="Path to simple JSON task list")
    run_p.add_argument("--image", default=None,
                       help="Single Docker image to run (requires --task-id and --problem)")
    run_p.add_argument("--task-id", default=None, help="Task ID for single-image mode")
    run_p.add_argument("--problem", default=None, help="Problem statement for single-image mode")
    run_p.add_argument("--sample", type=int, default=0,
                       help="Run only the first N tasks (0 = all)")
    run_p.add_argument("--parallelism", type=int, default=None,
                       help="Override parallelism from config")
    run_p.add_argument("--export", action="store_true",
                       help="Export traces to flat directory after run")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Print tasks without running containers")

    # ── collect ──
    col = sub.add_parser("collect", help="Collect and export traces from previous runs")
    config_arg(col)
    col.add_argument("--export-dir", default=None, help="Override flat export directory")

    # ── cleanup ──
    cln = sub.add_parser("cleanup", help="(No-op: containers are auto-removed)")
    config_arg(cln)

    args = parser.parse_args()
    # Resolve --config: subcommand-level arg takes precedence over top-level.
    config_path = args.config or default_config

    if not args.command:
        parser.print_help()
        return

    config = RunnerConfig.from_yaml(config_path, repo_root=repo_root)

    if args.command == "prepare":
        bundle_dir = Path(args.bundle_dir) if args.bundle_dir else None
        if bundle_dir is not None:
            config.bundle.output_dir = str(bundle_dir)
        build_bundle(config)
        return

    if args.command == "run":
        if args.parallelism is not None:
            config.batch.parallelism = args.parallelism

        # Build bundle if requested
        bundle_dir = repo_root / config.bundle.output_dir
        if args.do_prepare or not bundle_dir.exists():
            _log("Preparing runtime bundle...")
            build_bundle(config)

        # Load tasks
        tasks = _load_tasks(args, repo_root)
        if args.sample > 0:
            tasks = tasks[: args.sample]

        if not tasks:
            _log("ERROR: no tasks loaded.  Provide --dataset, --tasks, or --image.")
            sys.exit(1)

        _log(f"Loaded {len(tasks)} tasks")

        if args.dry_run:
            for i, t in enumerate(tasks):
                _log(f"  [{i+1}] {t.instance_id}  image={t.image}")
                if t.problem_statement:
                    _log(f"       problem: {t.problem_statement[:120]}...")
            return

        report = run_batch(config, tasks, bundle_dir, export_after=args.export)

        # Print summary
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        if report.failed > 0:
            sys.exit(1)

    elif args.command == "collect":
        if args.export_dir:
            config.output.flat_export_dir = _resolve_path(args.export_dir, repo_root)
        report = collect_traces(config)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    elif args.command == "cleanup":
        _log("Containers are auto-removed (--rm). Nothing to clean up.")


def _load_tasks(args: argparse.Namespace, repo_root: Path) -> list[TaskDef]:
    """Load tasks from whichever source was specified."""
    # Single image mode
    if args.image:
        task_id = args.task_id or "task-1"
        problem = args.problem or ""
        return [create_single_task(task_id, args.image, problem)]

    # Simple JSON task list
    if args.tasks:
        path = _resolve_path(args.tasks, repo_root)
        if not path.exists():
            raise FileNotFoundError(
                f"Tasks file not found: {path}\n"
                f"Generate one with:\n"
                f"  python -m swe_rebench.discover --out {path}"
            )
        from swe_rebench.task_source import load_tasks_from_simple_list
        return load_tasks_from_simple_list(path)

    # Swe-bench dataset
    if args.dataset:
        path = _resolve_path(args.dataset, repo_root)
        if not path.exists():
            raise FileNotFoundError(
                f"Dataset file not found: {path}\n"
                f"Generate one with:\n"
                f"  python -m swe_rebench.discover --out {path}\n"
                f"  python -m swe_rebench.discover --sample 10 --out {path}\n"
                f"Or use --image for a single task:\n"
                f"  python -m swe_rebench.runner run --image <docker-image> --task-id <id> --problem \"...\""
            )
        return load_tasks_from_swebench_dataset(path)

    return []


if __name__ == "__main__":
    main()
