#!/usr/bin/env python3
"""Summarize Harbor hallucination-result.json reports."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ReportTarget:
    job_dir: Path
    trial_dir: Path
    trajectory_path: Path | None
    report_path: Path
    step_name: str | None

    @property
    def job(self) -> str:
        return self.job_dir.name

    @property
    def trial(self) -> str:
        return self.trial_dir.name


@dataclass(frozen=True)
class TrialMetadata:
    trial_name: str
    task_name: str
    source: str
    agent: str
    model: str
    reward: float | None
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class TrialSummary:
    target: ReportTarget
    metadata: TrialMetadata
    report_status: str
    finding_count: int
    step_count: int
    severity_counts: Counter[str]
    error: str


@dataclass(frozen=True)
class FindingRow:
    target: ReportTarget
    metadata: TrialMetadata
    finding_index: int
    finding: dict[str, Any]


@dataclass(frozen=True)
class SummaryData:
    job_dirs: list[Path]
    targets: list[ReportTarget]
    trial_summaries: list[TrialSummary]
    findings: list[FindingRow]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Harbor hallucination-result.json reports and write a "
            "deterministic Markdown summary plus CSV rollups."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="One or more Harbor job folders or folders containing Harbor jobs.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/hallucination_summary"),
        help="Directory to write summary.md, findings.csv, and rollup CSV files.",
    )
    parser.add_argument(
        "--report-name",
        default="hallucination-result.json",
        help="Hallucination report filename under verifier directories.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=25,
        help="Number of findings to include in the Markdown top findings table.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top_k < 1:
        raise SystemExit("--top-k must be at least 1")

    data = summarize_paths(args.paths, report_name=args.report_name)
    if not data.targets:
        raise SystemExit("No Harbor trajectory targets or hallucination reports found.")

    args.out.mkdir(parents=True, exist_ok=True)
    write_outputs(args.out, data, top_k=args.top_k)
    print(
        f"Summarized {len(data.trial_summaries)} target(s) from "
        f"{len(data.job_dirs)} job folder(s)."
    )
    print(f"Wrote summary outputs to {args.out}")
    return 0


def summarize_paths(paths: Iterable[Path], *, report_name: str) -> SummaryData:
    job_dirs = discover_job_dirs(paths)
    targets = discover_targets(job_dirs, report_name=report_name)

    trial_summaries: list[TrialSummary] = []
    findings: list[FindingRow] = []
    for target in targets:
        metadata = load_trial_metadata(target.trial_dir)
        status, report_items, error = load_report_items(target.report_path)
        severity_counts: Counter[str] = Counter()

        if status == "ok":
            for index, item in enumerate(report_items):
                if isinstance(item, dict):
                    severity_counts[str(item.get("severity") or "")] += 1
                    findings.append(
                        FindingRow(
                            target=target,
                            metadata=metadata,
                            finding_index=index,
                            finding=item,
                        )
                    )

        trial_summaries.append(
            TrialSummary(
                target=target,
                metadata=metadata,
                report_status=status,
                finding_count=len(report_items) if status == "ok" else 0,
                step_count=load_step_count(target.trajectory_path),
                severity_counts=severity_counts,
                error=error,
            )
        )

    return SummaryData(
        job_dirs=job_dirs,
        targets=targets,
        trial_summaries=trial_summaries,
        findings=findings,
    )


def discover_job_dirs(paths: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if not path.exists():
            raise SystemExit(f"Path does not exist: {path}")

        candidates: list[Path] = []
        if is_job_dir(path):
            candidates.append(path)
        if path.is_dir():
            candidates.extend(
                child for child in sorted(path.iterdir()) if is_job_dir(child)
            )

        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                discovered.append(candidate.resolve())
    return discovered


def is_job_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        child.is_dir()
        and (
            (child / "agent" / "trajectory.json").exists()
            or any(child.glob("steps/*/agent/trajectory.json"))
            or (child / "verifier").exists()
            or (child / "steps").exists()
        )
        for child in path.iterdir()
    )


def discover_targets(
    job_dirs: Iterable[Path], *, report_name: str
) -> list[ReportTarget]:
    targets_by_key: dict[tuple[Path, str | None], ReportTarget] = {}
    for job_dir in job_dirs:
        for target in discover_trajectory_targets(job_dir, report_name=report_name):
            targets_by_key[(target.trial_dir, target.step_name)] = target
        for target in discover_orphan_report_targets(job_dir, report_name=report_name):
            targets_by_key.setdefault((target.trial_dir, target.step_name), target)

    return sorted(
        targets_by_key.values(),
        key=lambda target: (
            target.job_dir.as_posix(),
            target.trial_dir.name,
            target.step_name or "",
            target.report_path.as_posix(),
        ),
    )


def discover_trajectory_targets(
    job_dir: Path, *, report_name: str
) -> list[ReportTarget]:
    root_targets_by_trial: dict[Path, ReportTarget] = {}
    step_targets_by_trial: dict[Path, list[ReportTarget]] = {}

    for trajectory_path in sorted(job_dir.rglob("trajectory.json")):
        if trajectory_path.parent.name != "agent":
            continue
        target = target_from_trajectory(
            job_dir, trajectory_path, report_name=report_name
        )
        if target is None:
            continue
        if target.step_name is None:
            root_targets_by_trial[target.trial_dir] = target
        else:
            step_targets_by_trial.setdefault(target.trial_dir, []).append(target)

    targets: list[ReportTarget] = []
    for trial_dir in sorted(set(root_targets_by_trial) | set(step_targets_by_trial)):
        step_targets = step_targets_by_trial.get(trial_dir)
        if step_targets:
            targets.extend(
                sorted(step_targets, key=lambda target: target.step_name or "")
            )
        elif root_target := root_targets_by_trial.get(trial_dir):
            targets.append(root_target)
    return targets


def target_from_trajectory(
    job_dir: Path, trajectory_path: Path, *, report_name: str
) -> ReportTarget | None:
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

    if trial_dir.parent != job_dir:
        return None

    return ReportTarget(
        job_dir=job_dir,
        trial_dir=trial_dir,
        trajectory_path=trajectory_path,
        report_path=verifier_dir / report_name,
        step_name=step_name,
    )


def discover_orphan_report_targets(
    job_dir: Path, *, report_name: str
) -> list[ReportTarget]:
    targets: list[ReportTarget] = []
    for report_path in sorted(job_dir.rglob(report_name)):
        if report_path.parent.name != "verifier":
            continue
        target = target_from_report(job_dir, report_path)
        if target is not None:
            targets.append(target)
    return targets


def target_from_report(job_dir: Path, report_path: Path) -> ReportTarget | None:
    verifier_dir = report_path.parent
    if verifier_dir.parent.parent.name == "steps":
        step_dir = verifier_dir.parent
        trial_dir = step_dir.parent.parent
        trajectory_path = step_dir / "agent" / "trajectory.json"
        step_name = step_dir.name
    else:
        trial_dir = verifier_dir.parent
        trajectory_path = trial_dir / "agent" / "trajectory.json"
        step_name = None

    if trial_dir.parent != job_dir:
        return None

    return ReportTarget(
        job_dir=job_dir,
        trial_dir=trial_dir,
        trajectory_path=trajectory_path if trajectory_path.exists() else None,
        report_path=report_path,
        step_name=step_name,
    )


def load_report_items(report_path: Path) -> tuple[str, list[Any], str]:
    if not report_path.exists():
        return "missing", [], ""
    try:
        data = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        return "invalid", [], f"JSON parse error: {exc}"
    if not isinstance(data, list):
        return "invalid", [], f"expected array, got {type(data).__name__}"
    return "ok", data, ""


def load_step_count(trajectory_path: Path | None) -> int:
    if trajectory_path is None or not trajectory_path.exists():
        return 0
    try:
        data = json.loads(trajectory_path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    steps = data.get("steps")
    return len(steps) if isinstance(steps, list) else 0


def load_trial_metadata(trial_dir: Path) -> TrialMetadata:
    data: dict[str, Any] = {}
    result_path = trial_dir / "result.json"
    if result_path.exists():
        try:
            parsed = json.loads(result_path.read_text())
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            data = parsed

    agent_info = (
        data.get("agent_info") if isinstance(data.get("agent_info"), dict) else {}
    )
    model_info = (
        agent_info.get("model_info")
        if isinstance(agent_info.get("model_info"), dict)
        else {}
    )
    provider = str(model_info.get("provider") or "")
    model = str(model_info.get("name") or "")
    model_name = "/".join(part for part in (provider, model) if part)

    return TrialMetadata(
        trial_name=str(data.get("trial_name") or trial_dir.name),
        task_name=str(data.get("task_name") or ""),
        source=str(data.get("source") or ""),
        agent=str(agent_info.get("name") or ""),
        model=model_name,
        reward=extract_reward(data),
        started_at=str(data.get("started_at") or ""),
        finished_at=str(data.get("finished_at") or ""),
    )


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


def reward_bucket(reward: float | None) -> str:
    if reward is None:
        return "missing"
    if reward >= 1.0:
        return "1.0"
    if reward >= 0.9:
        return "0.9-<1.0"
    if reward >= 0.75:
        return "0.75-<0.9"
    if reward >= 0.5:
        return "0.5-<0.75"
    return "<0.5"


def write_outputs(out_dir: Path, data: SummaryData, *, top_k: int) -> None:
    write_trial_summary(out_dir / "trial_summary.csv", data.trial_summaries)
    write_findings(out_dir / "findings.csv", data.findings)
    write_aggregate_summary(out_dir / "aggregate_summary.csv", data)
    write_markdown_summary(out_dir / "summary.md", data, top_k=top_k)


def write_trial_summary(path: Path, summaries: list[TrialSummary]) -> None:
    fieldnames = [
        "job",
        "trial",
        "step",
        "task_name",
        "source",
        "agent",
        "model",
        "reward",
        "reward_bucket",
        "started_at",
        "finished_at",
        "report_status",
        "finding_count",
        "step_count",
        "hallucination_rate",
        "high_count",
        "medium_count",
        "low_count",
        "report_path",
        "trajectory_path",
        "error",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for summary in summaries:
        writer.writerow(trial_summary_row(summary))
    path.write_text(output.getvalue())


def trial_summary_row(summary: TrialSummary) -> dict[str, Any]:
    metadata = summary.metadata
    target = summary.target
    return {
        "job": target.job,
        "trial": metadata.trial_name or target.trial,
        "step": target.step_name or "",
        "task_name": metadata.task_name,
        "source": metadata.source,
        "agent": metadata.agent,
        "model": metadata.model,
        "reward": "" if metadata.reward is None else metadata.reward,
        "reward_bucket": reward_bucket(metadata.reward),
        "started_at": metadata.started_at,
        "finished_at": metadata.finished_at,
        "report_status": status_label(summary),
        "finding_count": summary.finding_count,
        "step_count": summary.step_count,
        "hallucination_rate": format_rate(summary.finding_count, summary.step_count),
        "high_count": summary.severity_counts["high"],
        "medium_count": summary.severity_counts["medium"],
        "low_count": summary.severity_counts["low"],
        "report_path": display_path(target.report_path),
        "trajectory_path": display_path(target.trajectory_path),
        "error": summary.error,
    }


def status_label(summary: TrialSummary) -> str:
    if summary.report_status != "ok":
        return summary.report_status
    return "nonempty" if summary.finding_count else "empty"


def write_findings(path: Path, findings: list[FindingRow]) -> None:
    fieldnames = [
        "job",
        "trial",
        "step",
        "task_name",
        "source",
        "agent",
        "model",
        "reward",
        "reward_bucket",
        "finding_index",
        "category",
        "severity",
        "confidence",
        "summary",
        "contradicting_agent_claim",
        "rationale",
        "evidence_count",
        "prior_evidence",
        "claim_event_index",
        "evidence_event_indices",
        "report_path",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for finding in findings:
        writer.writerow(finding_csv_row(finding))
    path.write_text(output.getvalue())


def finding_csv_row(row: FindingRow) -> dict[str, Any]:
    finding = row.finding
    metadata = row.metadata
    location = (
        finding.get("location") if isinstance(finding.get("location"), dict) else {}
    )
    prior_evidence = finding.get("prior_evidence")
    evidence_items = prior_evidence if isinstance(prior_evidence, list) else []
    evidence_indices = location.get("evidence_event_indices")
    return {
        "job": row.target.job,
        "trial": metadata.trial_name or row.target.trial,
        "step": row.target.step_name or "",
        "task_name": metadata.task_name,
        "source": metadata.source,
        "agent": metadata.agent,
        "model": metadata.model,
        "reward": "" if metadata.reward is None else metadata.reward,
        "reward_bucket": reward_bucket(metadata.reward),
        "finding_index": row.finding_index,
        "category": str(finding.get("category") or ""),
        "severity": str(finding.get("severity") or ""),
        "confidence": str(finding.get("confidence") or ""),
        "summary": str(finding.get("summary") or ""),
        "contradicting_agent_claim": str(
            finding.get("contradicting_agent_claim") or ""
        ),
        "rationale": str(finding.get("rationale") or ""),
        "evidence_count": len(evidence_items),
        "prior_evidence": " | ".join(str(item) for item in evidence_items),
        "claim_event_index": location.get("claim_event_index", ""),
        "evidence_event_indices": ",".join(str(item) for item in evidence_indices)
        if isinstance(evidence_indices, list)
        else "",
        "report_path": display_path(row.target.report_path),
    }


def write_aggregate_summary(path: Path, data: SummaryData) -> None:
    rows = aggregate_rows(data)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["section", "key", "value"])
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue())


def aggregate_rows(data: SummaryData) -> list[dict[str, Any]]:
    status_counts = Counter(status_label(summary) for summary in data.trial_summaries)
    total_steps = sum(summary.step_count for summary in data.trial_summaries)
    rows = [
        {"section": "coverage", "key": "job_folders", "value": len(data.job_dirs)},
        {"section": "coverage", "key": "trials", "value": count_trials(data)},
        {
            "section": "coverage",
            "key": "trajectory_targets",
            "value": len(data.targets),
        },
        {"section": "coverage", "key": "total_steps", "value": total_steps},
        {
            "section": "coverage",
            "key": "reports_found",
            "value": len(data.trial_summaries) - status_counts["missing"],
        },
        {
            "section": "coverage",
            "key": "reports_missing",
            "value": status_counts["missing"],
        },
        {
            "section": "coverage",
            "key": "invalid_reports",
            "value": status_counts["invalid"],
        },
        {
            "section": "coverage",
            "key": "empty_reports",
            "value": status_counts["empty"],
        },
        {
            "section": "coverage",
            "key": "nonempty_reports",
            "value": status_counts["nonempty"],
        },
        {"section": "findings", "key": "total_findings", "value": len(data.findings)},
        {
            "section": "findings",
            "key": "hallucination_rate",
            "value": format_rate(len(data.findings), total_steps),
        },
        {
            "section": "findings",
            "key": "findings_per_reported_target",
            "value": format_float(
                len(data.findings)
                / max(1, status_counts["empty"] + status_counts["nonempty"])
            ),
        },
    ]
    for section, counter in (
        (
            "category",
            Counter(finding.finding.get("category", "") for finding in data.findings),
        ),
        (
            "severity",
            Counter(finding.finding.get("severity", "") for finding in data.findings),
        ),
        (
            "confidence",
            Counter(finding.finding.get("confidence", "") for finding in data.findings),
        ),
    ):
        for key, value in sorted(counter.items()):
            rows.append({"section": section, "key": key or "missing", "value": value})
    return rows


def write_markdown_summary(path: Path, data: SummaryData, *, top_k: int) -> None:
    path.write_text(render_markdown_summary(data, top_k=top_k))


def render_markdown_summary(data: SummaryData, *, top_k: int) -> str:
    status_counts = Counter(status_label(summary) for summary in data.trial_summaries)
    reported = status_counts["empty"] + status_counts["nonempty"]
    findings_per_reported = len(data.findings) / max(1, reported)
    total_steps = sum(summary.step_count for summary in data.trial_summaries)

    lines = [
        "# Hallucination Report Summary",
        "",
        "## Overall Coverage",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Job folders | {len(data.job_dirs)} |",
        f"| Trials | {count_trials(data)} |",
        f"| Trajectory targets | {len(data.targets)} |",
        f"| Total steps | {total_steps} |",
        f"| Reports found | {reported + status_counts['invalid']} |",
        f"| Reports missing | {status_counts['missing']} |",
        f"| Invalid reports | {status_counts['invalid']} |",
        f"| Empty reports | {status_counts['empty']} |",
        f"| Reports with findings | {status_counts['nonempty']} |",
        "",
        "## Hallucination Totals",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total findings | {len(data.findings)} |",
        f"| Findings per reported target | {format_float(findings_per_reported)} |",
        f"| Hallucination rate | {format_rate(len(data.findings), total_steps)} |",
        "",
    ]

    lines.extend(render_counter_section("By Category", counter_for(data, "category")))
    lines.extend(render_counter_section("By Severity", counter_for(data, "severity")))
    lines.extend(
        render_counter_section("By Confidence", counter_for(data, "confidence"))
    )
    lines.extend(render_counter_section("By Task", task_counter(data)))
    lines.extend(
        render_counter_section("By Reward Bucket", reward_bucket_counter(data))
    )
    lines.extend(render_top_findings(data.findings, data.trial_summaries, top_k))
    lines.extend(render_problem_sections(data.trial_summaries))
    return "\n".join(lines).rstrip() + "\n"


def render_counter_section(title: str, counter: Counter[str]) -> list[str]:
    lines = [f"## {title}", "", "| Value | Findings |", "| --- | ---: |"]
    if not counter:
        lines.append("| none | 0 |")
    else:
        for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {markdown_cell(key or 'missing')} | {value} |")
    lines.append("")
    return lines


def render_top_findings(
    findings: list[FindingRow], summaries: list[TrialSummary], top_k: int
) -> list[str]:
    summaries_by_target = {summary.target: summary for summary in summaries}
    lines = [
        "## Top Findings",
        "",
        "| Trial | Reward | Findings | Steps | Rate | Category | Severity | Confidence | Summary | Report |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    if not findings:
        lines.append("| none |  | 0 | 0 |  |  |  |  |  |  |")
    for finding in sorted(findings, key=finding_sort_key)[:top_k]:
        item = finding.finding
        summary = summaries_by_target.get(finding.target)
        finding_count = summary.finding_count if summary is not None else ""
        step_count = summary.step_count if summary is not None else ""
        rate = (
            format_rate(summary.finding_count, summary.step_count)
            if summary is not None
            else ""
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(finding.metadata.trial_name or finding.target.trial),
                    format_reward(finding.metadata.reward),
                    str(finding_count),
                    str(step_count),
                    rate,
                    markdown_cell(str(item.get("category") or "")),
                    markdown_cell(str(item.get("severity") or "")),
                    markdown_cell(str(item.get("confidence") or "")),
                    markdown_cell(str(item.get("summary") or "")),
                    markdown_cell(display_path(finding.target.report_path)),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def finding_sort_key(finding: FindingRow) -> tuple[int, int, str, int]:
    item = finding.finding
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    return (
        severity_rank.get(str(item.get("severity") or ""), 9),
        confidence_rank.get(str(item.get("confidence") or ""), 9),
        finding.target.report_path.as_posix(),
        finding.finding_index,
    )


def render_problem_sections(summaries: list[TrialSummary]) -> list[str]:
    invalid = [summary for summary in summaries if summary.report_status == "invalid"]
    missing = [summary for summary in summaries if summary.report_status == "missing"]
    lines = ["## Invalid And Missing Reports", ""]
    lines.extend(render_summary_list("Invalid reports", invalid, include_error=True))
    lines.extend(render_summary_list("Missing reports", missing, include_error=False))
    return lines


def render_summary_list(
    title: str, summaries: list[TrialSummary], *, include_error: bool
) -> list[str]:
    lines = [f"### {title}", ""]
    if not summaries:
        lines.append("- none")
        lines.append("")
        return lines
    for summary in summaries[:50]:
        detail = display_path(summary.target.report_path)
        if include_error and summary.error:
            detail += f" ({summary.error})"
        lines.append(f"- `{detail}`")
    if len(summaries) > 50:
        lines.append(f"- ... {len(summaries) - 50} more")
    lines.append("")
    return lines


def counter_for(data: SummaryData, field: str) -> Counter[str]:
    return Counter(str(row.finding.get(field) or "missing") for row in data.findings)


def task_counter(data: SummaryData) -> Counter[str]:
    return Counter(row.metadata.task_name or "missing" for row in data.findings)


def reward_bucket_counter(data: SummaryData) -> Counter[str]:
    return Counter(reward_bucket(row.metadata.reward) for row in data.findings)


def count_trials(data: SummaryData) -> int:
    return len({summary.target.trial_dir for summary in data.trial_summaries})


def display_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def format_float(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def format_reward(reward: float | None) -> str:
    return "" if reward is None else format_float(reward)


def format_rate(finding_count: int, step_count: int) -> str:
    if step_count <= 0:
        return ""
    return format_float(finding_count / step_count)


if __name__ == "__main__":
    raise SystemExit(main())
