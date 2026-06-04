"""ClawBench adapter.

This adapter converts the ClawBench Core public manifest into Harbor task
directories. Generated tasks are self-contained: public assets are copied into
the agent workspace and the adapter-local verifier runtime is copied into
``tests/``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import textwrap
import zlib
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ADAPTER_DIR = Path(__file__).resolve().parents[2]
HARBOR_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE_DIR = HARBOR_ROOT / "related-projects" / "external-tasks" / "clawbench"
DEFAULT_TASKS_ROOT = "tasks-public"
DEFAULT_MANIFEST = "tasks-public/MANIFEST.yaml"
DEFAULT_BASE_IMAGE = (
    "ghcr.io/openclaw/openclaw@sha256:"
    "2e32f4f2e4f653f12d5dc6e5c93cc71e60f49d1dfaf061b18e53c3e61a38fb48"
)
DEFAULT_BASE_PLATFORM = "linux/amd64"
DEFAULT_JUDGE_MODEL = "glm-5.1"
WORKDIR = "/workspace"
RUN_STEP_NAME = "run"
RUNTIME_FILENAME = "clawbench_verifier_runtime.py"


@dataclass(frozen=True)
class ClawBenchTask:
    """Normalized ClawBench task metadata used by the adapter."""

    source_id: str
    local_task_id: str
    name: str
    tier: str
    family: str
    capabilities: tuple[str, ...]
    subsets: tuple[str, ...]
    timeout_seconds: int
    asset_packs: tuple[str, ...]
    yaml_path: Path
    manifest_entry: dict[str, Any]
    definition: dict[str, Any]


class ClawBenchAdapter:
    """Convert ClawBench Core public tasks into Harbor tasks."""

    NAME = "clawbench"

    def __init__(
        self,
        output_dir: Path,
        *,
        source_dir: Path = DEFAULT_SOURCE_DIR,
        tasks_root: str = DEFAULT_TASKS_ROOT,
        manifest: str | Path = DEFAULT_MANIFEST,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        base_image: str = DEFAULT_BASE_IMAGE,
        base_platform: str = DEFAULT_BASE_PLATFORM,
        link_assets: bool = False,
        org: str = "clawbench",
        judge_model: str = DEFAULT_JUDGE_MODEL,
        validate: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self.source_dir = source_dir
        self.tasks_root = tasks_root
        self.tasks_dir = source_dir / tasks_root
        self.manifest_path = (
            manifest if isinstance(manifest, Path) else source_dir / manifest
        )
        self.limit = limit
        self.overwrite = overwrite
        self.task_ids = task_ids
        self.base_image = base_image
        self.base_platform = base_platform
        self.link_assets = link_assets
        self.org = org
        self.judge_model = judge_model
        self.validate = validate
        self.tasks = self._load_tasks()

    @staticmethod
    def make_local_task_id(source_id: str) -> str:
        normalized = source_id.strip().replace("_", "-")
        normalized = re.sub(r"[^a-zA-Z0-9.-]+", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-").lower()
        return normalized or "clawbench-task"

    def generate_task(self, source_id: str, local_task_id: str | None = None) -> Path:
        task_by_id = {task.source_id: task for task in self.tasks}
        task_by_id.update({task.local_task_id: task for task in self.tasks})
        task = task_by_id.get(source_id)
        if task is None:
            raise ValueError(f"Unknown ClawBench task ID: {source_id}")
        output_dir = self.output_dir / (local_task_id or task.local_task_id)
        self._generate_task(task, output_dir)
        return output_dir

    def run(self) -> None:
        selected = self._select_tasks()
        logger.info("Generating %d ClawBench task(s)", len(selected))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for index, task in enumerate(selected, start=1):
            logger.info("Generating %s (%d/%d)", task.source_id, index, len(selected))
            self._generate_task(task, self.output_dir / task.local_task_id)

    def _generate_task(self, task: ClawBenchTask, output_dir: Path) -> None:
        if output_dir.exists():
            if not self.overwrite:
                logger.info("Skipping existing task: %s", output_dir)
                return
            shutil.rmtree(output_dir)
        self._build_harbor_task(task, output_dir)
        if self.validate:
            _validate_harbor_task(output_dir)

    def _build_harbor_task(self, task: ClawBenchTask, output_dir: Path) -> None:
        environment_dir = output_dir / "environment"
        workspace_dir = environment_dir / "workspace"
        tests_dir = output_dir / "tests"
        workspace_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        runtime_values = self._runtime_values_for(task)
        task_definition = _render_value(task.definition, runtime_values)

        self._stage_assets(task, workspace_dir)
        write_text(
            output_dir / "task.toml", self._render_task_toml(task, runtime_values)
        )
        write_text(environment_dir / "Dockerfile", self._render_dockerfile())
        write_json(tests_dir / "clawbench_task.json", task_definition)
        shutil.copy2(
            Path(__file__).with_name("verifier_runtime.py"),
            tests_dir / RUNTIME_FILENAME,
        )

        phases = _normalized_phases(task_definition)
        if len(phases) == 1:
            step_name = RUN_STEP_NAME
            step_dir = output_dir / "steps" / step_name
            self._write_step(task_definition, phases[0], step_dir, final=True)
        else:
            for index, phase in enumerate(phases):
                final = index == len(phases) - 1
                step_dir = output_dir / "steps" / _safe_step_name(str(phase["name"]))
                self._write_step(task_definition, phase, step_dir, final=final)

    def _write_step(
        self,
        task_definition: dict[str, Any],
        phase: dict[str, Any],
        step_dir: Path,
        *,
        final: bool,
    ) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        write_text(
            step_dir / "instruction.md",
            self._render_instruction(task_definition, phase),
        )
        write_text(
            step_dir / "workdir" / "setup.sh",
            self._render_setup(task_definition),
            executable=True,
        )
        if final:
            write_text(step_dir / "tests" / "test.sh", FINAL_TEST_SH, executable=True)
        else:
            write_text(
                step_dir / "tests" / "test.sh", PLACEHOLDER_TEST_SH, executable=True
            )

    def _stage_assets(self, task: ClawBenchTask, workspace_dir: Path) -> None:
        assets_root = self.tasks_dir / "assets"
        for pack in task.asset_packs:
            source = assets_root / pack
            if not source.is_dir():
                raise FileNotFoundError(f"ClawBench asset pack not found: {source}")
            copy_dir_contents(source, workspace_dir, link_files=self.link_assets)

    def _render_task_toml(
        self, task: ClawBenchTask, runtime_values: dict[str, Any]
    ) -> str:
        timeout = float(max(task.timeout_seconds, 120))
        verifier_timeout = float(max(task.timeout_seconds, 300))
        tags = ["clawbench", task.tier, task.family, *task.capabilities, *task.subsets]
        phases = _normalized_phases(task.definition)
        multi_step = len(phases) > 1
        lines = [
            'schema_version = "1.2"',
            f"source = {toml_string(_source_label(task.yaml_path))}",
        ]
        if multi_step:
            lines.append('multi_step_reward_strategy = "final"')
        lines.extend(
            [
                "",
                "[task]",
                f"name = {toml_string(f'{self.org}/{task.local_task_id}')}",
                f"description = {toml_string(task.name)}",
                "authors = []",
                f"keywords = {toml_array(tags)}",
                "",
                "[metadata]",
                f"difficulty = {toml_string(task.tier)}",
                f"category = {toml_string(task.family)}",
                f"tags = {toml_array(tags)}",
                f"clawbench_id = {toml_string(task.source_id)}",
                f"clawbench_tier = {toml_string(task.tier)}",
                f"clawbench_family = {toml_string(task.family)}",
                f"clawbench_pool = {toml_string(str(task.definition.get('pool', '')))}",
                f"clawbench_subsets = {toml_array(task.subsets)}",
                f"clawbench_capabilities = {toml_array(task.capabilities)}",
                f"clawbench_release = {toml_string(str(self._manifest().get('release', '')))}",
                f"clawbench_benchmark_version = {toml_string(str(self._manifest().get('benchmark_version', '')))}",
                "",
                "[verifier]",
                f"timeout_sec = {verifier_timeout:.1f}",
                "",
                "[verifier.env]",
                'ANTHROPIC_API_KEY = "${ANTHROPIC_API_KEY:-}"',
                'ANTHROPIC_BASE_URL = "${ANTHROPIC_BASE_URL:-}"',
                'OPENAI_API_KEY = "${OPENAI_API_KEY:-}"',
                'OPENAI_BASE_URL = "${OPENAI_BASE_URL:-}"',
                'OPENROUTER_API_KEY = "${OPENROUTER_API_KEY:-}"',
                'OPENROUTER_BASE_URL = "${OPENROUTER_BASE_URL:-}"',
                f"MODEL_NAME = {toml_string(f'${{MODEL_NAME:-{self.judge_model}}}')}",
                'JUDGE_MODEL = "${JUDGE_MODEL:-}"',
                'JUDGE_API_FORMAT = "${JUDGE_API_FORMAT:-auto}"',
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
                "",
                "[environment.env]",
                'ANTHROPIC_API_KEY = "${ANTHROPIC_API_KEY:-}"',
                'ANTHROPIC_BASE_URL = "${ANTHROPIC_BASE_URL:-}"',
                'OPENAI_API_KEY = "${OPENAI_API_KEY:-}"',
                'OPENAI_BASE_URL = "${OPENAI_BASE_URL:-}"',
                'OPENROUTER_API_KEY = "${OPENROUTER_API_KEY:-}"',
                'OPENROUTER_BASE_URL = "${OPENROUTER_BASE_URL:-}"',
                "",
                "[solution.env]",
            ]
        )
        for phase in phases:
            step_name = (
                _safe_step_name(str(phase["name"])) if multi_step else RUN_STEP_NAME
            )
            phase_timeout = float(phase.get("timeout_seconds") or task.timeout_seconds)
            lines.extend(
                [
                    "",
                    "[[steps]]",
                    f"name = {toml_string(step_name)}",
                    "",
                    "[steps.agent]",
                    f"timeout_sec = {max(phase_timeout, 120.0):.1f}",
                    "",
                    "[steps.verifier]",
                    f"timeout_sec = {verifier_timeout:.1f}",
                ]
            )
        return "\n".join(lines) + "\n"

    def _render_dockerfile(self) -> str:
        from_line = f"FROM {self.base_image}"
        if self.base_platform:
            from_line = f"FROM --platform={self.base_platform} {self.base_image}"
        return textwrap.dedent(
            f"""\
            {from_line}

            USER root
            HEALTHCHECK NONE
            ENV DEBIAN_FRONTEND=noninteractive
            RUN apt-get update \\
                && apt-get install -y python3-pip python-is-python3 curl \\
                && rm -rf /var/lib/apt/lists/*
            RUN python3 -m pip install --break-system-packages --no-cache-dir pytest
            ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
            ENV NODE_PATH={WORKDIR}/node_modules
            RUN if command -v npx >/dev/null 2>&1; then \\
                    cd /tmp && npx -y playwright@1.59.1 install --with-deps chromium && \\
                    CHROME_PATH="$(find /ms-playwright -path '*/chrome' -type f | sort | head -n 1)" && \\
                    if [ -x "$CHROME_PATH" ]; then ln -sf "$CHROME_PATH" /usr/bin/chromium; fi; \\
                fi
            RUN mkdir -p {WORKDIR} /logs/agent /logs/verifier \\
                && rm -rf /app \\
                && ln -s {WORKDIR} /app \\
                && chmod -R 777 {WORKDIR} /logs
            RUN if command -v npm >/dev/null 2>&1; then \\
                    npm install --prefix {WORKDIR} --omit=dev --no-audit --no-fund playwright@1.59.1; \\
                fi
            WORKDIR {WORKDIR}
            COPY workspace/ {WORKDIR}/
            """
        )

    def _render_instruction(
        self, task_definition: dict[str, Any], phase: dict[str, Any]
    ) -> str:
        turns = (phase.get("user") or {}).get("turns") or []
        lines = [
            "Complete this ClawBench task in the current workspace.",
            "Use the available tools to inspect, edit, and verify your work before finishing.",
            "",
        ]
        for index, turn in enumerate(turns, start=1):
            message = str(turn.get("message", "")).strip()
            if not message:
                continue
            if index == 1:
                lines.append(message)
            else:
                lines.extend(["", f"Follow-up instruction {index}: {message}"])
                conditions = _turn_conditions(turn)
                if conditions:
                    lines.append(f"Original ClawBench condition: {conditions}.")
        return "\n".join(lines).rstrip() + "\n"

    def _render_setup(self, task_definition: dict[str, Any]) -> str:
        services = (task_definition.get("setup") or {}).get("background_services") or []
        lines = [
            "#!/bin/bash",
            "set -euo pipefail",
            f"cd {WORKDIR}",
            "mkdir -p .clawbench-services",
        ]
        if not services:
            lines.append("exit 0")
            return "\n".join(lines) + "\n"

        for spec in services:
            name = str(spec["name"])
            port = int(spec["port"])
            command = str(spec["command"])
            cwd = str(spec.get("cwd") or ".")
            port_env = str(spec.get("port_env") or "PORT")
            ready_path = str(spec.get("ready_path") or "")
            ready_status = int(spec.get("ready_status") or 200)
            timeout = int(spec.get("startup_timeout_seconds") or 20)
            log_path = f".clawbench-services/{name}.log"
            lines.extend(
                [
                    f"(cd {shell_quote(cwd)} && {port_env}={port} nohup /bin/bash -lc {shell_quote(command)} > {shell_quote(log_path)} 2>&1 < /dev/null & echo $! > {shell_quote(f'.clawbench-services/{name}.pid')})",
                    "python3 - <<'PY'",
                    "import sys, time, urllib.request",
                    f"url = 'http://127.0.0.1:{port}/{ready_path.lstrip('/')}'"
                    if ready_path
                    else "url = ''",
                    f"deadline = time.time() + {timeout}",
                    f"expected = {ready_status}",
                    "while time.time() < deadline:",
                    "    if not url:",
                    "        sys.exit(0)",
                    "    try:",
                    "        with urllib.request.urlopen(url, timeout=2) as response:",
                    "            if response.status == expected:",
                    "                sys.exit(0)",
                    "    except Exception:",
                    "        pass",
                    "    time.sleep(0.2)",
                    "raise SystemExit(f'timed out waiting for {url}')",
                    "PY",
                ]
            )
        return "\n".join(lines) + "\n"

    def _runtime_values_for(self, task: ClawBenchTask) -> dict[str, Any]:
        values: dict[str, Any] = {
            "workspace": WORKDIR,
            "workspace_name": "workspace",
            "repo_root": WORKDIR,
            "benchmark_node_path": "/workspace/node_modules",
            "openclaw_node_path": "/openclaw/node_modules",
            "python_exe": "python3",
            "task_id": task.source_id,
            "prompt_variant": "clear",
        }
        services = (task.definition.get("setup") or {}).get("background_services") or []
        for spec in services:
            name = str(spec["name"])
            port = int(spec.get("port") or _deterministic_port(task.source_id, name))
            values[f"{name}_port"] = port
            values[f"{name}_url"] = f"http://127.0.0.1:{port}"
        return values

    def _load_tasks(self) -> list[ClawBenchTask]:
        if not self.tasks_dir.exists():
            raise FileNotFoundError(
                f"ClawBench tasks directory not found: {self.tasks_dir}. "
                "Initialize related-projects/external-tasks/clawbench first or pass --source-dir."
            )
        manifest = self._manifest()
        entries = manifest.get("tasks")
        if not isinstance(entries, list):
            raise ValueError(f"Malformed ClawBench manifest: {self.manifest_path}")
        tasks = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Malformed task entry in {self.manifest_path}: {entry!r}"
                )
            yaml_path = self.tasks_dir / str(entry["path"])
            if not yaml_path.exists():
                raise FileNotFoundError(
                    f"Manifest references missing task: {yaml_path}"
                )
            definition = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(definition, dict):
                raise ValueError(f"Task YAML must be a mapping: {yaml_path}")
            source_id = str(definition.get("id") or entry.get("id") or yaml_path.stem)
            setup = definition.get("setup") or {}
            tasks.append(
                ClawBenchTask(
                    source_id=source_id,
                    local_task_id=self.make_local_task_id(source_id),
                    name=str(definition.get("name") or source_id),
                    tier=str(definition.get("tier") or entry.get("tier") or ""),
                    family=str(definition.get("family") or entry.get("family") or ""),
                    capabilities=tuple(
                        str(item)
                        for item in definition.get("capabilities")
                        or entry.get("capabilities")
                        or []
                    ),
                    subsets=tuple(
                        str(item) for item in definition.get("subsets") or []
                    ),
                    timeout_seconds=int(definition.get("timeout_seconds") or 300),
                    asset_packs=tuple(
                        str(item)
                        for item in setup.get("asset_packs")
                        or ([entry["asset_pack"]] if entry.get("asset_pack") else [])
                    ),
                    yaml_path=yaml_path.resolve(),
                    manifest_entry=dict(entry),
                    definition=definition,
                )
            )
        return tasks

    def _manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"ClawBench manifest not found: {self.manifest_path}"
            )
        payload = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Malformed ClawBench manifest: {self.manifest_path}")
        return payload

    def _select_tasks(self) -> list[ClawBenchTask]:
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


def _normalized_phases(task_definition: dict[str, Any]) -> list[dict[str, Any]]:
    phases = task_definition.get("phases") or []
    if phases:
        return [dict(phase) for phase in phases]
    return [
        {
            "name": RUN_STEP_NAME,
            "user": task_definition.get("user") or {"turns": []},
            "timeout_seconds": task_definition.get("timeout_seconds"),
        }
    ]


def _render_value(value: Any, runtime_values: dict[str, Any]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in runtime_values.items():
            rendered = rendered.replace("{" + key + "}", str(replacement))
        return rendered
    if isinstance(value, list):
        return [_render_value(item, runtime_values) for item in value]
    if isinstance(value, dict):
        rendered = {
            str(key): _render_value(item, runtime_values) for key, item in value.items()
        }
        if "background_services" in rendered:
            rendered["background_services"] = [
                _with_service_port(service, runtime_values)
                for service in rendered["background_services"]
            ]
        if "setup" in rendered and isinstance(rendered["setup"], dict):
            setup = dict(rendered["setup"])
            if "background_services" in setup:
                setup["background_services"] = [
                    _with_service_port(service, runtime_values)
                    for service in setup["background_services"]
                ]
            rendered["setup"] = setup
        return rendered
    return value


def _with_service_port(
    service: dict[str, Any], runtime_values: dict[str, Any]
) -> dict[str, Any]:
    service = dict(service)
    name = str(service.get("name") or "service")
    service.setdefault("port", runtime_values.get(f"{name}_port"))
    service.setdefault("port_env", "PORT")
    service.setdefault("ready_status", 200)
    service.setdefault("url_template", "http://127.0.0.1:{port}")
    return service


def _safe_step_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip().lower())
    return re.sub(r"-+", "-", normalized).strip("-") or RUN_STEP_NAME


def _turn_conditions(turn: dict[str, Any]) -> str:
    labels = []
    for key in (
        "after_assistant_turns",
        "when_tool_family",
        "when_tool_name",
        "when_assistant_contains",
        "when_last_tool_failed",
    ):
        value = turn.get(key)
        if value not in (None, False, ""):
            labels.append(f"{key}={value}")
    return ", ".join(labels)


def _deterministic_port(task_id: str, service_name: str) -> int:
    return 18080 + (zlib.crc32(f"{task_id}:{service_name}".encode()) % 20000)


def copy_dir_contents(source: Path, dest: Path, *, link_files: bool = False) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = dest / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                child,
                target,
                symlinks=True,
                copy_function=(hardlink_or_copy_file if link_files else shutil.copy2),
            )
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
            "Failed to hardlink ClawBench asset. Use copy mode or place --output-dir "
            f"on the same filesystem as --source-dir. Source: {source_path}; destination: {dest_path}"
        ) from exc
    return dest_path


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(toml_string(str(value)) for value in values) + "]"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _source_label(task_path: Path) -> str:
    try:
        return str(task_path.relative_to(HARBOR_ROOT))
    except ValueError:
        return str(task_path)


def _validate_harbor_task(task_dir: Path) -> None:
    from harbor.models.task.task import Task

    Task(task_dir)


PLACEHOLDER_TEST_SH = """\
#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
printf '{"reward": 1.0, "clawbench.placeholder_step": 1.0}\\n' > /logs/verifier/reward.json
"""


FINAL_TEST_SH = f"""\
#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
python3 /tests/{RUNTIME_FILENAME}
"""
