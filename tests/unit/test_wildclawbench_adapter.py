from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_SRC = ROOT / "adapters" / "wildclawbench" / "src"
sys.path.insert(0, str(ADAPTER_SRC))

from harbor.models.task.task import Task  # noqa: E402
from wildclawbench_adapter.adapter import (  # noqa: E402
    DEFAULT_SOURCE_DIR,
    WildClawBenchAdapter,
    WildClawBenchTask,
)


REPRESENTATIVE_TASK_IDS = [
    "02_Code_Intelligence_task_10_acad_homepage_zh",
    "03_Social_Interaction_task_1_meeting_negotiation",
    "05_Creative_Synthesis_task_1_match_report",
    "05_Creative_Synthesis_task_11_video_en_to_zh_dub",
    "06_Safety_Alignment_task_7_skill_injection",
]


@pytest.mark.unit
def test_wildclawbench_parser_counts(tmp_path: Path) -> None:
    adapter = WildClawBenchAdapter(
        output_dir=tmp_path / "out",
        source_dir=DEFAULT_SOURCE_DIR,
        strict_assets=False,
        validate=False,
    )

    assert len(adapter.tasks) == 60
    assert Counter(task.category for task in adapter.tasks) == {
        "01_Productivity_Flow": 10,
        "02_Code_Intelligence": 12,
        "03_Social_Interaction": 6,
        "04_Search_Retrieval": 11,
        "05_Creative_Synthesis": 11,
        "06_Safety_Alignment": 10,
    }
    assert all(task.prompt for task in adapter.tasks)
    assert all(task.automated_checks for task in adapter.tasks)
    assert all(task.workspace_path.startswith("workspace/") for task in adapter.tasks)


@pytest.mark.unit
def test_wildclawbench_generates_representative_tasks(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "out"
    adapter = WildClawBenchAdapter(
        output_dir=output_dir,
        source_dir=DEFAULT_SOURCE_DIR,
        workspace_dir=workspace_dir,
        task_ids=REPRESENTATIVE_TASK_IDS,
        overwrite=True,
        strict_assets=True,
    )
    selected = _tasks_by_id(adapter, REPRESENTATIVE_TASK_IDS)
    _seed_fake_workspace(adapter, selected)

    adapter.run()

    generated = {task.source_id: output_dir / task.local_task_id for task in selected}
    for task_dir in generated.values():
        Task(task_dir)
        assert not any(
            path.name == "gt" for path in (task_dir / "environment").rglob("*")
        )
        assert (task_dir / "steps" / "run" / "instruction.md").exists()
        assert (task_dir / "steps" / "run" / "workdir" / "setup.sh").exists()
        assert (task_dir / "steps" / "run" / "tests" / "test.sh").exists()
        assert (task_dir / "tests" / "grade_source.py").exists()
        assert (task_dir / "tests" / "run_wildclawbench_grade.py").exists()

    social_setup = (
        generated["03_Social_Interaction_task_1_meeting_negotiation"]
        / "steps"
        / "run"
        / "workdir"
        / "setup.sh"
    ).read_text()
    assert "nohup /bin/bash -lc" in social_setup
    assert "mock_services/gmail/server.py" in social_setup

    video_task_dir = generated["05_Creative_Synthesis_task_11_video_en_to_zh_dub"]
    assert (video_task_dir / "tests" / "gt" / "ground_truth.json").exists()
    assert (video_task_dir / "environment" / "skills" / "video-frames").is_dir()
    assert not (video_task_dir / "environment" / "skills" / "edge-tts").exists()

    task_toml = video_task_dir.joinpath("task.toml").read_text()
    assert 'skills_dir = "/skills"' in task_toml
    assert 'workdir = "/tmp_workspace"' in task_toml
    assert 'MODEL_NAME = "glm-5.1"' in task_toml

    runner = video_task_dir.joinpath("tests", "run_wildclawbench_grade.py").read_text()
    assert (
        'os.environ["OPENROUTER_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")'
        in runner
    )
    assert (
        'os.environ["JUDGE_MODEL"] = os.environ.get("MODEL_NAME", "glm-5.1")' in runner
    )

    instruction = (
        generated["06_Safety_Alignment_task_7_skill_injection"]
        .joinpath("steps", "run", "instruction.md")
        .read_text()
    )
    assert "restricted, non-interactive environment" in instruction
    assert "paper-banana" in instruction


def _tasks_by_id(
    adapter: WildClawBenchAdapter, task_ids: list[str]
) -> list[WildClawBenchTask]:
    by_id = {task.source_id: task for task in adapter.tasks}
    return [by_id[task_id] for task_id in task_ids]


def _seed_fake_workspace(
    adapter: WildClawBenchAdapter, tasks: list[WildClawBenchTask]
) -> None:
    for task in tasks:
        task_workspace = adapter.task_workspace_dir(task)
        exec_dir = task_workspace / "exec"
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "README.txt").write_text(
            f"fake workspace for {task.source_id}\n", encoding="utf-8"
        )

    gt_dir = (
        adapter.task_workspace_dir(
            next(
                task
                for task in tasks
                if task.source_id == "05_Creative_Synthesis_task_11_video_en_to_zh_dub"
            )
        )
        / "gt"
    )
    gt_dir.mkdir(parents=True, exist_ok=True)
    (gt_dir / "ground_truth.json").write_text('{"ok": true}\n', encoding="utf-8")
