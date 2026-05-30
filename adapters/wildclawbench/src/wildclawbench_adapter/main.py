"""Generate Harbor tasks for WildClawBench."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wildclawbench_adapter.adapter import (  # noqa: PLC0415
        DEFAULT_BASE_IMAGE,
        DEFAULT_BASE_PLATFORM,
        DEFAULT_SOURCE_DIR,
        HARBOR_ROOT,
        WildClawBenchAdapter,
    )
else:
    from .adapter import (
        DEFAULT_BASE_IMAGE,
        DEFAULT_BASE_PLATFORM,
        DEFAULT_SOURCE_DIR,
        HARBOR_ROOT,
        WildClawBenchAdapter,
    )

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _default_output_dir() -> Path:
    return HARBOR_ROOT / "datasets" / "wildclawbench"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Harbor tasks for WildClawBench",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="WildClawBench repository root containing tasks/ and skills/",
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        help="Prepared WildClawBench workspace directory. Defaults to <source-dir>/workspace.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="Directory to write generated Harbor tasks",
    )
    parser.add_argument(
        "--limit",
        "--num-tasks",
        type=int,
        default=None,
        help="Generate only the first N selected tasks",
    )
    parser.add_argument(
        "--task-ids",
        nargs="+",
        default=None,
        help="Only generate these WildClawBench source IDs or Harbor local task IDs",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing generated task directories",
    )
    parser.add_argument(
        "--base-image",
        default=DEFAULT_BASE_IMAGE,
        help="Docker image used as the generated task base image",
    )
    parser.add_argument(
        "--base-platform",
        default=DEFAULT_BASE_PLATFORM,
        help="Docker platform for the generated task base image. Use an empty string to omit.",
    )
    parser.add_argument(
        "--link-assets",
        action="store_true",
        help=(
            "Hardlink workspace and gt files instead of copying them. This avoids "
            "duplicating large WildClawBench assets, but requires output-dir and "
            "workspace-dir to be on the same filesystem."
        ),
    )
    parser.add_argument(
        "--strict-assets",
        dest="strict_assets",
        action="store_true",
        default=True,
        help="Fail if a task's prepared workspace exec/ directory is missing",
    )
    parser.add_argument(
        "--no-strict-assets",
        dest="strict_assets",
        action="store_false",
        help="Allow missing workspace exec/ directories and generate empty workspaces",
    )
    parser.add_argument(
        "--org",
        default="wildclawbench",
        help="Harbor task package organization prefix",
    )
    parser.add_argument(
        "--verifier-model",
        default="glm-5.1",
        help="Default MODEL_NAME for generated verifier env",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Harbor Task model validation after each generated task",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workspace_dir = args.workspace_dir or args.source_dir / "workspace"
    logger.info("=== Starting WildClawBench Adapter ===")
    logger.info("Source directory: %s", args.source_dir.resolve())
    logger.info("Workspace directory: %s", workspace_dir.resolve())
    logger.info("Output directory: %s", args.output_dir.resolve())

    adapter = WildClawBenchAdapter(
        output_dir=args.output_dir,
        source_dir=args.source_dir,
        workspace_dir=workspace_dir,
        limit=args.limit,
        overwrite=args.overwrite,
        task_ids=args.task_ids,
        base_image=args.base_image,
        base_platform=args.base_platform,
        link_assets=args.link_assets,
        strict_assets=args.strict_assets,
        org=args.org,
        verifier_model=args.verifier_model,
        validate=not args.no_validate,
    )
    logger.info("Loaded %d WildClawBench task(s)", len(adapter.tasks))
    adapter.run()
    logger.info("Generated tasks in: %s", args.output_dir)


if __name__ == "__main__":
    main()
