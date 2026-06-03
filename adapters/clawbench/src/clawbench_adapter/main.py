"""Generate Harbor tasks for ClawBench."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

try:
    from clawbench_adapter.adapter import (
        DEFAULT_BASE_IMAGE,
        DEFAULT_MANIFEST,
        DEFAULT_SOURCE_DIR,
        DEFAULT_TASKS_ROOT,
        HARBOR_ROOT,
        ClawBenchAdapter,
    )
except ImportError:  # pragma: no cover - supports direct source execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from clawbench_adapter.adapter import (
        DEFAULT_BASE_IMAGE,
        DEFAULT_MANIFEST,
        DEFAULT_SOURCE_DIR,
        DEFAULT_TASKS_ROOT,
        HARBOR_ROOT,
        ClawBenchAdapter,
    )


def default_output_dir() -> Path:
    return HARBOR_ROOT / "datasets" / "clawbench"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Harbor tasks for ClawBench")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--tasks-root", default=DEFAULT_TASKS_ROOT)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--task-ids", nargs="*", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--link-assets", action="store_true")
    parser.add_argument("--base-image", default=DEFAULT_BASE_IMAGE)
    parser.add_argument("--org", default="clawbench")
    parser.add_argument("--judge-model", default="claude-sonnet-4-6")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    adapter = ClawBenchAdapter(
        output_dir=args.output_dir,
        source_dir=args.source_dir,
        tasks_root=args.tasks_root,
        manifest=args.manifest,
        limit=args.limit,
        overwrite=args.overwrite,
        task_ids=args.task_ids,
        base_image=args.base_image,
        link_assets=args.link_assets,
        org=args.org,
        judge_model=args.judge_model,
        validate=not args.no_validate,
    )
    adapter.run()


if __name__ == "__main__":
    main()
