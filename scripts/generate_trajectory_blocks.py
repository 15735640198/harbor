#!/usr/bin/env python3
"""Generate thought/action/result block analysis for all trials in a Harbor job."""

from __future__ import annotations

import argparse
from pathlib import Path

from harbor.utils.trajectory_blocks import write_trajectory_block_analysis


def iter_trial_trajectory_paths(job_dir: Path):
    for trial_dir in sorted(job_dir.iterdir()):
        if not trial_dir.is_dir():
            continue
        trajectory_path = trial_dir / "agent" / "trajectory.json"
        if trajectory_path.exists():
            yield trial_dir, trajectory_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate paper-style thought/action/result block analysis files for "
            "each trial in a Harbor job directory."
        )
    )
    parser.add_argument(
        "job_dir",
        type=Path,
        help="Path to a Harbor job directory, e.g. jobs/2026-05-27__16-03-14",
    )
    parser.add_argument(
        "--output-name",
        default="tar_blocks",
        help="Output directory name under each trial's agent/ directory.",
    )
    parser.add_argument(
        "--ngram-size",
        type=int,
        default=4,
        help="Action-category n-gram length to write to action_ngrams.csv.",
    )
    parser.add_argument(
        "--include-copied-context",
        action="store_true",
        help="Include ATIF steps marked as copied context.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    job_dir = args.job_dir

    if not job_dir.exists():
        raise SystemExit(f"Job directory does not exist: {job_dir}")
    if not job_dir.is_dir():
        raise SystemExit(f"Expected a job directory, got file: {job_dir}")

    generated = 0
    for trial_dir, trajectory_path in iter_trial_trajectory_paths(job_dir):
        output_dir = trial_dir / "agent" / args.output_name
        write_trajectory_block_analysis(
            trajectory_path,
            output_dir,
            ngram_size=args.ngram_size,
            include_copied_context=args.include_copied_context,
        )
        generated += 1
        print(f"generated: {output_dir}")

    if generated == 0:
        raise SystemExit(f"No trial trajectories found under: {job_dir}")

    print(f"Generated trajectory block analysis for {generated} trial(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
