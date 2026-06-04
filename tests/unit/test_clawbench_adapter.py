from __future__ import annotations

# ruff: noqa: E402

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_SRC = ROOT / "adapters" / "clawbench" / "src"
sys.path.insert(0, str(ADAPTER_SRC))

from clawbench_adapter.adapter import (
    DEFAULT_SOURCE_DIR,
    ClawBenchAdapter,
    ClawBenchTask,
)  # noqa: E402
from harbor.models.task.task import Task  # noqa: E402


REPRESENTATIVE_TASK_IDS = [
    "t1-bugfix-discount",
    "t2-fs-find-that-thing",
    "t2-browser-form-fix",
    "t4-memory-recall-continuation",
    "t5-hallucination-resistant-evidence",
]


@pytest.mark.unit
def test_clawbench_manifest_default_loads_core_public_only(tmp_path: Path) -> None:
    adapter = ClawBenchAdapter(
        output_dir=tmp_path / "out",
        source_dir=DEFAULT_SOURCE_DIR,
        validate=False,
    )

    raw_yaml_count = len(
        list((DEFAULT_SOURCE_DIR / "tasks-public").glob("tier*/*.yaml"))
    )

    assert raw_yaml_count == 27
    assert len(adapter.tasks) == 19
    assert "t1-bugfix-discount" in {task.source_id for task in adapter.tasks}
    assert "t1-bugfix-discount-perturbed" not in {
        task.source_id for task in adapter.tasks
    }


@pytest.mark.unit
def test_clawbench_task_id_filter_accepts_source_and_local_ids(tmp_path: Path) -> None:
    adapter = ClawBenchAdapter(
        output_dir=tmp_path / "out",
        source_dir=DEFAULT_SOURCE_DIR,
        task_ids=["t1-bugfix-discount", "t2-fs-find-that-thing"],
        validate=False,
    )

    selected = adapter._select_tasks()

    assert [task.source_id for task in selected] == [
        "t1-bugfix-discount",
        "t2-fs-find-that-thing",
    ]


@pytest.mark.unit
def test_clawbench_unknown_task_id_fails(tmp_path: Path) -> None:
    adapter = ClawBenchAdapter(
        output_dir=tmp_path / "out",
        source_dir=DEFAULT_SOURCE_DIR,
        task_ids=["not-a-task"],
        validate=False,
    )

    with pytest.raises(ValueError, match="Unknown task id"):
        adapter.run()


@pytest.mark.unit
def test_clawbench_generates_representative_tasks(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    adapter = ClawBenchAdapter(
        output_dir=output_dir,
        source_dir=DEFAULT_SOURCE_DIR,
        task_ids=REPRESENTATIVE_TASK_IDS,
        overwrite=True,
    )

    adapter.run()

    tasks = _tasks_by_id(adapter, REPRESENTATIVE_TASK_IDS)
    for task in tasks:
        task_dir = output_dir / task.local_task_id
        Task(task_dir)
        assert (task_dir / "environment" / "workspace").is_dir()
        assert (task_dir / "tests" / "clawbench_task.json").exists()
        assert (task_dir / "tests" / "clawbench_verifier_runtime.py").exists()
        assert not (task_dir / "environment" / "clawbench_verifier_runtime.py").exists()

    coding_task = output_dir / "t1-bugfix-discount"
    assert (coding_task / "environment" / "workspace" / "pricing.py").exists()
    assert (coding_task / "steps" / "run" / "tests" / "test.sh").exists()
    dockerfile = (coding_task / "environment" / "Dockerfile").read_text()
    assert "FROM --platform=linux/amd64 ghcr.io/openclaw/openclaw@" in dockerfile
    assert "HEALTHCHECK NONE" in dockerfile
    assert "ENV NODE_PATH=/workspace/node_modules" in dockerfile
    assert "npm install --prefix /workspace" in dockerfile
    assert "playwright@1.59.1" in dockerfile
    task_toml = (coding_task / "task.toml").read_text()
    assert 'MODEL_NAME = "${MODEL_NAME:-glm-5.1}"' in task_toml
    assert 'JUDGE_API_FORMAT = "${JUDGE_API_FORMAT:-auto}"' in task_toml
    assert 'OPENAI_API_KEY = "${OPENAI_API_KEY:-}"' in task_toml
    assert 'OPENAI_BASE_URL = "${OPENAI_BASE_URL:-}"' in task_toml

    browser_task = output_dir / "t2-browser-form-fix"
    setup = (browser_task / "steps" / "run" / "workdir" / "setup.sh").read_text()
    instruction = (browser_task / "steps" / "run" / "instruction.md").read_text()
    verifier_spec = (browser_task / "tests" / "clawbench_task.json").read_text()
    assert "PORT=" in setup
    assert "http://127.0.0.1:" in instruction
    assert "form_app_port" not in verifier_spec

    memory_task = output_dir / "t4-memory-recall-continuation"
    assert (memory_task / "steps" / "prep" / "instruction.md").exists()
    implementation = (
        memory_task / "steps" / "implementation" / "instruction.md"
    ).read_text()
    assert "Follow-up instruction 2" in implementation
    assert (
        'multi_step_reward_strategy = "final"'
        in (memory_task / "task.toml").read_text()
    )

    adversarial_task = output_dir / "t5-hallucination-resistant-evidence"
    assert (
        adversarial_task / "environment" / "workspace" / "docs" / "maintenance_notes.md"
    ).exists()


@pytest.mark.unit
def test_clawbench_can_hardlink_assets(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    adapter = ClawBenchAdapter(
        output_dir=output_dir,
        source_dir=DEFAULT_SOURCE_DIR,
        task_ids=["t1-bugfix-discount"],
        overwrite=True,
        link_assets=True,
    )

    adapter.run()

    source = (
        DEFAULT_SOURCE_DIR
        / "tasks-public"
        / "assets"
        / "t1_bugfix_discount"
        / "pricing.py"
    )
    staged = (
        output_dir / "t1-bugfix-discount" / "environment" / "workspace" / "pricing.py"
    )
    assert staged.stat().st_ino == source.stat().st_ino


def _tasks_by_id(adapter: ClawBenchAdapter, task_ids: list[str]) -> list[ClawBenchTask]:
    by_id = {task.source_id: task for task in adapter.tasks}
    return [by_id[task_id] for task_id in task_ids]
