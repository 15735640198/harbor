"""Thought/action/result block extraction for ATIF trajectories."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from harbor.models.trajectories import ContentPart, Step, ToolCall, Trajectory

ActionCategory = Literal[
    "Explore",
    "Locate",
    "Search",
    "Reproduce",
    "Generate Fix",
    "Run tests",
    "Refactor",
    "Explain",
    "Other",
]


class TrajectoryBlock(BaseModel):
    """A paper-style thought/action/result iteration derived from one ATIF step."""

    iteration: int = Field(ge=0)
    step_id: int = Field(ge=1)
    thought: str
    action: str
    result: str | None = None
    action_category: ActionCategory
    tool_calls: list[dict[str, Any]] | None = None

    model_config = {"extra": "forbid"}


def load_trajectory(path: Path) -> Trajectory:
    """Load and validate an ATIF trajectory file."""
    return Trajectory.model_validate_json(path.read_text())


def parse_trajectory_file(
    trajectory_path: Path,
    *,
    include_copied_context: bool = False,
) -> list[TrajectoryBlock]:
    """Load a trajectory file and parse it into thought/action/result blocks."""
    return parse_trajectory_blocks(
        load_trajectory(trajectory_path),
        include_copied_context=include_copied_context,
    )


def parse_trajectory_blocks(
    trajectory: Trajectory,
    *,
    include_copied_context: bool = False,
) -> list[TrajectoryBlock]:
    """Convert ATIF agent steps into thought/action/result blocks.

    The mapping follows the ATIF schema rather than raw agent logs:
    thought is `reasoning_content` when present, falling back to the agent
    message; action is the step's `tool_calls`, falling back to an agent message
    marker; result is the step's `observation`.
    """
    blocks: list[TrajectoryBlock] = []
    for step in trajectory.steps:
        if step.source != "agent":
            continue
        if step.is_copied_context and not include_copied_context:
            continue

        tool_calls = _dump_tool_calls(step.tool_calls)
        action = _render_action(step)
        blocks.append(
            TrajectoryBlock(
                iteration=len(blocks),
                step_id=step.step_id,
                thought=_extract_thought(step),
                action=action,
                result=_extract_result(step),
                action_category=categorize_action(action, tool_calls),
                tool_calls=tool_calls or None,
            )
        )
    return blocks


def categorize_action(
    action: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> ActionCategory:
    """Heuristically map a Harbor action to the paper's high-level categories."""
    text = _action_search_text(action, tool_calls)

    if not text or action == "agent_message":
        return "Explain"

    if _has_any(text, "pytest", "unittest", "npm test", "cargo test", "mvn test"):
        return "Run tests"
    if _has_any(text, "gradle test", "go test", "rspec", "test.sh", "run tests"):
        return "Run tests"
    if _has_any(text, "reproduce", "repro", "failing test", "regression test"):
        return "Reproduce"

    editor_category = _categorize_editor_tool(tool_calls)
    if editor_category is not None:
        return editor_category

    if _has_any(text, '"command": "view"', "'command': 'view'"):
        return "Explore"
    if _has_any(text, '"command": "read"', "'command': 'read'"):
        return "Explore"
    if _has_any(text, '"command": "str_replace"', "'command': 'str_replace'"):
        return "Generate Fix"
    if _has_any(text, '"command": "create"', "'command': 'create'"):
        return "Generate Fix"
    if _has_any(text, '"command": "insert"', "'command': 'insert'"):
        return "Generate Fix"

    if _has_any(text, "apply_patch", "edit", "write", "replace", "insert", "patch"):
        return "Generate Fix"
    if _has_any(text, "create file", "> ", "tee ", "cat <<"):
        return "Generate Fix"
    if _has_any(text, "ruff", "black", "prettier", "format", "lint", "refactor"):
        return "Refactor"
    if _has_any(text, "rg ", "grep", "search", "findstr", "ripgrep"):
        return "Search"
    if _has_any(text, "locate", "definition", "references", "symbol", "bug location"):
        return "Locate"
    if _has_any(text, "ls ", "find ", "cat ", "sed -n", "head ", "tail ", "pwd"):
        return "Explore"
    if _has_any(text, "read", "view", "open file", "list", "inspect"):
        return "Explore"
    if _has_any(text, "finish", "complete", "message", "summarize", "analyze"):
        return "Explain"

    return "Other"


def action_ngrams(
    blocks: Iterable[TrajectoryBlock],
    n: int = 4,
) -> Counter[tuple[str, ...]]:
    """Count fixed-length n-grams of action categories."""
    if n < 1:
        raise ValueError("n must be at least 1")
    categories = [block.action_category for block in blocks]
    return Counter(tuple(categories[i : i + n]) for i in range(len(categories) - n + 1))


def write_trajectory_block_analysis(
    trajectory_path: Path,
    output_dir: Path,
    *,
    ngram_size: int = 4,
    include_copied_context: bool = False,
) -> dict[str, Path]:
    """Write TAR blocks and paper-style analysis views for one trajectory."""
    blocks = parse_trajectory_file(
        trajectory_path,
        include_copied_context=include_copied_context,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "blocks_jsonl": output_dir / "blocks.jsonl",
        "actions_categories": output_dir / "actions_categories.csv",
        "action_ngrams": output_dir / "action_ngrams.csv",
        "thoughts_actions": output_dir / "thoughts_actions.txt",
        "thoughts_thoughts": output_dir / "thoughts_thoughts.txt",
        "action_actions": output_dir / "action_actions.txt",
        "results_actions": output_dir / "results_actions.txt",
        "results_thoughts": output_dir / "results_thoughts.txt",
    }

    paths["blocks_jsonl"].write_text(
        "".join(block.model_dump_json() + "\n" for block in blocks)
    )
    paths["actions_categories"].write_text(_format_categories_csv(blocks))
    paths["action_ngrams"].write_text(_format_ngrams_csv(blocks, ngram_size))
    paths["thoughts_actions"].write_text(_format_thoughts_actions(blocks))
    paths["thoughts_thoughts"].write_text(
        _format_single_component(blocks, "thought", "Thought")
    )
    paths["action_actions"].write_text(
        _format_single_component(blocks, "action", "Action")
    )
    paths["results_actions"].write_text(
        _format_result_to_next(blocks, "action", "Action")
    )
    paths["results_thoughts"].write_text(
        _format_result_to_next(blocks, "thought", "Thought")
    )
    return paths


def _extract_thought(step: Step) -> str:
    if step.reasoning_content:
        return step.reasoning_content.strip()
    return _content_to_text(step.message).strip()


def _extract_result(step: Step) -> str | None:
    if step.observation is None:
        return None
    parts = []
    for result in step.observation.results:
        if result.content is not None:
            parts.append(_content_to_text(result.content))
        if result.subagent_trajectory_ref:
            refs = [
                ref.model_dump(exclude_none=True, mode="json")
                for ref in result.subagent_trajectory_ref
            ]
            parts.append(json.dumps(refs, sort_keys=True))
    text = "\n\n".join(part for part in parts if part)
    return text or None


def _render_action(step: Step) -> str:
    if step.tool_calls:
        return "; ".join(_render_tool_call(call) for call in step.tool_calls)
    return "agent_message"


def _render_tool_call(tool_call: ToolCall) -> str:
    if not tool_call.arguments:
        return tool_call.function_name
    args = json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)
    return f"{tool_call.function_name}({args})"


def _dump_tool_calls(tool_calls: list[ToolCall] | None) -> list[dict[str, Any]]:
    if not tool_calls:
        return []
    return [call.model_dump(mode="json", exclude_none=True) for call in tool_calls]


def _content_to_text(content: str | list[ContentPart]) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if part.type == "text":
            parts.append(part.text or "")
        elif part.source:
            parts.append(f"[image:{part.source.path}]")
    return "\n".join(part for part in parts if part)


def _action_search_text(
    action: str,
    tool_calls: list[dict[str, Any]] | None,
) -> str:
    payload = action
    if tool_calls:
        payload += " " + json.dumps(tool_calls, sort_keys=True, ensure_ascii=False)
    return payload.lower()


def _categorize_editor_tool(
    tool_calls: list[dict[str, Any]] | None,
) -> ActionCategory | None:
    if not tool_calls:
        return None
    for call in tool_calls:
        name = str(call.get("function_name", "")).lower()
        args = call.get("arguments")
        arguments = args if isinstance(args, dict) else {}
        command = str(arguments.get("command", "")).lower()

        if name in {"str_replace_editor", "text_editor", "editor"}:
            if command in {"view", "read", "open"}:
                return "Explore"
            if command in {"create", "str_replace", "insert", "undo_edit"}:
                return "Generate Fix"

        if name in {"read_file", "list_files", "glob", "ls"}:
            return "Explore"
        if name in {"grep", "search", "rg", "ripgrep"}:
            return "Search"
    return None


def _has_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _format_categories_csv(blocks: list[TrajectoryBlock]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["iteration", "step_id", "category", "action"])
    for block in blocks:
        writer.writerow(
            [block.iteration, block.step_id, block.action_category, block.action]
        )
    return out.getvalue()


def _format_ngrams_csv(blocks: list[TrajectoryBlock], ngram_size: int) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ngram", "count"])
    for ngram, count in action_ngrams(blocks, ngram_size).most_common():
        writer.writerow([" -> ".join(ngram), count])
    return out.getvalue()


def _format_thoughts_actions(blocks: list[TrajectoryBlock]) -> str:
    rows = []
    for block in blocks:
        rows.append(
            f"Thought at Iteration {block.iteration}: {block.thought}\n"
            f"Action at Iteration {block.iteration}: {block.action}"
        )
    return "\n\n".join(rows) + ("\n" if rows else "")


def _format_single_component(
    blocks: list[TrajectoryBlock],
    field: Literal["thought", "action"],
    label: str,
) -> str:
    rows = [
        f"{label} at Iteration {block.iteration}: {getattr(block, field)}"
        for block in blocks
    ]
    return "\n".join(rows) + ("\n" if rows else "")


def _format_result_to_next(
    blocks: list[TrajectoryBlock],
    next_field: Literal["thought", "action"],
    next_label: str,
) -> str:
    rows = []
    for index, block in enumerate(blocks[:-1]):
        next_value = getattr(blocks[index + 1], next_field)
        rows.append(
            f"Result at Iteration {block.iteration}: {block.result or ''}\n"
            f"{next_label} at Iteration {blocks[index + 1].iteration}: {next_value}"
        )
    return "\n\n".join(rows) + ("\n" if rows else "")
