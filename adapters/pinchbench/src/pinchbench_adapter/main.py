"""Generate Harbor tasks for Pinchbench."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pinchbench_adapter.adapter import (  # noqa: PLC0415
        DEFAULT_SKILL_DIR,
        DEFAULT_SOURCE_DIR,
        HARBOR_ROOT,
        PinchbenchAdapter,
    )
else:
    from .adapter import (
        DEFAULT_SKILL_DIR,
        DEFAULT_SOURCE_DIR,
        HARBOR_ROOT,
        PinchbenchAdapter,
    )

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _default_output_dir() -> Path:
    return HARBOR_ROOT / "datasets" / "pinchbench"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Harbor tasks for Pinchbench",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Pinchbench repository root containing tasks/ and assets/",
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=DEFAULT_SKILL_DIR,
        help="pinchbench-to-harbor skill directory to stage into the harness",
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
        help="Only generate these Pinchbench source IDs or Harbor local task IDs",
    )
    parser.add_argument(
        "--core",
        action="store_true",
        help="Generate the Pinchbench manifest's core task subset",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing generated task directories",
    )
    parser.add_argument(
        "--harness",
        choices=["claude-code", "direct"],
        default="claude-code",
        help="Conversion backend. claude-code stages and uses the skill through Claude Code; direct runs the skill script locally.",
    )
    parser.add_argument(
        "--claude-bin",
        default="claude",
        help="Claude Code executable for --harness claude-code",
    )
    parser.add_argument(
        "--claude-model",
        default=None,
        help="Optional Claude model for the conversion harness",
    )
    parser.add_argument(
        "--claude-config-dir",
        type=Path,
        default=None,
        help="Claude Code config directory where the skill is staged",
    )
    parser.add_argument(
        "--conversion-timeout-sec",
        type=int,
        default=900,
        help="Per-task conversion timeout for the Claude Code harness",
    )
    parser.add_argument(
        "--keep-agent-workdirs",
        action="store_true",
        help="Keep Claude Code prompts/stdout/stderr under the output directory",
    )
    parser.add_argument(
        "--org",
        default="pinchbench",
        help="Harbor task package organization prefix",
    )
    parser.add_argument(
        "--judge-model",
        default="claude-haiku-4-5",
        help="Verifier MODEL_NAME for generated LLM judge tasks",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Harbor Task model validation after each generated task",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logger.info("=== Starting Pinchbench Adapter ===")
    logger.info("Source directory: %s", args.source_dir.resolve())
    logger.info("Output directory: %s", args.output_dir.resolve())
    logger.info("Harness: %s", args.harness)

    adapter = PinchbenchAdapter(
        output_dir=args.output_dir,
        source_dir=args.source_dir,
        skill_dir=args.skill_dir,
        harness=args.harness,
        limit=args.limit,
        overwrite=args.overwrite,
        task_ids=args.task_ids,
        core=args.core,
        org=args.org,
        judge_model=args.judge_model,
        claude_bin=args.claude_bin,
        claude_model=args.claude_model,
        claude_config_dir=args.claude_config_dir,
        conversion_timeout_sec=args.conversion_timeout_sec,
        keep_agent_workdirs=args.keep_agent_workdirs,
        validate=not args.no_validate,
    )
    logger.info("Loaded %d Pinchbench task(s)", len(adapter.tasks))
    adapter.run()
    logger.info("Generated tasks in: %s", args.output_dir)


if __name__ == "__main__":
    main()
