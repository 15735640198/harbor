#!/usr/bin/env python3
"""Preprocess an ATIF trajectory into a compact analysis packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harbor.utils.trajectory_preprocess import preprocess_trajectory_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an ATIF trajectory.json file into a compact processed JSON "
            "packet with task context, a chronological transcript, and summary "
            "counts."
        )
    )
    parser.add_argument(
        "trajectory",
        type=Path,
        help="Input ATIF trajectory JSON file.",
    )
    parser.add_argument(
        "--out",
        "--output",
        dest="output",
        type=Path,
        default=None,
        help=(
            "Output JSON file or directory. Defaults to the same directory as the "
            "input trajectory file."
        ),
    )
    parser.add_argument(
        "--max-result-chars",
        type=int,
        default=4000,
        help="Maximum characters kept in each compacted tool result.",
    )
    parser.add_argument(
        "--max-arguments-chars",
        type=int,
        default=2000,
        help="Maximum characters kept in each compacted invocation arguments field.",
    )
    parser.add_argument(
        "--max-message-chars",
        type=int,
        default=4000,
        help="Maximum characters kept for user/system/agent messages.",
    )
    parser.add_argument(
        "--include-copied-context",
        action="store_true",
        help="Include ATIF steps marked as copied context.",
    )
    parser.add_argument(
        "--include-status-basis",
        action="store_true",
        help="Include explanatory status_basis strings for inferred tool status.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.trajectory.exists():
        raise SystemExit(f"Trajectory file does not exist: {args.trajectory}")
    if not args.trajectory.is_file():
        raise SystemExit(f"Expected trajectory file, got directory: {args.trajectory}")

    packet = preprocess_trajectory_file(
        args.trajectory,
        max_result_chars=args.max_result_chars,
        max_arguments_chars=args.max_arguments_chars,
        max_message_chars=args.max_message_chars,
        include_copied_context=args.include_copied_context,
        include_status_basis=args.include_status_basis,
    )
    output = _resolve_output_path(args.trajectory, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(packet.to_json_dict(), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"wrote: {output}")
    return 0


def _resolve_output_path(trajectory_path: Path, output: Path | None) -> Path:
    filename = _default_output_filename(trajectory_path)
    if output is None:
        return trajectory_path.parent / filename
    if output.exists() and output.is_dir():
        return output / filename
    if output.suffix:
        return output
    return output / filename


def _default_output_filename(trajectory_path: Path) -> str:
    if trajectory_path.name == "trajectory.json":
        return "trajectory.processed.json"
    return f"{trajectory_path.stem}.processed.json"


if __name__ == "__main__":
    raise SystemExit(main())
