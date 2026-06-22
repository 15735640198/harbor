"""CLI for importing LiveClawBench's native Harbor tasks."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from liveclawbench_adapter.adapter import (  # noqa: PLC0415
        DEFAULT_SOURCE_DIR,
        HARBOR_ROOT,
        LiveClawBenchAdapter,
    )
else:
    from .adapter import DEFAULT_SOURCE_DIR, HARBOR_ROOT, LiveClawBenchAdapter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import LiveClawBench's native Harbor task directories",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="LiveClawBench repository root containing tasks/",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HARBOR_ROOT / "datasets" / "liveclawbench",
        help="Directory to write generated Harbor tasks",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Import only the first N tasks"
    )
    parser.add_argument(
        "--task-ids", nargs="+", default=None, help="Import only these task IDs"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing generated task directories",
    )
    parser.add_argument(
        "--org",
        default="mosi-ai",
        help="Registry organization for generated task names",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Harbor Task validation after copying",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    adapter = LiveClawBenchAdapter(
        output_dir=args.output_dir,
        source_dir=args.source_dir,
        limit=args.limit,
        overwrite=args.overwrite,
        task_ids=args.task_ids,
        org=args.org,
        validate=not args.no_validate,
    )
    adapter.run()
    print(
        f"Imported {len(adapter._select_tasks())} LiveClawBench task(s) into {args.output_dir}"
    )


if __name__ == "__main__":
    main()
