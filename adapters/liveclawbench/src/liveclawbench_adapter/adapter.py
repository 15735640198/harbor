"""Import the already-Harbor-compatible LiveClawBench task corpus."""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import re
import shutil
import tomllib


ADAPTER_DIR = Path(__file__).resolve().parents[2]
HARBOR_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE_DIR = (
    HARBOR_ROOT / "related-projects" / "external-tasks" / "liveclawbench"
)


class LiveClawBenchAdapter:
    """Copy LiveClawBench's native Harbor tasks and add package metadata."""

    def __init__(
        self,
        output_dir: Path,
        *,
        source_dir: Path = DEFAULT_SOURCE_DIR,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        org: str = "mosi-ai",
        validate: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.source_dir = Path(source_dir)
        self.tasks_dir = self.source_dir / "tasks"
        self.limit = limit
        self.overwrite = overwrite
        self.task_ids = task_ids
        self.org = org
        self.validate = validate

    @staticmethod
    def make_local_task_id(source_id: str) -> str:
        """Produce a stable directory and package-name-safe task identifier."""
        normalized = source_id.strip().lower().replace("_", "-")
        normalized = re.sub(r"[^a-z0-9.-]+", "-", normalized)
        return re.sub(r"-+", "-", normalized).strip("-.") or "liveclawbench-task"

    def generate_task(self, task_id: str) -> Path:
        """Generate one task, accepting either the source or local task ID."""
        tasks = {source.name: source for source in self._discover_source_tasks()}
        tasks.update(
            {self.make_local_task_id(source.name): source for source in tasks.values()}
        )
        try:
            source = tasks[task_id]
        except KeyError as exc:
            raise ValueError(f"Unknown LiveClawBench task ID: {task_id}") from exc
        return self._generate_task(source)

    def run(self) -> None:
        """Generate all selected tasks."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for source in self._select_tasks():
            self._generate_task(source)

    def _discover_source_tasks(self) -> list[Path]:
        if not self.tasks_dir.is_dir():
            raise FileNotFoundError(
                "LiveClawBench task directory not found: "
                f"{self.tasks_dir}. Clone https://github.com/Mosi-AI/LiveClawBench "
                "and pass its root with --source-dir."
            )

        tasks = sorted(
            path
            for path in self.tasks_dir.iterdir()
            if path.is_dir() and (path / "task.toml").is_file()
        )
        local_ids = [self.make_local_task_id(task.name) for task in tasks]
        if len(local_ids) != len(set(local_ids)):
            raise ValueError("LiveClawBench task IDs collide after normalization")
        return tasks

    def _select_tasks(self) -> list[Path]:
        tasks = self._discover_source_tasks()
        if self.task_ids:
            by_id = {source.name: source for source in tasks}
            by_id.update(
                {self.make_local_task_id(source.name): source for source in tasks}
            )
            requested = list(dict.fromkeys(self.task_ids))
            missing = [task_id for task_id in requested if task_id not in by_id]
            if missing:
                raise ValueError(
                    "Requested LiveClawBench task IDs not found: " + ", ".join(missing)
                )
            tasks = [by_id[task_id] for task_id in requested]
        if self.limit is not None:
            tasks = tasks[: max(self.limit, 0)]
        return tasks

    def _generate_task(self, source: Path) -> Path:
        target = self.output_dir / self.make_local_task_id(source.name)
        if target.exists():
            if not self.overwrite:
                return target
            shutil.rmtree(target)

        shutil.copytree(source, target, symlinks=True)
        self._ensure_task_metadata(target, source.name)
        if self.validate:
            self._validate_harbor_task(target)
        return target

    def _ensure_task_metadata(self, task_dir: Path, source_id: str) -> None:
        """Add the registry package metadata absent from the upstream task files."""
        path = task_dir / "task.toml"
        raw = path.read_text(encoding="utf-8")
        config = tomllib.loads(raw)
        if config.get("task", {}).get("name"):
            return
        if "task" in config:
            raise ValueError(f"{path} has a [task] table without a name")

        metadata = config.get("metadata", {})
        keywords = metadata.get("tags", [])
        if not isinstance(keywords, list) or not all(
            isinstance(keyword, str) for keyword in keywords
        ):
            keywords = []
        description = f"LiveClawBench task: {source_id}"
        package_metadata = "\n".join(
            [
                "[task]",
                f"name = {json.dumps(f'{self.org}/{self.make_local_task_id(source_id)}')}",
                f"description = {json.dumps(description)}",
                'authors = [{ name = "Mosi-AI" }]',
                f"keywords = {json.dumps(keywords)}",
                "",
            ]
        )
        metadata_header = re.search(r"(?m)^\[metadata\]\s*$", raw)
        if metadata_header is None:
            raise ValueError(f"{path} has no [metadata] table")
        path.write_text(
            raw[: metadata_header.start()]
            + package_metadata
            + raw[metadata_header.start() :],
            encoding="utf-8",
        )

    @staticmethod
    def _validate_harbor_task(task_dir: Path) -> None:
        from harbor.models.task.task import Task

        task = Task(task_dir)
        if task.config.task is None:
            raise ValueError(f"{task_dir} is missing registry package metadata")


def validate_generated_tasks(task_dirs: Iterable[Path]) -> None:
    """Validate a collection of generated task directories for callers and tests."""
    for task_dir in task_dirs:
        LiveClawBenchAdapter._validate_harbor_task(task_dir)
