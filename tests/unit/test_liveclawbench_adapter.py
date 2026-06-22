from __future__ import annotations

from pathlib import Path
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_SRC = ROOT / "adapters" / "liveclawbench" / "src"
sys.path.insert(0, str(ADAPTER_SRC))

from harbor.models.task.task import Task  # noqa: E402
from liveclawbench_adapter.adapter import LiveClawBenchAdapter  # noqa: E402


def _write_source_task(root: Path, task_id: str) -> Path:
    task_dir = root / "tasks" / task_id
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "solution").mkdir()
    (task_dir / "tests").mkdir()
    (task_dir / "task.toml").write_text(
        """version = \"1.0\"\n\n[metadata]\ndifficulty = \"easy\"\ntags = [\"openclaw\", \"test\"]\n\n[environment]\nallow_internet = true\n"""
    )
    (task_dir / "instruction.md").write_text("Complete the task.\n")
    (task_dir / "environment" / "Dockerfile").write_text("FROM ubuntu:24.04\n")
    (task_dir / "solution" / "solve.sh").write_text("#!/bin/sh\n")
    (task_dir / "tests" / "test.sh").write_text("#!/bin/sh\n")
    return task_dir


@pytest.mark.unit
def test_liveclawbench_adapter_copies_native_task_and_adds_package_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source_task(source, "My_Task")
    output = tmp_path / "output"

    LiveClawBenchAdapter(
        output,
        source_dir=source,
        task_ids=["my-task"],
        org="mosi-ai",
    ).run()

    task_dir = output / "my-task"
    config = tomllib.loads((task_dir / "task.toml").read_text())
    assert config["task"] == {
        "name": "mosi-ai/my-task",
        "description": "LiveClawBench task: My_Task",
        "authors": [{"name": "Mosi-AI"}],
        "keywords": ["openclaw", "test"],
    }
    assert (
        task_dir / "environment" / "Dockerfile"
    ).read_text() == "FROM ubuntu:24.04\n"
    assert Task(task_dir).name == "mosi-ai/my-task"


@pytest.mark.unit
def test_liveclawbench_adapter_rejects_unknown_task_id(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_source_task(source, "known-task")

    adapter = LiveClawBenchAdapter(
        tmp_path / "output", source_dir=source, task_ids=["missing-task"]
    )

    with pytest.raises(ValueError, match="missing-task"):
        adapter.run()
