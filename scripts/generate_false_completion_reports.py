#!/usr/bin/env python3
"""Generate heuristic false-completion reports for Harbor job trajectories."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from classify_final_message_completion import (  # noqa: E402
    CompletionClassification,
    classify_message,
)


@dataclass(frozen=True)
class JobTarget:
    job_dir: Path
    trial_dir: Path
    trajectory_path: Path
    verifier_dir: Path
    step_name: str | None


@dataclass(frozen=True)
class FinalAgentMessage:
    message: str
    step_id: int | None
    step_index: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate false-completion-result.json reports for one Harbor job "
            "folder or a folder containing Harbor jobs."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "Harbor job folder, folder of jobs, or an agent/trajectory.json file. "
            "The script searches for agent/trajectory.json files underneath it."
        ),
    )
    parser.add_argument(
        "--success-threshold",
        type=float,
        default=1.0,
        help="Minimum reward counted as task success.",
    )
    parser.add_argument(
        "--output-name",
        default="false-completion-result.json",
        help="Filename to write under each matching verifier directory.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip targets where the destination report already exists.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many discovered trajectories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovered targets without writing reports.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed target instead of continuing the batch.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


def discover_targets(input_path: Path) -> list[JobTarget]:
    if input_path.is_file():
        target = target_from_trajectory(input_path)
        return [target] if target is not None else []

    candidates = sorted(
        path
        for path in input_path.rglob("trajectory.json")
        if path.parent.name == "agent"
    )
    return dedupe_targets(candidates)


def target_from_trajectory(path: Path) -> JobTarget | None:
    if path.name != "trajectory.json" or path.parent.name != "agent":
        return None

    trajectory_path = path.resolve()
    agent_dir = trajectory_path.parent

    if agent_dir.parent.parent.name == "steps":
        step_dir = agent_dir.parent
        trial_dir = step_dir.parent.parent
        verifier_dir = step_dir / "verifier"
        step_name = step_dir.name
    else:
        trial_dir = agent_dir.parent
        verifier_dir = trial_dir / "verifier"
        step_name = None

    return JobTarget(
        job_dir=trial_dir.parent,
        trial_dir=trial_dir,
        trajectory_path=trajectory_path,
        verifier_dir=verifier_dir,
        step_name=step_name,
    )


def dedupe_targets(paths: list[Path]) -> list[JobTarget]:
    """Prefer step-local trajectories over root agent trajectories for each trial."""
    root_targets_by_trial: dict[Path, JobTarget] = {}
    step_targets_by_trial: dict[Path, list[JobTarget]] = {}

    for path in paths:
        target = target_from_trajectory(path)
        if target is None:
            continue
        if target.step_name is None:
            root_targets_by_trial[target.trial_dir] = target
        else:
            step_targets_by_trial.setdefault(target.trial_dir, []).append(target)

    targets: list[JobTarget] = []
    for trial_dir in sorted(set(root_targets_by_trial) | set(step_targets_by_trial)):
        step_targets = step_targets_by_trial.get(trial_dir)
        if step_targets:
            targets.extend(
                sorted(
                    step_targets,
                    key=lambda target: (
                        target.step_name or "",
                        target.trajectory_path.as_posix(),
                    ),
                )
            )
        elif root_target := root_targets_by_trial.get(trial_dir):
            targets.append(root_target)

    return targets


def load_reward(trial_dir: Path) -> float | None:
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        return None
    try:
        data = json.loads(result_path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    verifier_result = data.get("verifier_result")
    if not isinstance(verifier_result, dict):
        return None
    rewards = verifier_result.get("rewards")
    if not isinstance(rewards, dict):
        return None
    reward = rewards.get("reward")
    try:
        return float(reward)
    except (TypeError, ValueError):
        return None


def load_final_agent_message(trajectory_path: Path) -> FinalAgentMessage | None:
    data = json.loads(trajectory_path.read_text(errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("trajectory root must be an object")
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise ValueError("trajectory steps must be an array")

    for index in range(len(steps) - 1, -1, -1):
        step = steps[index]
        if not isinstance(step, dict) or step.get("source") != "agent":
            continue
        message = content_to_text(step.get("message")).strip()
        if not message:
            continue
        step_id = step.get("step_id")
        return FinalAgentMessage(
            message=message,
            step_id=step_id if isinstance(step_id, int) else None,
            step_index=index,
        )
    return None


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def build_report(
    *,
    target: JobTarget,
    final_message: FinalAgentMessage | None,
    reward: float | None,
    success_threshold: float,
    classification: CompletionClassification | None,
) -> list[dict[str, Any]]:
    if (
        reward is None
        or reward >= success_threshold
        or final_message is None
        or classification is None
        or classification.classification != "success"
    ):
        return []

    claim_excerpt = compact_text(final_message.message, max_chars=500)
    return [
        {
            "category": "false_completion",
            "severity": "high",
            "confidence": classification.confidence,
            "summary": (
                "Agent claimed task completion even though the verifier reward "
                "was below the success threshold."
            ),
            "contradicting_agent_claim": claim_excerpt,
            "prior_evidence": [
                f"Trial reward {reward:g} is below success threshold {success_threshold:g}."
            ],
            "location": {
                "claim_event_index": final_message.step_index,
                "evidence_event_indices": [],
            },
            "rationale": (
                f"The final agent message matched {classification.matched_pattern!r} "
                "as an explicit completion claim, but Harbor classified the trial "
                "as failed from reward and threshold."
            ),
            "extra": {
                "reward": reward,
                "success_threshold": success_threshold,
                "matched_pattern": classification.matched_pattern,
                "final_step_id": final_message.step_id,
                "step_name": target.step_name,
            },
        }
    ]


def compact_text(text: str, *, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3]}..."


def process_target(
    target: JobTarget,
    *,
    output_name: str,
    success_threshold: float,
    skip_existing: bool,
    index: int,
    total: int,
) -> str:
    destination = target.verifier_dir / output_name
    if skip_existing and destination.exists():
        print(f"[{index}/{total}] skip existing: {destination}", flush=True)
        return "skipped"

    reward = load_reward(target.trial_dir)
    final_message = load_final_agent_message(target.trajectory_path)
    classification = (
        classify_message(final_message.message) if final_message is not None else None
    )
    report = build_report(
        target=target,
        final_message=final_message,
        reward=reward,
        success_threshold=success_threshold,
        classification=classification,
    )

    target.verifier_dir.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    status = "generated"
    finding_label = "false_completion" if report else "empty"
    reward_label = "missing" if reward is None else f"{reward:g}"
    classification_label = (
        "missing_final_message"
        if classification is None
        else classification.classification
    )
    print(
        f"[{index}/{total}] wrote: {destination} "
        f"({finding_label}, reward={reward_label}, final={classification_label})",
        flush=True,
    )
    return status


def validate_inputs(input_path: Path, *, success_threshold: float) -> None:
    if not input_path.exists():
        raise SystemExit(f"Input path does not exist: {input_path}")
    if not 0 <= success_threshold <= 1:
        raise SystemExit("--success-threshold must be between 0 and 1")


def main() -> int:
    args = parse_args()
    input_path = resolve_path(args.input)
    validate_inputs(input_path, success_threshold=args.success_threshold)

    targets = discover_targets(input_path)
    if args.limit is not None:
        targets = targets[: args.limit]

    if not targets:
        raise SystemExit(f"No agent/trajectory.json files found under: {input_path}")

    print(f"discovered {len(targets)} trajectory target(s)", flush=True)
    if args.dry_run:
        for target in targets:
            print(
                f"target: trajectory={target.trajectory_path} "
                f"verifier={target.verifier_dir}",
                flush=True,
            )
        return 0

    counts = {"generated": 0, "skipped": 0, "failed": 0}
    for index, target in enumerate(targets, start=1):
        try:
            status = process_target(
                target,
                output_name=args.output_name,
                success_threshold=args.success_threshold,
                skip_existing=args.skip_existing,
                index=index,
                total=len(targets),
            )
            counts[status] += 1
        except Exception as exc:
            counts["failed"] += 1
            print(
                f"[{index}/{len(targets)}] failed: {target.trajectory_path}",
                file=sys.stderr,
            )
            print(f"  {exc}", file=sys.stderr)
            if args.fail_fast:
                break

    print(
        "summary: "
        f"generated={counts['generated']} "
        f"skipped={counts['skipped']} "
        f"failed={counts['failed']}",
        flush=True,
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
