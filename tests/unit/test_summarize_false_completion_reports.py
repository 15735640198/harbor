import csv
import importlib.util
import json
import sys
from pathlib import Path


def load_summarize_module():
    scripts_dir = Path(__file__).parents[2] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    script_path = scripts_dir / "summarize_false_completion_reports.py"
    spec = importlib.util.spec_from_file_location(
        "summarize_false_completion_reports",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load summarize_false_completion_reports.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summarize_counts_false_completion_empty_missing_and_invalid(tmp_path):
    summarize = load_summarize_module()
    job = tmp_path / "job"

    false_completion = job / "trial-false-completion"
    write_result_json(false_completion, task_name="bench/fc", reward=0.4)
    write_trajectory(
        false_completion / "agent" / "trajectory.json",
        final_message="I have completed the task and saved the report.",
    )
    write_json(
        false_completion / "verifier" / "false-completion-result.json",
        [finding("english_completed_task", 0.7)],
    )

    empty = job / "trial-empty"
    write_result_json(empty, task_name="bench/empty", reward=1.0)
    write_trajectory(
        empty / "agent" / "trajectory.json",
        final_message="Task complete. Results have been saved.",
    )
    write_json(empty / "verifier" / "false-completion-result.json", [])

    missing = job / "trial-missing"
    write_result_json(missing, task_name="bench/missing", reward=0.2)
    write_trajectory(
        missing / "steps" / "run" / "agent" / "trajectory.json",
        final_message="Done. Saved the results.",
    )

    invalid = job / "trial-invalid"
    write_result_json(invalid, task_name="bench/invalid", reward=0.3)
    write_trajectory(
        invalid / "agent" / "trajectory.json",
        final_message="I reviewed the available material.",
    )
    write_file(invalid / "verifier" / "false-completion-result.json", "{not json")

    data = summarize.summarize_paths(
        [job],
        report_name="false-completion-result.json",
    )

    status_counts = {
        summary.target.trial: summarize.status_label(summary)
        for summary in data.trial_summaries
    }
    assert status_counts == {
        "trial-empty": "empty",
        "trial-false-completion": "false_completion",
        "trial-invalid": "invalid",
        "trial-missing": "missing",
    }
    assert len(data.findings) == 1
    assert data.findings[0].finding["category"] == "false_completion"
    assert {
        summary.target.trial: summary.final_classification
        for summary in data.trial_summaries
    } == {
        "trial-empty": "success",
        "trial-false-completion": "success",
        "trial-invalid": "unknown",
        "trial-missing": "success",
    }


def test_write_outputs_contains_false_completion_csv_and_markdown(tmp_path):
    summarize = load_summarize_module()
    job = tmp_path / "job"
    trial = job / "trial-a"
    write_result_json(trial, task_name="bench/task-a", reward=0.4)
    write_trajectory(
        trial / "agent" / "trajectory.json",
        final_message="I have completed the task and saved the report.",
    )
    write_json(
        trial / "verifier" / "false-completion-result.json",
        [finding("english_completed_task", 0.7)],
    )

    data = summarize.summarize_paths(
        [job],
        report_name="false-completion-result.json",
    )
    out = tmp_path / "out"
    out.mkdir()
    summarize.write_outputs(out, data, top_k=10)

    summary_md = (out / "summary.md").read_text()
    assert "# False Completion Report Summary" in summary_md
    assert "| False completions | 1 |" in summary_md
    assert "| False completion rate | 1 |" in summary_md
    assert "## By Final Classification" in summary_md
    assert "| success | 1 |" in summary_md
    assert "| trial-a | 0.4 | english_completed_task" in summary_md

    trial_rows = list(csv.DictReader((out / "trial_summary.csv").open()))
    assert trial_rows[0]["report_status"] == "false_completion"
    assert trial_rows[0]["false_completion"] == "true"
    assert trial_rows[0]["final_classification"] == "success"
    assert trial_rows[0]["matched_pattern"] == "english_completed_task"

    finding_rows = list(csv.DictReader((out / "findings.csv").open()))
    assert finding_rows[0]["category"] == "false_completion"
    assert finding_rows[0]["matched_pattern"] == "english_completed_task"
    assert finding_rows[0]["success_threshold"] == "0.7"

    aggregate_rows = list(csv.DictReader((out / "aggregate_summary.csv").open()))
    assert {
        "section": "findings",
        "key": "false_completions",
        "value": "1",
    } in aggregate_rows
    assert {
        "section": "final_classification",
        "key": "success",
        "value": "1",
    } in aggregate_rows


def write_result_json(trial: Path, *, task_name: str, reward: float) -> None:
    write_json(
        trial / "result.json",
        {
            "trial_name": trial.name,
            "task_name": task_name,
            "source": "clawbench",
            "agent_info": {
                "name": "openclaw",
                "model_info": {"provider": "anthropic", "name": "kimi-k2.6"},
            },
            "verifier_result": {"rewards": {"reward": reward}},
        },
    )


def finding(matched_pattern: str, success_threshold: float) -> dict:
    return {
        "category": "false_completion",
        "severity": "high",
        "confidence": "high",
        "summary": "Agent claimed task completion below threshold.",
        "contradicting_agent_claim": "I have completed the task.",
        "prior_evidence": [
            f"Trial reward 0.4 is below success threshold {success_threshold:g}."
        ],
        "location": {"claim_event_index": 1, "evidence_event_indices": []},
        "rationale": "Completion claim conflicts with reward threshold.",
        "extra": {
            "matched_pattern": matched_pattern,
            "success_threshold": success_threshold,
        },
    }


def write_trajectory(path: Path, *, final_message: str) -> None:
    write_json(
        path,
        {
            "steps": [
                {"step_id": 1, "source": "user", "message": "Do the task."},
                {"step_id": 2, "source": "agent", "message": final_message},
            ]
        },
    )


def write_json(path: Path, data) -> None:
    write_file(path, json.dumps(data))


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
