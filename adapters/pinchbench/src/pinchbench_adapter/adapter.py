"""Pinchbench adapter.

This adapter converts Pinchbench task markdown files into Harbor task directories.
By default it uses a Claude Code harness with the adapter-local
``pinchbench-to-harbor`` skill staged into Claude Code's skills directory.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol

import yaml

logger = logging.getLogger(__name__)

ADAPTER_DIR = Path(__file__).resolve().parents[2]
HARBOR_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE_DIR = HARBOR_ROOT / "related-projects" / "external-tasks" / "skill"
DEFAULT_SKILL_DIR = ADAPTER_DIR / "pinchbench-to-harbor"

HarnessName = Literal["claude-code", "direct"]


@dataclass(frozen=True)
class PinchbenchTask:
    """Normalized Pinchbench task metadata used by the adapter."""

    source_id: str
    local_task_id: str
    name: str
    category: str
    grading_type: str
    path: Path


class ConversionHarness(Protocol):
    """Small interface for task conversion backends."""

    def convert(self, task: PinchbenchTask, output_dir: Path) -> None:
        """Convert one Pinchbench task into ``output_dir``."""


class DirectSkillHarness:
    """Run the adapter-local skill converter directly.

    This is mainly for deterministic smoke tests and CI. The production adapter
    path should use ``ClaudeCodeHarness`` so the skill is exercised through an
    agent harness.
    """

    def __init__(
        self, *, source_dir: Path, skill_dir: Path, org: str, judge_model: str
    ):
        self.source_dir = source_dir
        self.skill_dir = skill_dir
        self.org = org
        self.judge_model = judge_model
        self._converter: ModuleType | None = None

    def convert(self, task: PinchbenchTask, output_dir: Path) -> None:
        converter = self._load_converter()
        loaded_task = converter.load_pinchbench_task(task.path)
        converter.build_harbor_task(
            task=loaded_task,
            task_md=task.path,
            pinchbench_root=self.source_dir,
            output_dir=output_dir,
            org=self.org,
            judge_model=self.judge_model,
            source_label=_source_label(task.path),
        )

    def _load_converter(self) -> ModuleType:
        if self._converter is not None:
            return self._converter

        converter_path = self.skill_dir / "scripts" / "convert_pinchbench_task.py"
        if not converter_path.exists():
            raise FileNotFoundError(f"Pinchbench converter not found: {converter_path}")

        spec = importlib.util.spec_from_file_location(
            "_pinchbench_to_harbor_converter", converter_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load converter module from {converter_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self._converter = module
        return module


class ClaudeCodeHarness:
    """Use Claude Code to run the Pinchbench conversion skill."""

    def __init__(
        self,
        *,
        source_dir: Path,
        skill_dir: Path,
        org: str,
        judge_model: str,
        claude_bin: str = "claude",
        claude_model: str | None = None,
        claude_config_dir: Path | None = None,
        timeout_sec: int = 900,
        keep_workdirs: bool = False,
    ) -> None:
        self.source_dir = source_dir
        self.skill_dir = skill_dir
        self.org = org
        self.judge_model = judge_model
        self.claude_bin = claude_bin
        self.claude_model = claude_model
        self.claude_config_dir = claude_config_dir
        self.timeout_sec = timeout_sec
        self.keep_workdirs = keep_workdirs

    def convert(self, task: PinchbenchTask, output_dir: Path) -> None:
        claude_path = shutil.which(self.claude_bin)
        if claude_path is None:
            raise FileNotFoundError(
                f"`{self.claude_bin}` not found on PATH. Install Claude Code or use --harness direct."
            )

        if not self.skill_dir.exists():
            raise FileNotFoundError(f"Pinchbench skill not found: {self.skill_dir}")

        if self.keep_workdirs:
            workdir = (
                output_dir.parent / ".pinchbench-agent-workdirs" / task.local_task_id
            )
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True)
            self._run_in_workdir(claude_path, task, output_dir, workdir)
            return

        with tempfile.TemporaryDirectory(
            prefix=f"pinchbench-{task.local_task_id}-"
        ) as tmp:
            self._run_in_workdir(claude_path, task, output_dir, Path(tmp))

    def _run_in_workdir(
        self, claude_path: str, task: PinchbenchTask, output_dir: Path, workdir: Path
    ) -> None:
        config_dir = self._resolve_claude_config_dir()
        skills_dir = config_dir / "skills"
        logs_dir = workdir / "logs"
        staged_skill = skills_dir / self.skill_dir.name
        skills_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        if staged_skill.exists():
            shutil.rmtree(staged_skill)
        shutil.copytree(
            self.skill_dir,
            staged_skill,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

        prompt = self._build_prompt(task, output_dir, staged_skill)
        (logs_dir / "prompt.md").write_text(prompt, encoding="utf-8")

        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        if self.claude_model:
            env["ANTHROPIC_MODEL"] = self.claude_model.removeprefix("anthropic/")

        cmd = [
            claude_path,
            "--permission-mode=bypassPermissions",
            "--print",
            "--",
            prompt,
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=HARBOR_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_output_to_text(exc.stdout)
            stderr = _timeout_output_to_text(exc.stderr)
            (logs_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
            (logs_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
            raise TimeoutError(
                "Claude Code conversion timed out for "
                f"{task.source_id} after {self.timeout_sec} seconds.\n"
                f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
            ) from exc
        (logs_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (logs_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")

        if result.returncode != 0:
            raise RuntimeError(
                "Claude Code conversion failed for "
                f"{task.source_id} with exit code {result.returncode}.\n"
                f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
            )
        if not output_dir.exists():
            raise RuntimeError(
                f"Claude Code completed but did not create expected task dir: {output_dir}"
            )

    def _resolve_claude_config_dir(self) -> Path:
        if self.claude_config_dir is not None:
            return self.claude_config_dir.expanduser().resolve()
        configured = os.environ.get("CLAUDE_CONFIG_DIR")
        if configured:
            return Path(configured).expanduser().resolve()
        return (Path.home() / ".claude").resolve()

    def _build_prompt(
        self, task: PinchbenchTask, output_dir: Path, staged_skill: Path
    ) -> str:
        converter = staged_skill / "scripts" / "convert_pinchbench_task.py"
        command = [
            "uv",
            "run",
            str(converter),
            str(task.path),
            "--output-dir",
            str(output_dir),
            "--pinchbench-root",
            str(self.source_dir),
            "--org",
            self.org,
            "--judge-model",
            self.judge_model,
            "--source-label",
            _source_label(task.path),
            "--overwrite",
        ]
        shell_command = " ".join(_shell_quote(part) for part in command)
        return textwrap.dedent(
            f"""\
            Use $pinchbench-to-harbor to convert one Pinchbench task markdown file into a Harbor task directory.

            Task markdown: {task.path}
            Pinchbench root: {self.source_dir}
            Output directory: {output_dir}
            Adapter implementation guide: {HARBOR_ROOT / "docs/content/docs/datasets/adapter-implementation-guide.mdx"}

            The skill has already been copied into Claude Code at:
            {staged_skill}

            Run this exact conversion command:

            ```bash
            {shell_command}
            ```

            After running it, inspect the generated Harbor task shape briefly:
            - task.toml exists
            - environment/Dockerfile exists
            - instruction.md exists for single-step tasks or steps/*/instruction.md exists for multi-session tasks
            - tests/test.sh or final step tests/test.sh exists

            Do not modify unrelated repository files. Automated Pinchbench checks must remain deterministic verifier code, not LLM execution. Finish with: PINCHBENCH_CONVERSION_DONE {output_dir}
            """
        )


class PinchbenchAdapter:
    """Convert Pinchbench tasks into Harbor tasks."""

    NAME = "pinchbench"

    def __init__(
        self,
        output_dir: Path,
        *,
        source_dir: Path = DEFAULT_SOURCE_DIR,
        skill_dir: Path = DEFAULT_SKILL_DIR,
        harness: HarnessName = "claude-code",
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        core: bool = False,
        org: str = "pinchbench",
        judge_model: str = "claude-haiku-4-5",
        claude_bin: str = "claude",
        claude_model: str | None = None,
        claude_config_dir: Path | None = None,
        conversion_timeout_sec: int = 900,
        keep_agent_workdirs: bool = False,
        validate: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self.source_dir = source_dir
        self.tasks_dir = source_dir / "tasks"
        self.skill_dir = skill_dir
        self.harness_name = harness
        self.limit = limit
        self.overwrite = overwrite
        self.task_ids = task_ids
        self.core = core
        self.org = org
        self.judge_model = judge_model
        self.claude_bin = claude_bin
        self.claude_model = claude_model
        self.claude_config_dir = claude_config_dir
        self.conversion_timeout_sec = conversion_timeout_sec
        self.keep_agent_workdirs = keep_agent_workdirs
        self.validate = validate
        self.tasks = self._load_tasks()

    @staticmethod
    def make_local_task_id(source_id: str) -> str:
        """Return a stable Harbor task directory name for a Pinchbench task ID."""
        normalized = source_id.strip().replace("_", "-")
        normalized = re.sub(r"[^a-zA-Z0-9.-]+", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-").lower()
        return normalized or "pinchbench-task"

    def generate_task(self, source_id: str, local_task_id: str | None = None) -> Path:
        """Generate one task by Pinchbench source ID."""
        task_by_id = {task.source_id: task for task in self.tasks}
        task = task_by_id.get(source_id)
        if task is None:
            raise ValueError(f"Unknown Pinchbench task ID: {source_id}")
        output_dir = self.output_dir / (local_task_id or task.local_task_id)
        self._generate_task(task, output_dir)
        return output_dir

    def run(self) -> None:
        """Generate selected Pinchbench tasks."""
        selected_tasks = self._select_tasks()
        logger.info("Generating %d Pinchbench task(s)", len(selected_tasks))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for index, task in enumerate(selected_tasks, start=1):
            output_dir = self.output_dir / task.local_task_id
            logger.info(
                "Generating %s (%d/%d)", task.source_id, index, len(selected_tasks)
            )
            self._generate_task(task, output_dir)

    def _generate_task(self, task: PinchbenchTask, output_dir: Path) -> None:
        if output_dir.exists():
            if not self.overwrite:
                logger.info("Skipping existing task: %s", output_dir)
                return
            shutil.rmtree(output_dir)

        harness = self._build_harness()
        harness.convert(task, output_dir)
        if self.validate:
            _validate_harbor_task(output_dir)

    def _build_harness(self) -> ConversionHarness:
        kwargs = {
            "source_dir": self.source_dir,
            "skill_dir": self.skill_dir,
            "org": self.org,
            "judge_model": self.judge_model,
        }
        if self.harness_name == "direct":
            return DirectSkillHarness(**kwargs)
        if self.harness_name == "claude-code":
            return ClaudeCodeHarness(
                **kwargs,
                claude_bin=self.claude_bin,
                claude_model=self.claude_model,
                claude_config_dir=self.claude_config_dir,
                timeout_sec=self.conversion_timeout_sec,
                keep_workdirs=self.keep_agent_workdirs,
            )
        raise ValueError(f"Unsupported harness: {self.harness_name}")

    def _load_tasks(self) -> list[PinchbenchTask]:
        if not self.tasks_dir.exists():
            raise FileNotFoundError(
                f"Pinchbench tasks directory not found: {self.tasks_dir}. "
                "Initialize related-projects/external-tasks/skill first or pass --source-dir."
            )

        manifest = self._load_manifest()
        ordered_ids, category_map = _task_order_from_manifest(manifest, core=self.core)
        if ordered_ids:
            task_paths = []
            for task_id in ordered_ids:
                path = self.tasks_dir / f"{task_id}.md"
                if not path.exists():
                    raise FileNotFoundError(f"Manifest references missing task: {path}")
                task_paths.append(path)
        else:
            task_paths = sorted(
                path
                for path in self.tasks_dir.glob("task_*.md")
                if path.name != "TASK_TEMPLATE.md"
            )

        tasks = []
        for path in task_paths:
            metadata = _read_frontmatter(path)
            source_id = str(metadata.get("id") or path.stem)
            category = str(
                category_map.get(source_id) or metadata.get("category") or ""
            )
            tasks.append(
                PinchbenchTask(
                    source_id=source_id,
                    local_task_id=self.make_local_task_id(source_id),
                    name=str(metadata.get("name") or source_id),
                    category=category,
                    grading_type=str(metadata.get("grading_type") or "automated"),
                    path=path.resolve(),
                )
            )
        return tasks

    def _load_manifest(self) -> dict[str, Any]:
        manifest_path = self.tasks_dir / "manifest.yaml"
        if not manifest_path.exists():
            return {}
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Malformed Pinchbench manifest: {manifest_path}")
        return payload

    def _select_tasks(self) -> list[PinchbenchTask]:
        selected = self.tasks
        if self.task_ids:
            requested = set(self.task_ids)
            selected = [
                task
                for task in selected
                if task.source_id in requested or task.local_task_id in requested
            ]
            found = {task.source_id for task in selected} | {
                task.local_task_id for task in selected
            }
            missing = sorted(requested - found)
            if missing:
                raise ValueError(f"Unknown task id(s): {', '.join(missing)}")
        if self.limit is not None:
            selected = selected[: self.limit]
        return selected


def _task_order_from_manifest(
    manifest: dict[str, Any], *, core: bool
) -> tuple[list[str], dict[str, str]]:
    if core:
        core_ids = manifest.get("core") or []
        if not isinstance(core_ids, list):
            raise ValueError("Pinchbench manifest field 'core' must be a list")
        return [str(task_id) for task_id in core_ids], _category_map(manifest)

    categories = manifest.get("categories")
    if isinstance(categories, dict):
        run_first = manifest.get("run_first") or []
        if not isinstance(run_first, list):
            raise ValueError("Pinchbench manifest field 'run_first' must be a list")
        seen: set[str] = set()
        ordered: list[str] = []
        for task_id in [*run_first, *_flatten_categories(categories)]:
            task_id = str(task_id)
            if task_id not in seen:
                ordered.append(task_id)
                seen.add(task_id)
        return ordered, _category_map(manifest)

    tasks = manifest.get("tasks")
    if isinstance(tasks, list):
        return [str(task_id) for task_id in tasks], {}
    return [], {}


def _flatten_categories(categories: dict[Any, Any]) -> list[str]:
    task_ids: list[str] = []
    for ids in categories.values():
        if not isinstance(ids, list):
            continue
        task_ids.extend(str(task_id) for task_id in ids)
    return task_ids


def _category_map(manifest: dict[str, Any]) -> dict[str, str]:
    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        return {}
    mapping: dict[str, str] = {}
    for category, ids in categories.items():
        if not isinstance(ids, list):
            continue
        for task_id in ids:
            mapping[str(task_id)] = str(category)
    return mapping


def _read_frontmatter(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path}")
    payload = yaml.safe_load(match.group(1)) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML frontmatter in {path} must be a mapping")
    return payload


def _validate_harbor_task(task_dir: Path) -> None:
    from harbor.models.task.task import Task

    Task(task_dir)


def _source_label(task_path: Path) -> str:
    try:
        return str(task_path.relative_to(HARBOR_ROOT))
    except ValueError:
        return str(task_path)


def _shell_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _timeout_output_to_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
