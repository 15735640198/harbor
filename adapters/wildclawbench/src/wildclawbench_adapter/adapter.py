"""WildClawBench adapter.

This adapter converts WildClawBench Markdown tasks into Harbor task directories
while preserving the upstream runtime contract: agents work in /tmp_workspace,
task-visible files come from each workspace/*/exec directory, hidden ground truth
stays under tests/, and embedded Python graders run directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import textwrap

import yaml

logger = logging.getLogger(__name__)

ADAPTER_DIR = Path(__file__).resolve().parents[2]
HARBOR_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE_DIR = (
    HARBOR_ROOT / "related-projects" / "external-tasks" / "WildClawBench"
)
DEFAULT_BASE_IMAGE = "wildclawbench-ubuntu-openclaw:2026.5.27"
DEFAULT_BASE_PLATFORM = "linux/amd64"
RUN_STEP_NAME = "run"
WORKDIR = "/tmp_workspace"

DEFAULT_CATEGORY_ORDER = (
    "01_Productivity_Flow",
    "02_Code_Intelligence",
    "03_Social_Interaction",
    "04_Search_Retrieval",
    "05_Creative_Synthesis",
    "06_Safety_Alignment",
)

EMPTY_EXEC_WORKSPACE_TASK_IDS = frozenset(
    {
        "01_Productivity_Flow_task_1_arxiv_digest",
        "01_Productivity_Flow_task_9_scp_crawl",
    }
)

REQUIRED_WORKSPACE_FILES = {
    "02_Code_Intelligence_task_2_sam3_debug": ("test_sam3.py",),
}


@dataclass(frozen=True)
class WildClawBenchTask:
    """Normalized WildClawBench task metadata used by the adapter."""

    source_id: str
    local_task_id: str
    name: str
    category: str
    timeout_seconds: int
    modality: str
    prompt: str
    expected_behavior: str
    grading_criteria: str
    automated_checks: str
    workspace_path: str
    skills: tuple[str, ...]
    env_keys: tuple[str, ...]
    warmup: str
    path: Path


class WildClawBenchAdapter:
    """Convert WildClawBench tasks into Harbor tasks."""

    NAME = "wildclawbench"

    def __init__(
        self,
        output_dir: Path,
        *,
        source_dir: Path = DEFAULT_SOURCE_DIR,
        workspace_dir: Path | None = None,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        base_image: str = DEFAULT_BASE_IMAGE,
        base_platform: str = DEFAULT_BASE_PLATFORM,
        link_assets: bool = False,
        strict_assets: bool = True,
        org: str = "wildclawbench",
        verifier_model: str = "glm-5.1",
        validate: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self.source_dir = source_dir
        self.tasks_dir = source_dir / "tasks"
        self.skills_dir = source_dir / "skills"
        self.workspace_dir = workspace_dir or source_dir / "workspace"
        self.limit = limit
        self.overwrite = overwrite
        self.task_ids = task_ids
        self.base_image = base_image
        self.base_platform = base_platform
        self.link_assets = link_assets
        self.strict_assets = strict_assets
        self.org = org
        self.verifier_model = verifier_model
        self.validate = validate
        self.tasks = self._load_tasks()

    @staticmethod
    def make_local_task_id(source_id: str) -> str:
        """Return a stable Harbor task directory name for a WildClawBench task ID."""
        normalized = source_id.strip().replace("_", "-")
        normalized = re.sub(r"[^a-zA-Z0-9.-]+", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-").lower()
        return normalized or "wildclawbench-task"

    def generate_task(self, source_id: str, local_task_id: str | None = None) -> Path:
        """Generate one task by WildClawBench source ID."""
        task_by_id = {task.source_id: task for task in self.tasks}
        task = task_by_id.get(source_id)
        if task is None:
            raise ValueError(f"Unknown WildClawBench task ID: {source_id}")
        output_dir = self.output_dir / (local_task_id or task.local_task_id)
        self._generate_task(task, output_dir)
        return output_dir

    def run(self) -> None:
        """Generate selected WildClawBench tasks."""
        selected_tasks = self._select_tasks()
        logger.info("Generating %d WildClawBench task(s)", len(selected_tasks))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for index, task in enumerate(selected_tasks, start=1):
            output_dir = self.output_dir / task.local_task_id
            logger.info(
                "Generating %s (%d/%d)", task.source_id, index, len(selected_tasks)
            )
            self._generate_task(task, output_dir)

    def task_workspace_dir(self, task: WildClawBenchTask) -> Path:
        """Resolve a task's prepared upstream workspace directory."""
        raw = task.workspace_path.replace("\\", "/").strip()
        if not raw:
            raise ValueError(f"Task {task.source_id} has no Workspace Path")
        path = Path(raw)
        if path.is_absolute():
            return path
        parts = path.parts
        if parts and parts[0] == "workspace":
            return (self.workspace_dir / Path(*parts[1:])).resolve()
        return (self.source_dir / path).resolve()

    def _generate_task(self, task: WildClawBenchTask, output_dir: Path) -> None:
        if output_dir.exists():
            if not self.overwrite:
                logger.info("Skipping existing task: %s", output_dir)
                return
            shutil.rmtree(output_dir)

        self._build_harbor_task(task, output_dir)
        if self.validate:
            _validate_harbor_task(output_dir)

    def _build_harbor_task(self, task: WildClawBenchTask, output_dir: Path) -> None:
        environment_dir = output_dir / "environment"
        workspace_out = environment_dir / "workspace"
        root_tests_dir = output_dir / "tests"
        step_dir = output_dir / "steps" / RUN_STEP_NAME
        step_tests_dir = step_dir / "tests"
        step_workdir = step_dir / "workdir"

        workspace_out.mkdir(parents=True)
        root_tests_dir.mkdir(parents=True)
        step_tests_dir.mkdir(parents=True)
        step_workdir.mkdir(parents=True)

        task_workspace = self.task_workspace_dir(task)
        has_gt = self._stage_workspace(
            task, task_workspace, workspace_out, root_tests_dir
        )
        copied_skills = self._stage_skills(task, environment_dir / "skills")

        write_text(
            output_dir / "task.toml", self._render_task_toml(task, copied_skills)
        )
        write_text(
            environment_dir / "Dockerfile", self._render_dockerfile(copied_skills)
        )
        write_text(
            step_dir / "instruction.md", ensure_newline(self._render_instruction(task))
        )
        write_text(
            step_workdir / "setup.sh",
            self._render_setup_script(task),
            executable=True,
        )
        write_text(step_tests_dir / "test.sh", STEP_TEST_SH, executable=True)
        write_text(
            root_tests_dir / "grade_source.py",
            extract_python_code(task.automated_checks),
        )
        write_text(
            root_tests_dir / "run_wildclawbench_grade.py",
            WILDCLAWBENCH_GRADE_RUNNER,
            executable=True,
        )

        if has_gt:
            logger.debug("Staged hidden gt for %s", task.source_id)

    def _stage_workspace(
        self,
        task: WildClawBenchTask,
        task_workspace: Path,
        workspace_out: Path,
        root_tests_dir: Path,
    ) -> bool:
        exec_dir = task_workspace / "exec"
        tmp_dir = task_workspace / "tmp"
        gt_dir = task_workspace / "gt"

        if not exec_dir.exists():
            if task.source_id in EMPTY_EXEC_WORKSPACE_TASK_IDS:
                logger.info(
                    "No upstream exec/ for %s; generating an empty agent workspace",
                    task.source_id,
                )
            elif self.strict_assets:
                raise FileNotFoundError(_missing_assets_message(task, task_workspace))
            else:
                logger.warning(
                    "Missing exec/ for %s; generating an empty agent workspace",
                    task.source_id,
                )
        elif not exec_dir.is_dir():
            raise NotADirectoryError(f"Expected exec/ directory: {exec_dir}")
        else:
            self._validate_required_workspace_files(task, exec_dir)
            copy_dir_contents(exec_dir, workspace_out, link_files=self.link_assets)

        if tmp_dir.exists():
            if not tmp_dir.is_dir():
                raise NotADirectoryError(f"Expected tmp/ directory: {tmp_dir}")
            copy_dir_contents(
                tmp_dir, workspace_out / "tmp", link_files=self.link_assets
            )

        if not gt_dir.exists():
            if self.strict_assets and automated_checks_require_gt(task):
                raise FileNotFoundError(_missing_gt_message(task, task_workspace))
            return False
        if not gt_dir.is_dir():
            raise NotADirectoryError(f"Expected gt/ directory: {gt_dir}")
        if self.strict_assets and automated_checks_require_gt(task):
            gt_files = [path for path in gt_dir.rglob("*") if path.is_file()]
            if not gt_files:
                raise FileNotFoundError(_missing_gt_message(task, task_workspace))
        copy_tree(gt_dir, root_tests_dir / "gt", link_files=self.link_assets)
        return True

    def _validate_required_workspace_files(
        self, task: WildClawBenchTask, exec_dir: Path
    ) -> None:
        if not self.strict_assets:
            return
        missing = [
            rel_path
            for rel_path in REQUIRED_WORKSPACE_FILES.get(task.source_id, ())
            if not (exec_dir / rel_path).exists()
        ]
        if missing:
            raise FileNotFoundError(
                _missing_required_workspace_files_message(task, exec_dir, missing)
            )

    def _stage_skills(self, task: WildClawBenchTask, skills_out: Path) -> bool:
        copied_any = False
        seen_dest_names: set[str] = set()
        for skill in task.skills:
            src_rel = skill.replace("\\", "/").strip("/")
            if not src_rel:
                continue
            source = self.skills_dir / src_rel
            dest_name = Path(src_rel).name
            if dest_name in seen_dest_names:
                logger.warning(
                    "Duplicate flattened skill target %s in %s; skipping %s",
                    dest_name,
                    task.source_id,
                    skill,
                )
                continue
            seen_dest_names.add(dest_name)
            if not source.exists():
                logger.warning(
                    "Skill %s requested by %s was not found under %s; skipping",
                    skill,
                    task.source_id,
                    self.skills_dir,
                )
                continue
            dest = skills_out / dest_name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source, dest, symlinks=True)
            copied_any = True
        return copied_any

    def _render_instruction(self, task: WildClawBenchTask) -> str:
        prefix = (
            "You are an expert in a restricted, non-interactive environment. "
            f"Solve the task efficiently before the timeout ({task.timeout_seconds}s). "
            "Run all processes in the foreground unless a service must stay running. "
            "Provide a complete, functional solution in a single pass with no placeholders."
        )
        return f"{prefix}\n\n{task.prompt.strip()}\n"

    def _render_task_toml(self, task: WildClawBenchTask, copied_skills: bool) -> str:
        timeout = float(max(task.timeout_seconds, 120))
        verifier_timeout = float(max(task.timeout_seconds, 300))
        tags = [
            "wildclawbench",
            task.category,
            task.modality,
            task.source_id,
        ]
        source_label = _source_label(task.path)
        lines = [
            'schema_version = "1.1"',
            f"source = {toml_string(source_label)}",
            'multi_step_reward_strategy = "final"',
            "",
            "[task]",
            f"name = {toml_string(f'{self.org}/{task.local_task_id}')}",
            f"description = {toml_string(task.name)}",
            "authors = []",
            f"keywords = {toml_array(tags)}",
            "",
            "[metadata]",
            f"category = {toml_string(task.category)}",
            'difficulty = "unknown"',
            f"tags = {toml_array(tags)}",
            f"wildclawbench_id = {toml_string(task.source_id)}",
            f"wildclawbench_category = {toml_string(task.category)}",
            f"wildclawbench_modality = {toml_string(task.modality)}",
            "",
            "[verifier]",
            f"timeout_sec = {verifier_timeout:.1f}",
            "",
            "[agent]",
            f"timeout_sec = {timeout:.1f}",
            "",
            "[environment]",
            "build_timeout_sec = 1800.0",
            "cpus = 2",
            "memory_mb = 8192",
            "storage_mb = 51200",
            "gpus = 0",
            "allow_internet = true",
            "mcp_servers = []",
            f"workdir = {toml_string(WORKDIR)}",
        ]
        if copied_skills:
            lines.append('skills_dir = "/skills"')

        lines.extend(
            [
                "",
                "[verifier.env]",
                'ANTHROPIC_API_KEY = "${ANTHROPIC_API_KEY:-}"',
                'ANTHROPIC_BASE_URL = "${ANTHROPIC_BASE_URL:-}"',
                f"MODEL_NAME = {toml_string(self.verifier_model)}",
                'OPENROUTER_API_KEY = "${OPENROUTER_API_KEY:-}"',
                'OPENROUTER_BASE_URL = "${OPENROUTER_BASE_URL:-}"',
                'JUDGE_MODEL = "${JUDGE_MODEL:-}"',
                "",
                "[environment.env]",
            ]
        )
        for key in sorted(_environment_env_keys(task.env_keys)):
            lines.append(f"{key} = {toml_string(env_template_with_blank_default(key))}")

        lines.extend(
            [
                "",
                "[solution.env]",
                "",
                "[[steps]]",
                f"name = {toml_string(RUN_STEP_NAME)}",
                "",
                "[steps.agent]",
                f"timeout_sec = {timeout:.1f}",
                "",
                "[steps.verifier]",
                f"timeout_sec = {verifier_timeout:.1f}",
            ]
        )
        return "\n".join(lines) + "\n"

    def _render_dockerfile(self, copied_skills: bool) -> str:
        skills_block = (
            "COPY skills/ /skills/" if copied_skills else "RUN mkdir -p /skills"
        )
        from_line = f"FROM {self.base_image}"
        if self.base_platform:
            from_line = f"FROM --platform={self.base_platform} {self.base_image}"
        return textwrap.dedent(
            f"""\
            {from_line}

            RUN mkdir -p {WORKDIR} \\
                && rm -rf /app \\
                && ln -s {WORKDIR} /app

            WORKDIR {WORKDIR}
            COPY workspace/ {WORKDIR}/
            {skills_block}
            RUN chmod -R u+rwX {WORKDIR} /skills || true
            """
        )

    def _render_setup_script(self, task: WildClawBenchTask) -> str:
        lines = [
            "#!/bin/bash",
            "set -euo pipefail",
            f"cd {shlex.quote(WORKDIR)}",
            "mkdir -p results",
        ]
        warmup_lines = [
            line.strip()
            for line in task.warmup.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not warmup_lines:
            lines.append("exit 0")
            return "\n".join(lines) + "\n"

        lines.append("mkdir -p /tmp/wildclawbench-warmup")
        for index, command in enumerate(warmup_lines, start=1):
            if command.endswith("&"):
                background_command = command[:-1].strip()
                log_path = f"/tmp/wildclawbench-warmup/{index}.log"
                lines.append(
                    "nohup /bin/bash -lc "
                    f"{shlex.quote(background_command)} "
                    f"> {shlex.quote(log_path)} 2>&1 < /dev/null &"
                )
            else:
                lines.append(command)
        return "\n".join(lines) + "\n"

    def _load_tasks(self) -> list[WildClawBenchTask]:
        if not self.tasks_dir.exists():
            raise FileNotFoundError(
                f"WildClawBench tasks directory not found: {self.tasks_dir}. "
                "Initialize related-projects/external-tasks/WildClawBench first "
                "or pass --source-dir."
            )

        task_paths = sorted(
            (
                path
                for path in self.tasks_dir.glob("*/*task_*.md")
                if path.name != "task0_template.md"
            ),
            key=_task_sort_key,
        )
        return [load_wildclawbench_task(path) for path in task_paths]

    def _select_tasks(self) -> list[WildClawBenchTask]:
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


def load_wildclawbench_task(task_md: Path) -> WildClawBenchTask:
    content = task_md.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {task_md}")

    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"YAML frontmatter in {task_md} must be a mapping")
    sections = parse_sections(match.group(2))

    source_id = str(metadata.get("id") or task_md.stem)
    prompt = sections.get("Prompt", "").strip()
    workspace_path = strip_codeblock(sections.get("Workspace Path", "")).strip()
    if not prompt:
        raise ValueError(f"Missing ## Prompt in {task_md}")
    if not workspace_path:
        raise ValueError(f"Missing ## Workspace Path in {task_md}")

    return WildClawBenchTask(
        source_id=source_id,
        local_task_id=WildClawBenchAdapter.make_local_task_id(source_id),
        name=str(metadata.get("name") or source_id),
        category=str(metadata.get("category") or task_md.parent.name),
        timeout_seconds=int(metadata.get("timeout_seconds") or 300),
        modality=str(metadata.get("modality") or "unknown"),
        prompt=prompt,
        expected_behavior=sections.get("Expected Behavior", "").strip(),
        grading_criteria=sections.get("Grading Criteria", "").strip(),
        automated_checks=sections.get("Automated Checks", "").strip(),
        workspace_path=workspace_path,
        skills=tuple(parse_codeblock_lines(sections.get("Skills", ""))),
        env_keys=tuple(parse_codeblock_lines(sections.get("Env", ""))),
        warmup=strip_codeblock(sections.get("Warmup", "")).strip(),
        path=task_md.resolve(),
    )


def parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        header = re.match(r"^##\s+(.+?)\s*$", line)
        if header:
            current = header.group(1)
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def strip_codeblock(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"^```[^\n]*\n?", "", value)
    value = re.sub(r"\n?```$", "", value)
    return value.strip()


def parse_codeblock_lines(raw: str) -> list[str]:
    value = strip_codeblock(raw)
    return [
        line.strip()
        for line in value.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def extract_python_code(section_text: str) -> str:
    match = re.search(r"```python\s*(.*?)\s*```", section_text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    stripped = strip_codeblock(section_text)
    if "def grade" not in stripped:
        raise ValueError("Automated Checks section does not contain a grade function")
    return stripped.rstrip() + "\n"


def copy_tree(source: Path, dest: Path, *, link_files: bool = False) -> None:
    shutil.copytree(
        source,
        dest,
        symlinks=True,
        copy_function=(hardlink_or_copy_file if link_files else shutil.copy2),
    )


def copy_dir_contents(source: Path, dest: Path, *, link_files: bool = False) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = dest / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            copy_tree(child, target, link_files=link_files)
        else:
            if target.exists():
                target.unlink()
            if link_files:
                hardlink_or_copy_file(child, target)
            else:
                shutil.copy2(child, target, follow_symlinks=False)


def hardlink_or_copy_file(source: str | Path, dest: str | Path) -> Path:
    source_path = Path(source)
    dest_path = Path(dest)
    if source_path.is_symlink():
        shutil.copy2(source_path, dest_path, follow_symlinks=False)
        return dest_path
    try:
        os.link(source_path, dest_path)
    except OSError as exc:
        raise OSError(
            "Failed to hardlink WildClawBench asset. "
            "Use copy mode or place --output-dir on the same filesystem as "
            f"--workspace-dir. Source: {source_path}; destination: {dest_path}"
        ) from exc
    return dest_path


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_newline(value: str) -> str:
    return value.rstrip() + "\n"


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(toml_string(str(value)) for value in values) + "]"


def env_template_with_blank_default(key: str) -> str:
    return f"${{{key}:-}}"


def _environment_env_keys(task_env_keys: Iterable[str]) -> set[str]:
    keys = {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "JUDGE_MODEL",
        "MODEL_NAME",
        "BRAVE_API_KEY",
    }
    keys.update(
        key for key in task_env_keys if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key)
    )
    return keys


def _source_label(task_path: Path) -> str:
    try:
        return str(task_path.relative_to(HARBOR_ROOT))
    except ValueError:
        return str(task_path)


def _task_sort_key(path: Path) -> tuple[int, int, str]:
    category = path.parent.name
    try:
        category_index = DEFAULT_CATEGORY_ORDER.index(category)
    except ValueError:
        category_index = len(DEFAULT_CATEGORY_ORDER)
    match = re.search(r"_task_(\d+)", path.name)
    task_num = int(match.group(1)) if match else 10_000
    return (category_index, task_num, path.name)


def _missing_assets_message(task: WildClawBenchTask, task_workspace: Path) -> str:
    return (
        f"Prepared WildClawBench workspace missing for {task.source_id}: "
        + f"{task_workspace / 'exec'}\n\n"
        + _wildclawbench_prepare_guidance()
        + "Then rerun the adapter, or pass --no-strict-assets for structural smoke tests."
    )


def _missing_gt_message(task: WildClawBenchTask, task_workspace: Path) -> str:
    return (
        f"Prepared WildClawBench hidden gt/ data missing or empty for "
        f"{task.source_id}: {task_workspace / 'gt'}\n\n"
        "This task's embedded grader references gt/ data, so the converted task "
        "would fail verification.\n\n"
        f"{_wildclawbench_prepare_guidance()}"
        "Then rerun the adapter."
    )


def _missing_required_workspace_files_message(
    task: WildClawBenchTask, exec_dir: Path, missing: list[str]
) -> str:
    missing_lines = "\n".join(f"  - {rel_path}" for rel_path in missing)
    return (
        f"Prepared WildClawBench workspace incomplete for {task.source_id}: "
        f"{exec_dir}\n\n"
        f"Missing required file(s):\n{missing_lines}\n\n"
        f"{_wildclawbench_prepare_guidance()}"
        "Then rerun the adapter."
    )


def _wildclawbench_prepare_guidance() -> str:
    return (
        "Download and prepare upstream data first:\n"
        "  hf download internlm/WildClawBench workspace --repo-type dataset "
        "--local-dir related-projects/external-tasks/WildClawBench\n"
        "  bash related-projects/external-tasks/WildClawBench/script/prepare.sh\n\n"
        "If the workspace was partially downloaded, force a re-download of the "
        "affected task path before running prepare.sh again.\n\n"
    )


def automated_checks_require_gt(task: WildClawBenchTask) -> bool:
    checks = task.automated_checks
    return bool(
        re.search(r'["\']/tmp_workspace/gt(?:/|["\'])', checks)
        or re.search(r'["\']gt/[^"\']+', checks)
        or re.search(r'/\s*["\']gt["\']', checks)
    )


def _validate_harbor_task(task_dir: Path) -> None:
    from harbor.models.task.task import Task

    Task(task_dir)


STEP_TEST_SH = """\
#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
python3 /tests/run_wildclawbench_grade.py
"""


WILDCLAWBENCH_GRADE_RUNNER = r"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import traceback
from typing import Any

WORKSPACE = Path("/tmp_workspace")
REWARD_PATH = Path("/logs/verifier/reward.json")
ERROR_PATH = Path("/logs/verifier/error.txt")
GRADE_SOURCE_PATH = Path("/tests/grade_source.py")
TESTS_GT_DIR = Path("/tests/gt")
WORKSPACE_GT_DIR = WORKSPACE / "gt"


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def apply_env_aliases() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")
    if not os.environ.get("OPENROUTER_BASE_URL"):
        os.environ["OPENROUTER_BASE_URL"] = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not os.environ.get("JUDGE_MODEL"):
        os.environ["JUDGE_MODEL"] = os.environ.get("MODEL_NAME", "glm-5.1")


def stage_hidden_gt() -> None:
    if not TESTS_GT_DIR.exists():
        return
    if WORKSPACE_GT_DIR.exists():
        shutil.rmtree(WORKSPACE_GT_DIR)
    shutil.copytree(TESTS_GT_DIR, WORKSPACE_GT_DIR, symlinks=True)


def safe_json_loads(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except Exception:
        return None


def parse_json_lines(raw: str) -> list[Any]:
    rows: list[Any] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = safe_json_loads(line)
        if parsed is not None:
            rows.append(parsed)
    return rows


def read_transcript_file(path: Path) -> list[Any]:
    if not path.exists() or not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    parsed = safe_json_loads(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("transcript", "events", "messages", "trajectory", "chat"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        return [parsed]
    return parse_json_lines(raw)


def transcript_candidates() -> list[Path]:
    explicit = [
        Path("/root/.openclaw/agents/main/sessions/chat.jsonl"),
        Path("/logs/agent/openclaw-session.jsonl"),
        Path("/claude_code/log/chat.json"),
    ]
    candidates: list[Path] = []
    candidates.extend(explicit)
    for root in (Path("/logs/agent"), Path("/logs")):
        if not root.exists():
            continue
        for pattern in ("*.jsonl", "*.json"):
            for path in sorted(root.rglob(pattern)):
                if path.name.endswith(".trajectory.jsonl"):
                    continue
                candidates.append(path)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def load_transcript() -> list[Any]:
    for candidate in transcript_candidates():
        loaded = read_transcript_file(candidate)
        if loaded:
            return loaded
    return []


def sync_compat_transcript(transcript: list[Any]) -> None:
    if not transcript:
        return
    jsonl = "\n".join(json.dumps(item, ensure_ascii=False) for item in transcript) + "\n"
    openclaw_path = Path("/root/.openclaw/agents/main/sessions/chat.jsonl")
    openclaw_path.parent.mkdir(parents=True, exist_ok=True)
    openclaw_path.write_text(jsonl, encoding="utf-8")

    claude_path = Path("/claude_code/log/chat.json")
    claude_path.parent.mkdir(parents=True, exist_ok=True)
    claude_path.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")


def normalize_scores(raw_scores: Any) -> dict[str, float]:
    if not isinstance(raw_scores, dict):
        return {}
    return {
        str(key): clamp01(value)
        for key, value in raw_scores.items()
        if isinstance(value, (int, float))
    }


def average_numeric(scores: dict[str, float]) -> float:
    values = list(scores.values())
    if not values:
        return 0.0
    return clamp01(sum(values) / len(values))


def build_reward_payload(raw_scores: Any) -> dict[str, float]:
    scores = normalize_scores(raw_scores)
    reward = scores.get("overall_score", average_numeric(scores))
    payload: dict[str, float] = {"reward": clamp01(reward)}
    for key, value in scores.items():
        safe_key = "wildclawbench.reward" if key == "reward" else key
        payload[safe_key] = clamp01(value)
    if "overall_score" not in payload:
        payload["overall_score"] = payload["reward"]
    return payload


def write_reward(payload: dict[str, float]) -> None:
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


def write_error_reward(exc: BaseException) -> None:
    traceback_text = "".join(traceback.format_exception(exc))
    ERROR_PATH.parent.mkdir(parents=True, exist_ok=True)
    ERROR_PATH.write_text(traceback_text, encoding="utf-8")
    print(traceback_text)
    write_reward({"reward": 0.0, "overall_score": 0.0, "verifier_error": 1.0})


def main() -> None:
    try:
        apply_env_aliases()
        stage_hidden_gt()
        transcript = load_transcript()
        sync_compat_transcript(transcript)
        namespace = runpy.run_path(str(GRADE_SOURCE_PATH))
        grade = namespace.get("grade")
        if not callable(grade):
            raise RuntimeError("grade_source.py does not define a callable grade function")
        raw_scores = grade(transcript=transcript, workspace_path=str(WORKSPACE))
        write_reward(build_reward_payload(raw_scores))
    except BaseException as exc:
        write_error_reward(exc)


if __name__ == "__main__":
    main()
"""
