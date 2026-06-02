#!/usr/bin/env python3
"""Summarize thought/action/result block statistics across Harbor jobs."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable, Iterator

from harbor.models.trajectories import Trajectory
from harbor.utils.trajectory_blocks import (
    TrajectoryBlock,
    action_ngrams,
    write_trajectory_block_analysis,
)


@dataclass
class TrialSummary:
    job: str
    trial: str
    task_name: str
    source: str
    agent: str
    model: str
    reward: float | None
    outcome: str
    exception_type: str
    length: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    cost_usd: float
    categories: list[str]
    repeated_actions: int
    repeated_categories: int
    consecutive_generate_fix: int
    no_test_after_last_fix: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Harbor thought/action/result block outputs and summarize them "
            "with paper-style trajectory length, token, action category, n-gram, "
            "progress, and simple anti-pattern statistics."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Job directory or jobs root. Example: jobs or jobs/2026-05-27__16-03-14",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/trajectory_block_summary"),
        help="Directory to write summary outputs.",
    )
    parser.add_argument(
        "--blocks-dir-name",
        default="tar_blocks",
        help="Directory name under each trial's agent/ directory containing blocks.",
    )
    parser.add_argument(
        "--ngram-size",
        type=int,
        default=4,
        help="Action-category n-gram length for top sequence summaries.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=25,
        help="Number of top n-grams to include per aggregate group.",
    )
    parser.add_argument(
        "--progress-bins",
        type=int,
        default=5,
        help="Number of normalized trajectory progress bins.",
    )
    parser.add_argument(
        "--no-generate-missing",
        action="store_true",
        help="Do not generate missing tar_blocks from agent/trajectory.json.",
    )
    parser.add_argument(
        "--regenerate-blocks",
        action="store_true",
        help="Regenerate tar_blocks from agent/trajectory.json before summarizing.",
    )
    parser.add_argument(
        "--include-copied-context",
        action="store_true",
        help="Include ATIF steps marked as copied context when generating missing blocks.",
    )
    parser.add_argument(
        "--combine-retrieve",
        action="store_true",
        help="Temporarily combine Explore and Search categories into Retrieve.",
    )
    parser.add_argument(
        "--success-threshold",
        type=float,
        default=1.0,
        help="Minimum reward value counted as success.",
    )
    parser.add_argument(
        "--errors-as-failures",
        action="store_true",
        help="Count exception trials as failures when block data exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.ngram_size < 1:
        raise SystemExit("--ngram-size must be at least 1")
    if args.progress_bins < 1:
        raise SystemExit("--progress-bins must be at least 1")
    if args.no_generate_missing and args.regenerate_blocks:
        raise SystemExit(
            "--no-generate-missing and --regenerate-blocks are mutually exclusive"
        )

    job_dirs = discover_job_dirs(args.paths)
    if not job_dirs:
        raise SystemExit("No Harbor job directories found.")

    trial_summaries: list[TrialSummary] = []
    category_rows: list[dict[str, Any]] = []
    progress_counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    ngram_counts: dict[tuple[str, str], Counter[tuple[str, ...]]] = defaultdict(Counter)

    for job_dir in job_dirs:
        for trial_dir in iter_trial_dirs(job_dir):
            blocks = load_or_generate_blocks(
                trial_dir,
                args.blocks_dir_name,
                generate_missing=not args.no_generate_missing,
                regenerate=args.regenerate_blocks,
                ngram_size=args.ngram_size,
                include_copied_context=args.include_copied_context,
                combine_retrieve=args.combine_retrieve,
            )
            if not blocks:
                continue

            metadata = load_trial_metadata(trial_dir)
            metrics = load_trajectory_metrics(trial_dir / "agent" / "trajectory.json")
            categories = [block.action_category for block in blocks]
            outcome = classify_outcome(
                metadata,
                success_threshold=args.success_threshold,
                errors_as_failures=args.errors_as_failures,
            )
            trial_summary = TrialSummary(
                job=job_dir.name,
                trial=trial_dir.name,
                task_name=str(metadata.get("task_name") or ""),
                source=str(metadata.get("source") or ""),
                agent=get_agent_name(metadata),
                model=get_model_name(metadata),
                reward=extract_reward(metadata),
                outcome=outcome,
                exception_type=get_exception_type(metadata),
                length=len(blocks),
                prompt_tokens=metrics["prompt_tokens"],
                completion_tokens=metrics["completion_tokens"],
                cached_tokens=metrics["cached_tokens"],
                total_tokens=metrics["prompt_tokens"] + metrics["completion_tokens"],
                cost_usd=metrics["cost_usd"],
                categories=categories,
                repeated_actions=count_repeated_actions(blocks),
                repeated_categories=count_repeated_categories(categories),
                consecutive_generate_fix=count_consecutive_category(
                    categories, "Generate Fix"
                ),
                no_test_after_last_fix=no_test_after_last_fix(categories),
            )
            trial_summaries.append(trial_summary)

            cat_counts = Counter(categories)
            for category, count in sorted(cat_counts.items()):
                category_rows.append(
                    {
                        "job": job_dir.name,
                        "trial": trial_dir.name,
                        "outcome": outcome,
                        "category": category,
                        "count": count,
                        "percent": count / len(blocks) if blocks else 0.0,
                    }
                )

            add_progress_counts(progress_counts, job_dir.name, outcome, blocks)
            ngram_counts[(job_dir.name, outcome)].update(
                action_ngrams(blocks, args.ngram_size)
            )
            ngram_counts[(job_dir.name, "all")].update(
                action_ngrams(blocks, args.ngram_size)
            )
            ngram_counts[("ALL", outcome)].update(
                action_ngrams(blocks, args.ngram_size)
            )
            ngram_counts[("ALL", "all")].update(action_ngrams(blocks, args.ngram_size))

    if not trial_summaries:
        raise SystemExit(
            "No block data found. Generate blocks first or omit --no-generate-missing."
        )

    args.out.mkdir(parents=True, exist_ok=True)
    write_trial_summaries(args.out / "trial_summary.csv", trial_summaries)
    write_job_summaries(args.out / "job_summary.csv", trial_summaries)
    write_outcome_summaries(args.out / "outcome_summary.csv", trial_summaries)
    write_category_summary(args.out / "action_category_summary.csv", trial_summaries)
    write_category_rows(args.out / "trial_action_categories.csv", category_rows)
    write_progress_summary(
        args.out / "action_progress_summary.csv",
        progress_counts,
        args.progress_bins,
    )
    write_ngram_summary(args.out / "top_action_ngrams.csv", ngram_counts, args.top_k)
    write_antipattern_summary(args.out / "antipattern_summary.csv", trial_summaries)
    write_markdown_summary(
        args.out / "summary.md",
        trial_summaries,
        ngram_counts,
        args.top_k,
        args.ngram_size,
    )

    print(f"Summarized {len(trial_summaries)} trial(s) from {len(job_dirs)} job(s).")
    print(f"Wrote summary outputs to {args.out}")
    return 0


def discover_job_dirs(paths: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if not path.exists():
            raise SystemExit(f"Path does not exist: {path}")
        candidates = [path] if is_job_dir(path) else []
        if path.is_dir():
            candidates.extend(
                child for child in sorted(path.iterdir()) if is_job_dir(child)
            )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                discovered.append(candidate)
    return discovered


def is_job_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        (child / "agent" / "trajectory.json").exists() for child in path.iterdir()
    )


def iter_trial_dirs(job_dir: Path) -> Iterator[Path]:
    for trial_dir in sorted(job_dir.iterdir()):
        if (trial_dir / "agent" / "trajectory.json").exists():
            yield trial_dir


def load_or_generate_blocks(
    trial_dir: Path,
    blocks_dir_name: str,
    *,
    generate_missing: bool,
    regenerate: bool,
    ngram_size: int,
    include_copied_context: bool,
    combine_retrieve: bool,
) -> list[TrajectoryBlock]:
    blocks_path = trial_dir / "agent" / blocks_dir_name / "blocks.jsonl"
    trajectory_path = trial_dir / "agent" / "trajectory.json"
    if regenerate or not blocks_path.exists():
        if not generate_missing:
            return []
        write_trajectory_block_analysis(
            trajectory_path,
            blocks_path.parent,
            ngram_size=ngram_size,
            include_copied_context=include_copied_context,
            combine_retrieve=combine_retrieve,
        )
    blocks = []
    # Split JSONL on the record delimiter only. str.splitlines() also splits on
    # Unicode separators that can appear inside PDF-derived strings.
    for line in blocks_path.read_bytes().split(b"\n"):
        line = line.rstrip(b"\r")
        if line.strip():
            block = TrajectoryBlock.model_validate_json(line)
            if combine_retrieve and block.action_category in {"Explore", "Search"}:
                block = block.model_copy(update={"action_category": "Retrieve"})
            blocks.append(block)
    return blocks


def load_trial_metadata(trial_dir: Path) -> dict[str, Any]:
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        return {}
    try:
        data = json.loads(result_path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_trajectory_metrics(trajectory_path: Path) -> dict[str, int | float]:
    trajectory = Trajectory.model_validate_json(trajectory_path.read_text())
    prompt_tokens = completion_tokens = cached_tokens = 0
    cost_usd = 0.0

    if trajectory.final_metrics:
        prompt_tokens = trajectory.final_metrics.total_prompt_tokens or 0
        completion_tokens = trajectory.final_metrics.total_completion_tokens or 0
        cached_tokens = trajectory.final_metrics.total_cached_tokens or 0
        cost_usd = trajectory.final_metrics.total_cost_usd or 0.0

    if prompt_tokens == 0 and completion_tokens == 0 and cost_usd == 0.0:
        for step in trajectory.steps:
            if step.metrics is None:
                continue
            prompt_tokens += step.metrics.prompt_tokens or 0
            completion_tokens += step.metrics.completion_tokens or 0
            cached_tokens += step.metrics.cached_tokens or 0
            cost_usd += step.metrics.cost_usd or 0.0

    return {
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "cached_tokens": int(cached_tokens),
        "cost_usd": float(cost_usd),
    }


def get_agent_name(metadata: dict[str, Any]) -> str:
    agent_info = metadata.get("agent_info")
    if isinstance(agent_info, dict) and agent_info.get("name"):
        return str(agent_info["name"])
    config = metadata.get("config")
    if isinstance(config, dict):
        agent = config.get("agent")
        if isinstance(agent, dict) and agent.get("name"):
            return str(agent["name"])
    return ""


def get_model_name(metadata: dict[str, Any]) -> str:
    agent_info = metadata.get("agent_info")
    if isinstance(agent_info, dict):
        model_info = agent_info.get("model_info")
        if isinstance(model_info, dict) and model_info.get("name"):
            return str(model_info["name"])
    config = metadata.get("config")
    if isinstance(config, dict):
        agent = config.get("agent")
        if isinstance(agent, dict) and agent.get("model_name"):
            return str(agent["model_name"])
    return ""


def extract_reward(metadata: dict[str, Any]) -> float | None:
    verifier_result = metadata.get("verifier_result")
    if not isinstance(verifier_result, dict):
        return None
    rewards = verifier_result.get("rewards")
    if not isinstance(rewards, dict):
        return None
    reward = rewards.get("reward")
    if reward is None:
        return None
    try:
        return float(reward)
    except (TypeError, ValueError):
        return None


def classify_outcome(
    metadata: dict[str, Any],
    *,
    success_threshold: float = 1.0,
    errors_as_failures: bool = False,
) -> str:
    if get_exception_type(metadata):
        return "failure" if errors_as_failures else "error"
    reward = extract_reward(metadata)
    if reward is not None:
        return "success" if reward >= success_threshold else "failure"
    return "unknown"


def get_exception_type(metadata: dict[str, Any]) -> str:
    exception_info = metadata.get("exception_info")
    if isinstance(exception_info, dict) and exception_info.get("exception_type"):
        return str(exception_info["exception_type"])
    return ""


def count_repeated_actions(blocks: list[TrajectoryBlock]) -> int:
    return sum(
        1
        for left, right in zip(blocks, blocks[1:])
        if left.action.strip() == right.action.strip()
    )


def count_repeated_categories(categories: list[str]) -> int:
    return sum(1 for left, right in zip(categories, categories[1:]) if left == right)


def count_consecutive_category(categories: list[str], category: str) -> int:
    return sum(
        1
        for left, right in zip(categories, categories[1:])
        if left == category and right == category
    )


def no_test_after_last_fix(categories: list[str]) -> bool:
    try:
        last_fix = (
            len(categories) - 1 - list(reversed(categories)).index("Generate Fix")
        )
    except ValueError:
        return False
    return "Run tests" not in categories[last_fix + 1 :]


def add_progress_counts(
    progress_counts: dict[tuple[str, str, str], Counter[str]],
    job: str,
    outcome: str,
    blocks: list[TrajectoryBlock],
) -> None:
    total = len(blocks)
    if total == 0:
        return
    for index, block in enumerate(blocks):
        progress_counts[(job, outcome, str(index / total))][block.action_category] += 1
        progress_counts[(job, "all", str(index / total))][block.action_category] += 1
        progress_counts[("ALL", outcome, str(index / total))][
            block.action_category
        ] += 1
        progress_counts[("ALL", "all", str(index / total))][block.action_category] += 1


def write_trial_summaries(path: Path, summaries: list[TrialSummary]) -> None:
    fieldnames = [
        "job",
        "trial",
        "task_name",
        "source",
        "agent",
        "model",
        "reward",
        "outcome",
        "exception_type",
        "length",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "total_tokens",
        "cost_usd",
        "repeated_actions",
        "repeated_categories",
        "consecutive_generate_fix",
        "no_test_after_last_fix",
        "category_sequence",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for summary in summaries:
        row = summary.__dict__.copy()
        row["category_sequence"] = " -> ".join(summary.categories)
        row.pop("categories")
        writer.writerow(row)
    path.write_text(output.getvalue())


def write_job_summaries(path: Path, summaries: list[TrialSummary]) -> None:
    rows = []
    for job, group in group_by(summaries, lambda item: item.job).items():
        rows.append(make_group_summary(job, group))
    rows.append(make_group_summary("ALL", summaries))
    write_dict_rows(path, rows)


def write_outcome_summaries(path: Path, summaries: list[TrialSummary]) -> None:
    rows = []
    for job, outcome, group in grouped_by_job_outcome(summaries):
        row = make_group_summary(job, group)
        row["outcome"] = outcome
        rows.append(row)
    write_dict_rows(path, rows)


def make_group_summary(name: str, group: list[TrialSummary]) -> dict[str, Any]:
    return {
        "job": name,
        "trials": len(group),
        "successes": sum(1 for item in group if item.outcome == "success"),
        "failures": sum(1 for item in group if item.outcome == "failure"),
        "errors": sum(1 for item in group if item.outcome == "error"),
        "unknown": sum(1 for item in group if item.outcome == "unknown"),
        "exceptions": sum(1 for item in group if item.exception_type),
        "total_blocks": sum(item.length for item in group),
        "mean_length": safe_mean(item.length for item in group),
        "median_length": safe_median(item.length for item in group),
        "mean_total_tokens": safe_mean(item.total_tokens for item in group),
        "median_total_tokens": safe_median(item.total_tokens for item in group),
        "total_cost_usd": sum(item.cost_usd for item in group),
        "mean_cost_usd": safe_mean(item.cost_usd for item in group),
    }


def write_category_summary(path: Path, summaries: list[TrialSummary]) -> None:
    rows = []
    for job, outcome, group in grouped_by_job_outcome(summaries):
        counts: Counter[str] = Counter()
        for summary in group:
            counts.update(summary.categories)
        total = sum(counts.values())
        for category, count in sorted(counts.items()):
            rows.append(
                {
                    "job": job,
                    "outcome": outcome,
                    "category": category,
                    "count": count,
                    "percent": count / total if total else 0.0,
                }
            )
    write_dict_rows(path, rows)


def write_category_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    write_dict_rows(path, rows)


def write_progress_summary(
    path: Path,
    progress_counts: dict[tuple[str, str, str], Counter[str]],
    progress_bins: int,
) -> None:
    binned: dict[tuple[str, str, int], Counter[str]] = defaultdict(Counter)
    for (job, outcome, progress_raw), counts in progress_counts.items():
        progress = float(progress_raw)
        bin_index = min(int(progress * progress_bins), progress_bins - 1)
        binned[(job, outcome, bin_index)].update(counts)

    rows = []
    for (job, outcome, bin_index), counts in sorted(binned.items()):
        total = sum(counts.values())
        start = int(100 * bin_index / progress_bins)
        end = int(100 * (bin_index + 1) / progress_bins)
        for category, count in sorted(counts.items()):
            rows.append(
                {
                    "job": job,
                    "outcome": outcome,
                    "progress_bin": f"{start}-{end}%",
                    "category": category,
                    "count": count,
                    "percent": count / total if total else 0.0,
                }
            )
    write_dict_rows(path, rows)


def write_ngram_summary(
    path: Path,
    ngram_counts: dict[tuple[str, str], Counter[tuple[str, ...]]],
    top_k: int,
) -> None:
    rows = []
    for (job, outcome), counts in sorted(ngram_counts.items()):
        for ngram, count in counts.most_common(top_k):
            rows.append(
                {
                    "job": job,
                    "outcome": outcome,
                    "ngram": " -> ".join(ngram),
                    "count": count,
                }
            )
    write_dict_rows(path, rows)


def write_antipattern_summary(path: Path, summaries: list[TrialSummary]) -> None:
    rows = []
    for job, outcome, group in grouped_by_job_outcome(summaries):
        rows.append(
            {
                "job": job,
                "outcome": outcome,
                "trials": len(group),
                "repeated_actions": sum(item.repeated_actions for item in group),
                "repeated_categories": sum(item.repeated_categories for item in group),
                "consecutive_generate_fix": sum(
                    item.consecutive_generate_fix for item in group
                ),
                "trials_with_no_test_after_last_fix": sum(
                    1 for item in group if item.no_test_after_last_fix
                ),
            }
        )
    write_dict_rows(path, rows)


def write_markdown_summary(
    path: Path,
    summaries: list[TrialSummary],
    ngram_counts: dict[tuple[str, str], Counter[tuple[str, ...]]],
    top_k: int,
    ngram_size: int,
) -> None:
    lines = [
        "# Trajectory Block Summary",
        "",
        "## Overall",
        "",
    ]
    overall = make_group_summary("ALL", summaries)
    lines.extend(
        [
            f"- Trials: {overall['trials']}",
            f"- Successes: {overall['successes']}",
            f"- Failures: {overall['failures']}",
            f"- Errors: {overall['errors']}",
            f"- Unknown outcomes: {overall['unknown']}",
            f"- Exceptions: {overall['exceptions']}",
            f"- Total blocks: {overall['total_blocks']}",
            f"- Mean trajectory length: {overall['mean_length']:.2f}",
            f"- Median trajectory length: {overall['median_length']:.2f}",
            f"- Mean total tokens: {overall['mean_total_tokens']:.2f}",
            f"- Median total tokens: {overall['median_total_tokens']:.2f}",
            f"- Total cost USD: {overall['total_cost_usd']:.6f}",
            "",
            "## Action Categories",
            "",
        ]
    )
    category_counts: Counter[str] = Counter()
    for summary in summaries:
        category_counts.update(summary.categories)
    total_categories = sum(category_counts.values())
    lines.append("| Category | Count | Percent |")
    lines.append("| --- | ---: | ---: |")
    for category, count in category_counts.most_common():
        percent = 100 * count / total_categories if total_categories else 0.0
        lines.append(f"| {category} | {count} | {percent:.2f}% |")

    lines.extend(["", f"## Top {ngram_size}-grams", ""])
    append_ngram_table(lines, ngram_counts[("ALL", "all")], top_k)

    for outcome in ("success", "failure"):
        title = outcome.capitalize()
        lines.extend(["", f"## {title} Top {ngram_size}-grams", ""])
        append_ngram_table(lines, ngram_counts[("ALL", outcome)], top_k)

    lines.extend(["", "## Anti-Patterns", ""])
    lines.append("| Metric | Count |")
    lines.append("| --- | ---: |")
    lines.append(
        f"| Repeated identical actions | {sum(s.repeated_actions for s in summaries)} |"
    )
    lines.append(
        f"| Repeated adjacent categories | {sum(s.repeated_categories for s in summaries)} |"
    )
    lines.append(
        "| Consecutive Generate Fix pairs | "
        f"{sum(s.consecutive_generate_fix for s in summaries)} |"
    )
    lines.append(
        "| Trials with no Run tests after last Generate Fix | "
        f"{sum(1 for s in summaries if s.no_test_after_last_fix)} |"
    )

    path.write_text("\n".join(lines) + "\n")


def append_ngram_table(
    lines: list[str],
    counts: Counter[tuple[str, ...]],
    top_k: int,
) -> None:
    lines.append("| N-gram | Count |")
    lines.append("| --- | ---: |")
    if not counts:
        lines.append("| _No matching trajectories_ | 0 |")
        return
    for ngram, count in counts.most_common(top_k):
        lines.append(f"| {' -> '.join(ngram)} | {count} |")


def grouped_by_job_outcome(
    summaries: list[TrialSummary],
) -> Iterator[tuple[str, str, list[TrialSummary]]]:
    groups: dict[tuple[str, str], list[TrialSummary]] = defaultdict(list)
    for summary in summaries:
        groups[(summary.job, summary.outcome)].append(summary)
        groups[(summary.job, "all")].append(summary)
        groups[("ALL", summary.outcome)].append(summary)
        groups[("ALL", "all")].append(summary)
    for (job, outcome), group in sorted(groups.items()):
        yield job, outcome, group


def group_by(
    items: Iterable[TrialSummary],
    key_fn: Callable[[TrialSummary], str],
) -> dict[str, list[TrialSummary]]:
    groups: dict[str, list[TrialSummary]] = defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item)
    return groups


def safe_mean(values: Iterable[int | float]) -> float:
    vals = list(values)
    return float(mean(vals)) if vals else 0.0


def safe_median(values: Iterable[int | float]) -> float:
    vals = list(values)
    return float(median(vals)) if vals else 0.0


def write_dict_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue())


if __name__ == "__main__":
    raise SystemExit(main())
