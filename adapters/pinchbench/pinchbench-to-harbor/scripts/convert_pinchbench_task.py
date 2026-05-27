#!/usr/bin/env python3
# /// script
# dependencies = [
#   "pyyaml>=6.0.2",
# ]
# ///

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import textwrap
from pathlib import Path
from typing import Any

import yaml


DEFAULT_JUDGE_MODEL = "claude-haiku-4-5"
DEFAULT_ORG = "pinchbench"
SCRIPT_DIR = Path(__file__).resolve().parent
ENVIRONMENT_DOCKERFILE_TEMPLATE = SCRIPT_DIR / "Dockerfile"


def main() -> None:
    args = parse_args()
    task_md = args.task_md.resolve()
    if not task_md.exists():
        raise FileNotFoundError(task_md)

    pinchbench_root = (
        args.pinchbench_root.resolve()
        if args.pinchbench_root
        else infer_pinchbench_root(task_md)
    )
    task = load_pinchbench_task(task_md)
    output_root = args.output_root.resolve()
    output_dir = (
        args.output_dir.resolve() if args.output_dir else output_root / task["id"]
    )

    if output_dir.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"{output_dir} exists; pass --overwrite to replace it"
            )
        shutil.rmtree(output_dir)

    build_harbor_task(
        task=task,
        task_md=task_md,
        pinchbench_root=pinchbench_root,
        output_dir=output_dir,
        org=args.org,
        judge_model=args.judge_model,
        source_label=args.source_label or str(task_md),
    )
    print(output_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one Pinchbench task markdown file to a Harbor task directory."
    )
    parser.add_argument("task_md", type=Path, help="Pinchbench task markdown file")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("converted-pinchbench-tasks"),
        help="Directory under which <task-id>/ will be created",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Exact output task directory. Overrides --output-root.",
    )
    parser.add_argument(
        "--pinchbench-root",
        type=Path,
        help="Pinchbench repo root. Defaults to the parent of the task's tasks/ directory.",
    )
    parser.add_argument(
        "--org",
        default=DEFAULT_ORG,
        help="Harbor task package org prefix for [task].name.",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help="Verifier MODEL_NAME for generated LLM judge tasks.",
    )
    parser.add_argument(
        "--source-label",
        help="Value to write to task.toml source. Defaults to the task markdown path.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output directory.",
    )
    return parser.parse_args()


def infer_pinchbench_root(task_md: Path) -> Path:
    if task_md.parent.name == "tasks":
        return task_md.parent.parent.resolve()
    return task_md.parent.resolve()


def load_pinchbench_task(task_md: Path) -> dict[str, Any]:
    content = task_md.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {task_md}")

    metadata = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    sections = parse_sections(body)

    task_id = str(metadata.get("id") or task_md.stem)
    return {
        "id": sanitize_id(task_id),
        "display_id": task_id,
        "name": str(metadata.get("name") or task_id),
        "category": str(metadata.get("category") or "pinchbench"),
        "grading_type": str(metadata.get("grading_type") or "automated"),
        "timeout_seconds": int(metadata.get("timeout_seconds") or 180),
        "workspace_files": metadata.get("workspace_files") or [],
        "grading_weights": metadata.get("grading_weights") or {},
        "multi_session": bool(metadata.get("multi_session")),
        "sessions": metadata.get("sessions") or [],
        "frontmatter": metadata,
        "prompt": sections.get("Prompt", "").strip(),
        "expected_behavior": sections.get("Expected Behavior", "").strip(),
        "grading_criteria": sections.get("Grading Criteria", "").strip(),
        "automated_checks": sections.get("Automated Checks", "").strip(),
        "llm_judge_rubric": sections.get("LLM Judge Rubric", "").strip(),
    }


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


def sanitize_id(value: str) -> str:
    value = value.strip().replace("_", "-")
    value = re.sub(r"[^a-zA-Z0-9.-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-").lower()
    if not value:
        return "pinchbench-task"
    return value


def build_harbor_task(
    *,
    task: dict[str, Any],
    task_md: Path,
    pinchbench_root: Path,
    output_dir: Path,
    org: str,
    judge_model: str,
    source_label: str,
) -> None:
    grading_type = task["grading_type"]
    if grading_type not in {"automated", "llm_judge", "hybrid"}:
        raise ValueError(f"Unsupported grading_type: {grading_type}")

    (output_dir / "environment").mkdir(parents=True)
    (output_dir / "tests").mkdir(parents=True)
    stage_workspace_files(
        task, pinchbench_root, output_dir / "environment" / "workspace"
    )
    write_environment_dockerfile(output_dir / "environment" / "Dockerfile")
    write_task_toml(
        task=task,
        task_md=task_md,
        output_path=output_dir / "task.toml",
        org=org,
        judge_model=judge_model,
        source_label=source_label,
    )

    if task["multi_session"] and task["sessions"]:
        write_multi_session_instructions_and_tests(task, output_dir)
    else:
        write_text(output_dir / "instruction.md", ensure_newline(task["prompt"]))
        write_single_step_test(task, output_dir)

    write_verifier_scripts(
        task=task,
        pinchbench_root=pinchbench_root,
        tests_dir=output_dir / "tests",
    )


def stage_workspace_files(
    task: dict[str, Any], pinchbench_root: Path, workspace_dir: Path
) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    workspace_files = task["workspace_files"]
    if not workspace_files:
        return

    for entry in workspace_files:
        if not isinstance(entry, dict):
            raise ValueError(f"workspace_files entries must be mappings: {entry!r}")
        dest = entry.get("dest") or entry.get("path") or entry.get("destination")
        if not dest and entry.get("source"):
            dest = Path(str(entry["source"])).name
        if not dest:
            raise ValueError(f"workspace file entry has no dest/path: {entry!r}")

        dest_path = safe_join(workspace_dir, str(dest))
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if "content" in entry:
            write_text(dest_path, str(entry["content"]))
            continue

        source = entry.get("source")
        if not source:
            raise ValueError(f"workspace file entry has no source/content: {entry!r}")
        source_path = resolve_workspace_source(pinchbench_root, str(source))
        if source_path.is_dir():
            if dest_path.exists():
                shutil.rmtree(dest_path)
            shutil.copytree(source_path, dest_path)
        else:
            shutil.copy2(source_path, dest_path)


def safe_join(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError(f"Path escapes workspace: {relative_path}")
    return target


def resolve_workspace_source(pinchbench_root: Path, source: str) -> Path:
    candidates = [
        pinchbench_root / "assets" / source,
        pinchbench_root / source,
        pinchbench_root / "tasks" / source,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = "\n".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Could not resolve workspace source {source!r}. Tried:\n{tried}"
    )


def write_environment_dockerfile(path: Path) -> None:
    if not ENVIRONMENT_DOCKERFILE_TEMPLATE.exists():
        raise FileNotFoundError(
            f"Harbor environment Dockerfile template not found: {ENVIRONMENT_DOCKERFILE_TEMPLATE}"
        )
    shutil.copy2(ENVIRONMENT_DOCKERFILE_TEMPLATE, path)


def write_task_toml(
    *,
    task: dict[str, Any],
    task_md: Path,
    output_path: Path,
    org: str,
    judge_model: str,
    source_label: str,
) -> None:
    timeout = float(task["timeout_seconds"])
    tags = ["pinchbench", task["category"], task["grading_type"]]
    lines = [
        'schema_version = "1.1"',
        f"source = {toml_string(source_label)}",
    ]
    if task["multi_session"] and task["sessions"]:
        lines.append('multi_step_reward_strategy = "final"')
    lines.extend(
        [
            "",
            "[task]",
            f"name = {toml_string(f'{org}/{task["id"]}')}",
            f"description = {toml_string(task['name'])}",
            "authors = []",
            f"keywords = {toml_array(tags)}",
            "",
            "[metadata]",
            f"category = {toml_string(task['category'])}",
            'difficulty = "unknown"',
            f"tags = {toml_array(tags)}",
            f"pinchbench_id = {toml_string(task['display_id'])}",
            f"pinchbench_grading_type = {toml_string(task['grading_type'])}",
            "",
            "[verifier]",
            f"timeout_sec = {max(timeout, 120.0):.1f}",
            "",
            "[agent]",
            f"timeout_sec = {max(timeout, 120.0):.1f}",
            "",
            "[environment]",
            "build_timeout_sec = 900.0",
            "cpus = 1",
            "memory_mb = 4096",
            "storage_mb = 10240",
            "gpus = 0",
            "allow_internet = true",
            "mcp_servers = []",
            'workdir = "/app"',
        ]
    )

    if task["grading_type"] in {"llm_judge", "hybrid"}:
        lines.extend(
            [
                "",
                "[verifier.env]",
                'ANTHROPIC_API_KEY = "${ANTHROPIC_API_KEY}"',
                'ANTHROPIC_BASE_URL = "${ANTHROPIC_BASE_URL:-}"',
                f"MODEL_NAME = {toml_string(judge_model)}",
            ]
        )
    else:
        lines.extend(["", "[verifier.env]"])

    lines.extend(["", "[solution.env]"])

    if task["multi_session"] and task["sessions"]:
        for session in task["sessions"]:
            step_name = sanitize_id(str(session.get("id") or f"step-{len(lines)}"))
            lines.extend(
                [
                    "",
                    "[[steps]]",
                    f"name = {toml_string(step_name)}",
                    "",
                    "[steps.agent]",
                    f"timeout_sec = {max(timeout, 120.0):.1f}",
                    "",
                    "[steps.verifier]",
                    f"timeout_sec = {max(timeout, 120.0):.1f}",
                ]
            )

    write_text(output_path, "\n".join(lines) + "\n")


def write_multi_session_instructions_and_tests(
    task: dict[str, Any], output_dir: Path
) -> None:
    sessions = task["sessions"]
    if not sessions:
        raise ValueError("multi_session task has no sessions")
    last_index = len(sessions) - 1
    for index, session in enumerate(sessions):
        step_name = sanitize_id(str(session.get("id") or f"step-{index + 1}"))
        step_dir = output_dir / "steps" / step_name
        prompt = str(session.get("prompt") or "")
        if session.get("new_session"):
            prompt = "[Pinchbench new_session requested]\n\n" + prompt
        write_text(step_dir / "instruction.md", ensure_newline(prompt))
        tests_dir = step_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        if index == last_index:
            write_test_sh(tests_dir / "test.sh", task["grading_type"])
        else:
            write_text(
                tests_dir / "test.sh",
                "#!/bin/bash\nmkdir -p /logs/verifier\necho '{\"reward\": 1.0}' > /logs/verifier/reward.json\n",
                executable=True,
            )


def write_single_step_test(task: dict[str, Any], output_dir: Path) -> None:
    write_test_sh(output_dir / "tests" / "test.sh", task["grading_type"])


def write_test_sh(path: Path, grading_type: str) -> None:
    if grading_type == "automated":
        body = """\
#!/bin/bash
mkdir -p /logs/verifier
python3 /tests/run_pinchbench_grade.py || echo '{"reward": 0.0}' > /logs/verifier/reward.json
"""
    else:
        body = """\
#!/bin/bash
mkdir -p /logs/verifier
uv run /tests/llm_judge.py || echo '{"reward": 0.0}' > /logs/verifier/reward.json
"""
    write_text(path, body, executable=True)


def write_verifier_scripts(
    task: dict[str, Any], pinchbench_root: Path, tests_dir: Path
) -> None:
    grade_code = extract_python_code(task["automated_checks"])
    grading_type = task["grading_type"]
    if grading_type in {"automated", "hybrid"} and not grade_code:
        raise ValueError(
            f"{grading_type} task is missing a Python Automated Checks block"
        )

    maybe_copy_private_image_key(pinchbench_root, tests_dir, grade_code)

    if grading_type == "automated":
        write_text(
            tests_dir / "run_pinchbench_grade.py",
            build_automated_verifier_py(task, grade_code),
            executable=True,
        )
    else:
        write_text(
            tests_dir / "llm_judge.py",
            build_llm_judge_py(task, grade_code),
            executable=True,
        )


def maybe_copy_private_image_key(
    pinchbench_root: Path, tests_dir: Path, grade_code: str
) -> None:
    if "_PINCHBENCH_PRIVATE_IMAGE_KEY_PATH" not in grade_code:
        return
    source = pinchbench_root / "assets" / "image_classification_answer_key.json"
    if source.exists():
        shutil.copy2(source, tests_dir / "image_classification_answer_key.json")


def extract_python_code(section_text: str) -> str:
    if not section_text:
        return ""
    match = re.search(r"```python\s*(.*?)\s*```", section_text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    return ""


def build_automated_verifier_py(task: dict[str, Any], grade_code: str) -> str:
    return (
        GENERATED_AUTOMATED_PREFIX
        + GENERATED_COMMON_PY
        + f"""
TASK_ID = {py_literal(task["display_id"])}
GRADE_SOURCE = {py_literal(grade_code)}


def main() -> None:
    automated_score, automated_scores = run_automated_grade(GRADE_SOURCE)
    payload = build_reward_payload(
        reward=automated_score,
        automated_score=automated_score,
        automated_scores=automated_scores,
        judge_score=None,
        judge_scores={{}},
        notes="",
    )
    write_reward(payload)


if __name__ == "__main__":
    main()
"""
    )


def build_llm_judge_py(task: dict[str, Any], grade_code: str) -> str:
    weights = task["grading_weights"] or {}
    auto_weight = float(weights.get("automated", 0.5))
    judge_weight = float(weights.get("llm_judge", 0.5))
    rubric = task["llm_judge_rubric"] or checklist_to_rubric(task["grading_criteria"])
    return (
        GENERATED_LLM_PREFIX
        + GENERATED_COMMON_PY
        + GENERATED_LLM_HELPERS_PY
        + f"""
TASK_ID = {py_literal(task["display_id"])}
GRADING_TYPE = {py_literal(task["grading_type"])}
TASK_PROMPT = {py_literal(task["prompt"])}
EXPECTED_BEHAVIOR = {py_literal(task["expected_behavior"])}
RUBRIC = {py_literal(rubric)}
GRADE_SOURCE = {py_literal(grade_code)}
AUTOMATED_WEIGHT = {auto_weight!r}
LLM_JUDGE_WEIGHT = {judge_weight!r}


def main() -> None:
    automated_score = None
    automated_scores = {{}}
    if GRADING_TYPE == "hybrid":
        automated_score, automated_scores = run_automated_grade(GRADE_SOURCE)

    judge_score, judge_scores, notes = run_llm_judge(
        task_prompt=TASK_PROMPT,
        expected_behavior=EXPECTED_BEHAVIOR,
        rubric=RUBRIC,
    )

    if GRADING_TYPE == "hybrid":
        total_weight = AUTOMATED_WEIGHT + LLM_JUDGE_WEIGHT
        if total_weight <= 0:
            total_weight = 1.0
            auto_weight = judge_weight = 0.5
        else:
            auto_weight = AUTOMATED_WEIGHT
            judge_weight = LLM_JUDGE_WEIGHT
        reward = ((automated_score or 0.0) * auto_weight + judge_score * judge_weight) / total_weight
    else:
        reward = judge_score

    payload = build_reward_payload(
        reward=reward,
        automated_score=automated_score,
        automated_scores=automated_scores,
        judge_score=judge_score,
        judge_scores=judge_scores,
        notes=notes,
    )
    write_reward(payload)


if __name__ == "__main__":
    main()
"""
    )


GENERATED_AUTOMATED_PREFIX = """#!/usr/bin/env python3
"""


GENERATED_LLM_PREFIX = """#!/usr/bin/env python3
# /// script
# dependencies = [
#   "anthropic>=0.75.0",
#   "pydantic==2.12.5",
# ]
# ///
"""


GENERATED_COMMON_PY = """
import json
import traceback
from pathlib import Path
from typing import Any


WORKSPACE = Path("/app")
REWARD_PATH = Path("/logs/verifier/reward.json")
PRIVATE_IMAGE_KEY = Path("/tests/image_classification_answer_key.json")


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def average_scores(scores: dict[str, Any]) -> float:
    values = [float(v) for v in scores.values() if isinstance(v, (int, float))]
    if not values:
        return 0.0
    return clamp01(sum(values) / len(values))


def normalize_scores(scores: Any) -> dict[str, float]:
    if not isinstance(scores, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, value in scores.items():
        if isinstance(value, (int, float)):
            normalized[str(key)] = clamp01(value)
    return normalized


def load_transcript() -> list[dict[str, Any]]:
    roots = [Path("/logs/agent"), Path("/logs")]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            loaded = load_json_transcript(path)
            if loaded:
                return loaded
        for path in sorted(root.rglob("*.jsonl")):
            loaded = load_jsonl_transcript(path)
            if loaded:
                return loaded
    return []


def load_json_transcript(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("transcript", "events", "messages", "trajectory"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def load_jsonl_transcript(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
    except Exception:
        return []
    return events


def run_automated_grade(grade_source: str) -> tuple[float, dict[str, float]]:
    if not grade_source.strip():
        return 0.0, {}
    namespace: dict[str, Any] = {}
    if PRIVATE_IMAGE_KEY.exists():
        namespace["_PINCHBENCH_PRIVATE_IMAGE_KEY_PATH"] = str(PRIVATE_IMAGE_KEY)
    try:
        exec(grade_source, namespace)
        grade = namespace.get("grade")
        if not callable(grade):
            return 0.0, {}
        raw_scores = grade(load_transcript(), str(WORKSPACE))
        scores = normalize_scores(raw_scores)
        return average_scores(scores), scores
    except Exception:
        traceback.print_exc()
        return 0.0, {}


def build_reward_payload(
    *,
    reward: float,
    automated_score: float | None,
    automated_scores: dict[str, float],
    judge_score: float | None,
    judge_scores: dict[str, float],
    notes: str,
) -> dict[str, float | int]:
    payload: dict[str, float | int] = {"reward": clamp01(reward)}
    if automated_score is not None:
        payload["automated"] = clamp01(automated_score)
        for key, value in automated_scores.items():
            payload[f"automated.{key}"] = clamp01(value)
    if judge_score is not None:
        payload["llm_judge"] = clamp01(judge_score)
        for key, value in judge_scores.items():
            payload[f"llm_judge.{key}"] = clamp01(value)
    return payload


def write_reward(payload: dict[str, float | int]) -> None:
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
"""


GENERATED_LLM_HELPERS_PY = """
import os

from anthropic import Anthropic
from pydantic import BaseModel, Field


class JudgeResponse(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    total: float = Field(..., ge=0.0, le=1.0)
    notes: str = ""


def read_workspace_files() -> str:
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv"}
    skip_names = {"BOOTSTRAP.md", "SOUL.md", "USER.md", "IDENTITY.md", "HEARTBEAT.md", "TOOLS.md", "AGENTS.md"}
    chunks: list[str] = []
    total_chars = 0
    for path in sorted(WORKSPACE.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(WORKSPACE)
        if any(part.startswith(".") or part in skip_dirs for part in rel.parts):
            continue
        if path.name in skip_names:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(text) > 50000:
            text = text[:50000] + "\\n...[truncated]"
        next_chunk = f"### File: {rel}\\n{text}"
        if total_chars + len(next_chunk) > 160000:
            chunks.append("...[workspace truncated]")
            break
        chunks.append(next_chunk)
        total_chars += len(next_chunk)
    return "\\n\\n".join(chunks)


def summarize_transcript() -> str:
    events = load_transcript()
    parts: list[str] = []
    for event in events[:200]:
        role = ""
        text = ""
        if isinstance(event.get("message"), dict):
            message = event["message"]
            role = str(message.get("role", ""))
            content = message.get("content", "")
            text = json.dumps(content) if not isinstance(content, str) else content
        else:
            role = str(event.get("role") or event.get("type") or "")
            text = json.dumps(event)[:2000]
        if text:
            parts.append(f"{role}: {text[:2000]}")
    return "\\n".join(parts)


def build_judge_prompt(task_prompt: str, expected_behavior: str, rubric: str) -> str:
    workspace = read_workspace_files()
    transcript = summarize_transcript()
    workspace_section = f"## Workspace Files Created or Available\\n{workspace}\\n\\n" if workspace else ""
    transcript_section = f"## Agent Transcript Summary\\n{transcript}\\n\\n" if transcript else ""
    return (
        "You are a grading function. Output only a valid JSON object, with no markdown fences or extra text.\\n"
        'Use exactly this shape: {"scores": {"criterion_name": 0.0}, "total": 0.0, "notes": "short rationale"}.\\n'
        "Each score and total must be a number from 0.0 to 1.0.\\n"
        "Be strict: reserve 1.0 for excellent performance and use partial credit.\\n\\n"
        "## Task\\n"
        f"{task_prompt}\\n\\n"
        "## Expected Behavior\\n"
        f"{expected_behavior}\\n\\n"
        f"{transcript_section}"
        f"{workspace_section}"
        "## Grading Rubric\\n"
        f"{rubric}\\n\\n"
        "Score each criterion from 0.0 to 1.0. The total must be the arithmetic mean of the criterion scores, not their sum."
    )


def extract_response_text(response: Any) -> str:
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text
        if isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise ValueError("LLM judge response did not include a text content block")


def parse_judge_response(text: str) -> JudgeResponse:
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return JudgeResponse.model_validate_json(candidate)
        except Exception as exc:
            last_error = exc
        try:
            payload = json.loads(candidate)
            return JudgeResponse.model_validate(coerce_judge_payload(payload))
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("LLM judge response did not contain JSON")


def coerce_judge_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM judge JSON response must be an object")

    data = dict(payload)
    if "total" not in data:
        for key in ("Total", "overall", "Overall", "score", "Score", "reward", "Reward"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                data["total"] = clamp01(value)
                break

    if not isinstance(data.get("scores"), dict):
        excluded = {
            "total",
            "Total",
            "overall",
            "Overall",
            "score",
            "Score",
            "reward",
            "Reward",
            "notes",
            "Notes",
            "explanation",
            "Explanation",
            "reasoning",
            "Reasoning",
        }
        scores = {
            str(key): clamp01(value)
            for key, value in data.items()
            if key not in excluded and isinstance(value, (int, float))
        }
        if scores:
            data["scores"] = scores

    if "total" not in data and isinstance(data.get("scores"), dict):
        data["total"] = average_scores(data["scores"])

    if "notes" not in data:
        for key in ("Notes", "explanation", "Explanation", "reasoning", "Reasoning"):
            value = data.get(key)
            if isinstance(value, str):
                data["notes"] = value
                break
        else:
            data["notes"] = ""

    return data


def run_llm_judge(
    *, task_prompt: str, expected_behavior: str, rubric: str
) -> tuple[float, dict[str, float], str]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return 0.0, {}, "ANTHROPIC_API_KEY is not set"

    base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip() or None
    client = Anthropic(api_key=api_key, base_url=base_url)
    response = client.messages.create(
        model=os.getenv("MODEL_NAME", "claude-haiku-4-5"),
        max_tokens=2048,
        messages=[{"role": "user", "content": build_judge_prompt(task_prompt, expected_behavior, rubric)}],
    )
    result = parse_judge_response(extract_response_text(response))
    return clamp01(result.total), normalize_scores(result.scores), result.notes
"""


def checklist_to_rubric(criteria: str) -> str:
    lines = []
    for line in criteria.splitlines():
        match = re.match(r"^-\s+\[[ xX]\]\s+(.+)$", line.strip())
        if match:
            lines.append(f"- {match.group(1)}")
    return "\n".join(lines)


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_array(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(str(value)) for value in values) + "]"


def py_literal(value: str) -> str:
    return repr(value)


def ensure_newline(value: str) -> str:
    return value.rstrip() + "\n"


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    main()
