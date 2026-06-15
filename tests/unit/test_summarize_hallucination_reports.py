import csv
import importlib.util
import json
import sys
from pathlib import Path


def load_summarize_module():
    script_path = (
        Path(__file__).parents[2] / "scripts" / "summarize_hallucination_reports.py"
    )
    spec = importlib.util.spec_from_file_location(
        "summarize_hallucination_reports",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load summarize_hallucination_reports.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discovers_step_targets_and_prefers_them_over_root_trajectory(tmp_path):
    summarize = load_summarize_module()
    job = tmp_path / "job"
    trial = job / "trial-a"
    write_trajectory(trial / "agent" / "trajectory.json", step_count=2)
    write_trajectory(
        trial / "steps" / "run" / "agent" / "trajectory.json", step_count=3
    )
    write_file(trial / "steps" / "run" / "verifier" / "hallucination-result.json", "[]")

    job_dirs = summarize.discover_job_dirs([job])
    targets = summarize.discover_targets(
        job_dirs, report_name="hallucination-result.json"
    )

    assert len(targets) == 1
    assert targets[0].trial_dir == trial
    assert targets[0].step_name == "run"
    assert targets[0].report_path == (
        trial / "steps" / "run" / "verifier" / "hallucination-result.json"
    )


def test_summarize_counts_empty_nonempty_missing_and_invalid_reports(tmp_path):
    summarize = load_summarize_module()
    job = tmp_path / "job"

    empty = job / "trial-empty"
    write_trajectory(empty / "agent" / "trajectory.json", step_count=2)
    write_file(empty / "verifier" / "hallucination-result.json", "[]")
    write_result_json(empty, task_name="bench/empty", reward=1.0)

    nonempty = job / "trial-nonempty"
    write_trajectory(
        nonempty / "steps" / "run" / "agent" / "trajectory.json", step_count=4
    )
    write_json(
        nonempty / "steps" / "run" / "verifier" / "hallucination-result.json",
        [finding("false_completion_claim", "high", "high")],
    )
    write_result_json(nonempty, task_name="bench/nonempty", reward=0.82)

    missing = job / "trial-missing"
    write_trajectory(
        missing / "steps" / "run" / "agent" / "trajectory.json", step_count=5
    )

    invalid = job / "trial-invalid"
    write_trajectory(invalid / "agent" / "trajectory.json", step_count=6)
    write_file(invalid / "verifier" / "hallucination-result.json", "{not json")

    data = summarize.summarize_paths([job], report_name="hallucination-result.json")

    status_counts = {
        summary.target.trial: summarize.status_label(summary)
        for summary in data.trial_summaries
    }
    assert status_counts == {
        "trial-empty": "empty",
        "trial-invalid": "invalid",
        "trial-missing": "missing",
        "trial-nonempty": "nonempty",
    }
    assert len(data.findings) == 1
    assert data.findings[0].metadata.task_name == "bench/nonempty"
    assert data.findings[0].metadata.reward == 0.82
    assert summarize.reward_bucket(data.findings[0].metadata.reward) == "0.75-<0.9"
    assert {
        summary.target.trial: summary.step_count for summary in data.trial_summaries
    } == {
        "trial-empty": 2,
        "trial-invalid": 6,
        "trial-missing": 5,
        "trial-nonempty": 4,
    }


def test_write_outputs_contains_expected_csv_and_markdown(tmp_path):
    summarize = load_summarize_module()
    job = tmp_path / "job"
    trial = job / "trial-a"
    write_trajectory(trial / "agent" / "trajectory.json", step_count=4)
    write_json(
        trial / "verifier" / "hallucination-result.json",
        [finding("unsupported_factual_claim", "medium", "high")],
    )
    write_result_json(trial, task_name="bench/task-a", reward=0.4)

    data = summarize.summarize_paths([job], report_name="hallucination-result.json")
    out = tmp_path / "out"
    out.mkdir()
    summarize.write_outputs(out, data, top_k=10)

    summary_md = (out / "summary.md").read_text()
    assert "# Hallucination Report Summary" in summary_md
    assert "| Trials | 1 |" in summary_md
    assert "| Total steps | 4 |" in summary_md
    assert "| Total findings | 1 |" in summary_md
    assert "| Hallucination rate | 0.25 |" in summary_md
    assert "## Highest Hallucination Rates" not in summary_md
    assert (
        "| Trial | Reward | Findings | Steps | Rate | Category | Severity | Confidence | Summary | Report |"
        in summary_md
    )
    assert "| trial-a | 0.4 | 1 | 4 | 0.25 | unsupported_factual_claim" in summary_md
    assert "| unsupported_factual_claim | 1 |" in summary_md
    assert "bench/task-a" in summary_md

    finding_rows = list(csv.DictReader((out / "findings.csv").open()))
    assert finding_rows[0]["category"] == "unsupported_factual_claim"
    assert finding_rows[0]["evidence_count"] == "1"
    assert finding_rows[0]["claim_event_index"] == "7"

    trial_rows = list(csv.DictReader((out / "trial_summary.csv").open()))
    assert trial_rows[0]["report_status"] == "nonempty"
    assert trial_rows[0]["step_count"] == "4"
    assert trial_rows[0]["hallucination_rate"] == "0.25"
    assert trial_rows[0]["medium_count"] == "1"

    aggregate_rows = list(csv.DictReader((out / "aggregate_summary.csv").open()))
    assert {
        "section": "findings",
        "key": "total_findings",
        "value": "1",
    } in aggregate_rows
    assert {
        "section": "findings",
        "key": "hallucination_rate",
        "value": "0.25",
    } in aggregate_rows
    assert {"section": "coverage", "key": "trials", "value": "1"} in aggregate_rows
    assert {"section": "coverage", "key": "total_steps", "value": "4"} in aggregate_rows


def write_result_json(trial: Path, *, task_name: str, reward: float) -> None:
    write_json(
        trial / "result.json",
        {
            "trial_name": trial.name,
            "task_name": task_name,
            "source": "clawbench",
            "started_at": "2026-06-10T00:00:00Z",
            "finished_at": "2026-06-10T00:01:00Z",
            "agent_info": {
                "name": "openclaw",
                "model_info": {"provider": "anthropic", "name": "kimi-k2.6"},
            },
            "verifier_result": {"rewards": {"reward": reward}},
        },
    )


def finding(category: str, severity: str, confidence: str) -> dict:
    return {
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "summary": "Agent made an unsupported claim.",
        "contradicting_agent_claim": "It works.",
        "prior_evidence": ["No successful verification happened."],
        "location": {"claim_event_index": 7, "evidence_event_indices": [3]},
        "rationale": "The claim is not supported by prior evidence.",
    }


def write_trajectory(path: Path, *, step_count: int) -> None:
    write_json(path, {"steps": [{} for _ in range(step_count)]})


def write_json(path: Path, data) -> None:
    write_file(path, json.dumps(data))


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
