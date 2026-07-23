"""
SWE-Rebench task discovery and dataset generation.

Generates a tasks JSON file that ``runner.py --dataset`` can consume.
Sources (tried in order):

1. Local ``agent-test-bench`` checkout — uses its ``inspect_swebench.py``
   or the ``datasets`` library if available.
2. Direct HuggingFace download — requires ``pip install datasets``.
3. Manual image list — if you already know the Docker image names.

Usage::

    # Discover from agent-test-bench
    python -m swe_rebench.discover --bench-root ~/agent-test-bench --out tasks.json

    # Download from HuggingFace
    python -m swe_rebench.discover --out tasks.json --sample 10

    # Generate from known images
    python -m swe_rebench.discover --images images.txt --out tasks.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
HF_DATASET = "nebius/SWE-rebench"
HF_SPLIT = "filtered"
DEFAULT_BENCH_ROOT_ENV = "AGENT_TEST_BENCH_ROOT"
DEFAULT_BENCH_ROOT = REPO_ROOT.parent / "agent-test-bench"


def discover_from_agent_test_bench(
    bench_root: Path,
    sample: int = 0,
) -> list[dict[str, Any]]:
    """Try to list tasks via agent-test-bench's inspect_swebench.py."""
    inspect_script = bench_root / "scripts" / "inspect_swebench.py"
    if not inspect_script.exists():
        raise FileNotFoundError(
            f"inspect_swebench.py not found at {inspect_script}. "
            f"Is agent-test-bench checked out at {bench_root}?"
        )

    # First try: use `inspect_swebench.py list` (requires datasets)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(inspect_script),
                "--benchmark", "swe-rebench",
                "list",
            ],
            cwd=str(bench_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _parse_list_output(result.stdout, sample)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Second try: directly load from HuggingFace
    return _load_from_huggingface(sample)


def _parse_list_output(output: str, sample: int = 0) -> list[dict[str, Any]]:
    """Parse the table output from inspect_swebench.py list."""
    tasks: list[dict[str, Any]] = []
    lines = output.strip().splitlines()
    # The output is typically a table: instance_id | repo | image | ...
    for line in lines:
        line = line.strip()
        if not line or line.startswith("-") or line.startswith("="):
            continue
        # Try to extract instance_id (first column)
        parts = line.split("|")
        if len(parts) >= 1:
            iid = parts[0].strip()
            if iid and not iid.lower().startswith("instance"):
                tasks.append({"instance_id": iid})
    if sample > 0 and len(tasks) > sample:
        tasks = tasks[:sample]
    return tasks


def _load_from_huggingface(sample: int = 0) -> list[dict[str, Any]]:
    """Load tasks directly from HuggingFace datasets."""
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "The 'datasets' package is required to download tasks from HuggingFace. "
            "Install it with: pip install datasets"
        )

    _log(f"Downloading {HF_DATASET} (split={HF_SPLIT})...")
    ds = load_dataset(HF_DATASET, split=HF_SPLIT)
    tasks: list[dict[str, Any]] = []
    for row in ds:
        task = dict(row)
        # Normalize field names for runner.py compatibility
        task_out: dict[str, Any] = {
            "instance_id": str(task.get("instance_id", "")),
            "image": str(task.get("docker_image", "")),
            "problem_statement": str(task.get("problem_statement", "")),
            "repo": str(task.get("repo", "")),
            "base_commit": str(task.get("base_commit", "")),
        }
        # Preserve additional fields that may be useful
        for key in ("FAIL_TO_PASS", "PASS_TO_PASS", "install_config", "version"):
            if key in task:
                task_out[key] = task[key]
        tasks.append(task_out)
        if sample > 0 and len(tasks) >= sample:
            break

    _log(f"Downloaded {len(tasks)} tasks from HuggingFace")
    return tasks


def discover_from_images(image_file: Path) -> list[dict[str, Any]]:
    """Generate task stubs from a list of Docker images (one per line)."""
    text = _read_text_file(image_file)
    tasks: list[dict[str, Any]] = []
    for line in text.splitlines():
        image = line.strip()
        if not image or image.startswith("#"):
            continue
        # Derive task ID from image name
        # e.g. swerebench/sweb.eval.x86_64.django__django-12345:latest
        #   -> django__django-12345
        iid = _derive_task_id(image)
        tasks.append({
            "instance_id": iid,
            "image": image,
            "problem_statement": "",
            "repo": "",
            "base_commit": "",
        })
    return tasks


def discover_single(image: str, task_id: str = "", problem: str = "") -> list[dict[str, Any]]:
    """Create a single task definition."""
    return [{
        "instance_id": task_id or _derive_task_id(image),
        "image": image,
        "problem_statement": problem,
        "repo": "",
        "base_commit": "",
    }]


def _derive_task_id(image: str) -> str:
    """Derive a task ID from a Docker image name.

    >>> _derive_task_id('swerebench/sweb.eval.x86_64.django__django-12345:latest')
    'django__django-12345'
    >>> _derive_task_id('swerebench/sweb.eval.x86_64.django:latest')
    'django'
    """
    # Strip the tag (everything after the last ':')
    if ":" in image:
        image = image.rsplit(":", 1)[0]
    # Take the last path component
    parts = image.split("/")
    last = parts[-1]
    # Remove common swe-rebench prefixes
    for prefix in ("sweb.eval.x86_64.", "sweb.eval.arm64.", "sweb.eval.", "sweb."):
        if last.startswith(prefix):
            last = last[len(prefix):]
            break
    return last or "unknown"


def _read_text_file(path: Path) -> str:
    """Read a text file, trying UTF-8 first then UTF-16 (Windows)."""
    for encoding in ("utf-8", "utf-16", "utf-16-le", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ── CLI ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover SWE-Rebench tasks and generate a tasks JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--out", default="swe-bench-tasks.json",
        help="Output JSON file (default: swe-bench-tasks.json)",
    )
    parser.add_argument("--sample", type=int, default=0, help="Limit to first N tasks (0=all)")
    parser.add_argument("--bench-root", default=None,
                        help="Path to agent-test-bench checkout")
    parser.add_argument("--images", default=None,
                        help="File with Docker images (one per line)")
    parser.add_argument("--image", default=None,
                        help="Single Docker image (use with --task-id, --problem)")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--problem", default=None)

    args = parser.parse_args()

    tasks: list[dict[str, Any]] = []

    if args.image:
        tasks = discover_single(args.image, args.task_id or "", args.problem or "")
    elif args.images:
        tasks = discover_from_images(Path(args.images))
    else:
        # Try agent-test-bench first, then HuggingFace
        bench_root = Path(args.bench_root) if args.bench_root else Path(
            os.getenv(DEFAULT_BENCH_ROOT_ENV, str(DEFAULT_BENCH_ROOT))
        )
        try:
            tasks = discover_from_agent_test_bench(bench_root, sample=args.sample)
        except (FileNotFoundError, ImportError) as exc:
            _log(f"[warn] Cannot load from agent-test-bench: {exc}")
            _log("[warn] Trying direct HuggingFace download...")
            try:
                tasks = _load_from_huggingface(sample=args.sample)
            except ImportError as exc2:
                _log(f"[error] {exc2}")
                _log("[error] Cannot discover tasks. Options:")
                _log("[error]   1. pip install datasets  (download from HuggingFace)")
                _log("[error]   2. --images images.txt    (provide Docker image list)")
                _log("[error]   3. --image <img> --task-id <id> --problem <text>")
                sys.exit(1)

    if not tasks:
        _log("No tasks discovered.")
        sys.exit(1)

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _log(f"Wrote {len(tasks)} tasks to {out_path}")

    # Print summary
    print(f"\nDiscovered {len(tasks)} tasks → {out_path}")
    for i, t in enumerate(tasks[:5]):
        iid = t.get("instance_id", "?")
        img = t.get("image", "?")
        prob = t.get("problem_statement", "")
        print(f"  [{i+1}] {iid}")
        print(f"       image: {img}")
        if prob:
            print(f"       problem: {prob[:100]}...")
    if len(tasks) > 5:
        print(f"  ... and {len(tasks) - 5} more")


if __name__ == "__main__":
    main()
