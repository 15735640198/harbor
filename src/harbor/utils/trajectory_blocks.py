"""Thought/action/result block extraction for ATIF trajectories."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path
from dataclasses import dataclass
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
    """A paper-style thought/action/result iteration derived from ATIF steps."""

    iteration: int = Field(ge=0)
    step_id: int = Field(ge=1)
    thought: str
    action: str
    result: str | None = None
    action_category: ActionCategory
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    result_step_id: int | None = None
    source_step_ids: list[int] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


@dataclass
class _MatchedResult:
    content: str | None
    result_step_id: int | None
    result_index: int | None


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

    The mapping follows the ATIF schema rather than raw agent logs. Tool-call
    steps become one block per tool call. Deterministic tool-result steps that
    follow the tool-call step are merged into the matching block as `result`.
    """
    blocks, _diagnostics = _parse_trajectory_blocks_with_diagnostics(
        trajectory,
        include_copied_context=include_copied_context,
    )
    return blocks


def _parse_trajectory_blocks_with_diagnostics(
    trajectory: Trajectory,
    *,
    include_copied_context: bool = False,
) -> tuple[list[TrajectoryBlock], dict[str, Any]]:
    blocks: list[TrajectoryBlock] = []
    diagnostics: dict[str, Any] = {
        "unmatched_tool_calls": [],
        "orphan_tool_result_steps": [],
        "positional_result_matches": [],
        "ambiguous_result_matches": [],
    }
    steps = [
        step
        for step in trajectory.steps
        if step.source == "agent"
        and (include_copied_context or not step.is_copied_context)
    ]
    consumed_result_indexes: set[int] = set()

    index = 0
    while index < len(steps):
        step = steps[index]
        tool_calls = step.tool_calls or []

        if tool_calls:
            result_run = _collect_following_tool_results(steps, index + 1)
            for tool_index, tool_call in enumerate(tool_calls):
                result = _match_tool_result(
                    step,
                    tool_call,
                    tool_index,
                    result_run,
                    diagnostics,
                )
                if result.result_index is not None:
                    consumed_result_indexes.add(result.result_index)

                source_step_ids = [step.step_id]
                if (
                    result.result_step_id is not None
                    and result.result_step_id != step.step_id
                ):
                    source_step_ids.append(result.result_step_id)

                action = _render_tool_call(tool_call)
                dumped_call = _dump_tool_calls([tool_call])
                blocks.append(
                    TrajectoryBlock(
                        iteration=len(blocks),
                        step_id=step.step_id,
                        thought=_extract_thought(step),
                        action=action,
                        result=result.content,
                        action_category=categorize_action(action, dumped_call),
                        tool_calls=dumped_call,
                        tool_call_id=tool_call.tool_call_id,
                        result_step_id=result.result_step_id,
                        source_step_ids=source_step_ids,
                    )
                )
            index += 1
            continue

        if _is_tool_result_step(step):
            if index not in consumed_result_indexes:
                diagnostics["orphan_tool_result_steps"].append(
                    {
                        "step_id": step.step_id,
                        "tool_call_id": _step_tool_call_id(step),
                    }
                )
            index += 1
            continue

        action = _render_action(step)
        blocks.append(
            TrajectoryBlock(
                iteration=len(blocks),
                step_id=step.step_id,
                thought=_extract_thought(step),
                action=action,
                result=_extract_result(step),
                action_category=categorize_action(action, None),
                tool_calls=None,
                source_step_ids=[step.step_id],
            )
        )
        index += 1

    return blocks, diagnostics


def categorize_action(
    action: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> ActionCategory:
    """Heuristically map a Harbor action to the paper's high-level categories."""
    text = _action_search_text(action, tool_calls)

    if not text or action == "agent_message":
        return "Explain"

    rendered_tool_category = _categorize_rendered_tool_action(action)
    if rendered_tool_category is not None:
        return rendered_tool_category

    tool_category = _categorize_tool_call(tool_calls)
    if tool_category is not None:
        return tool_category

    if _has_any(text, "pytest", "unittest", "npm test", "cargo test", "mvn test"):
        return "Run tests"
    if _has_any(text, "gradle test", "go test", "rspec", "test.sh", "run tests"):
        return "Run tests"
    if _has_any(text, "playwright test", "python test_", "python3 test_"):
        return "Run tests"
    if _has_any(text, "python /app/test_", "python3 /app/test_"):
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
    trajectory = load_trajectory(trajectory_path)
    blocks, diagnostics = _parse_trajectory_blocks_with_diagnostics(
        trajectory,
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
        "parse_diagnostics": output_dir / "parse_diagnostics.json",
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
    paths["parse_diagnostics"].write_text(json.dumps(diagnostics, indent=2) + "\n")
    return paths


def _collect_following_tool_results(
    steps: list[Step],
    start_index: int,
) -> list[tuple[int, Step]]:
    result_steps = []
    for index in range(start_index, len(steps)):
        step = steps[index]
        if step.tool_calls:
            break
        if not _is_tool_result_step(step):
            break
        result_steps.append((index, step))
    return result_steps


def _match_tool_result(
    action_step: Step,
    tool_call: ToolCall,
    tool_index: int,
    result_run: list[tuple[int, Step]],
    diagnostics: dict[str, Any],
) -> _MatchedResult:
    source_matches = _find_source_call_id_matches(action_step, tool_call, None)
    for result_index, result_step in result_run:
        source_matches.extend(
            _find_source_call_id_matches(result_step, tool_call, result_index)
        )
    if source_matches:
        if len(source_matches) > 1:
            diagnostics["ambiguous_result_matches"].append(
                {
                    "tool_call_id": tool_call.tool_call_id,
                    "action_step_id": action_step.step_id,
                    "matched_by": "source_call_id",
                    "candidate_step_ids": [
                        match.result_step_id for match in source_matches
                    ],
                }
            )
        return source_matches[0]

    if action_step.observation is not None and len(action_step.tool_calls or []) == 1:
        return _MatchedResult(
            content=_extract_result(action_step),
            result_step_id=action_step.step_id,
            result_index=None,
        )

    extra_matches = [
        (
            _MatchedResult(
                content=_extract_result_text(result_step),
                result_step_id=result_step.step_id,
                result_index=result_index,
            ),
            result_step.step_id,
        )
        for result_index, result_step in result_run
        if _step_tool_call_id(result_step) == tool_call.tool_call_id
    ]
    if extra_matches:
        if len(extra_matches) > 1:
            diagnostics["ambiguous_result_matches"].append(
                {
                    "tool_call_id": tool_call.tool_call_id,
                    "action_step_id": action_step.step_id,
                    "matched_by": "step_extra_tool_call_id",
                    "candidate_step_ids": [
                        step_id for _match, step_id in extra_matches
                    ],
                }
            )
        return extra_matches[0][0]

    if tool_index < len(result_run):
        result_index, result_step = result_run[tool_index]
        diagnostics["positional_result_matches"].append(
            {
                "tool_call_id": tool_call.tool_call_id,
                "action_step_id": action_step.step_id,
                "result_step_id": result_step.step_id,
            }
        )
        return _MatchedResult(
            content=_extract_result_text(result_step),
            result_step_id=result_step.step_id,
            result_index=result_index,
        )

    diagnostics["unmatched_tool_calls"].append(
        {
            "tool_call_id": tool_call.tool_call_id,
            "function_name": tool_call.function_name,
            "action_step_id": action_step.step_id,
        }
    )
    return _MatchedResult(content=None, result_step_id=None, result_index=None)


def _find_source_call_id_matches(
    step: Step,
    tool_call: ToolCall,
    result_index: int | None,
) -> list[_MatchedResult]:
    if step.observation is None:
        return []
    matches = []
    for result in step.observation.results:
        if result.source_call_id == tool_call.tool_call_id:
            matches.append(
                _MatchedResult(
                    content=_observation_result_to_text(result),
                    result_step_id=step.step_id,
                    result_index=result_index,
                )
            )
    return matches


def _is_tool_result_step(step: Step) -> bool:
    if step.tool_calls:
        return False
    extra = step.extra or {}
    return (
        step.llm_call_count == 0
        or extra.get("openclaw_role") == "toolResult"
        or step.observation is not None
    )


def _step_tool_call_id(step: Step) -> str | None:
    extra = step.extra or {}
    tool_call_id = extra.get("tool_call_id")
    return str(tool_call_id) if tool_call_id else None


def _extract_result_text(step: Step) -> str | None:
    result = _extract_result(step)
    if result:
        return result
    text = _content_to_text(step.message).strip()
    return text or None


def _extract_thought(step: Step) -> str:
    if step.reasoning_content:
        return step.reasoning_content.strip()
    return _content_to_text(step.message).strip()


def _extract_result(step: Step) -> str | None:
    if step.observation is None:
        return None
    parts = []
    for result in step.observation.results:
        text = _observation_result_to_text(result)
        if text:
            parts.append(text)
    text = "\n\n".join(part for part in parts if part)
    return text or None


def _observation_result_to_text(result: Any) -> str | None:
    parts = []
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


def _categorize_tool_call(
    tool_calls: list[dict[str, Any]] | None,
) -> ActionCategory | None:
    if not tool_calls:
        return None
    for call in tool_calls:
        name = str(call.get("function_name", "")).lower()
        args = call.get("arguments")
        arguments = args if isinstance(args, dict) else {}

        if name == "exec":
            command = str(arguments.get("command", ""))
            category = _categorize_exec_command(command)
            if category is not None:
                return category
            continue

        if name in {
            "read",
            "read_file",
            "list_files",
            "glob",
            "ls",
            "web_fetch",
            "pdf",
            "image",
        }:
            return "Explore"
        if name == "browser":
            action = str(arguments.get("action", "")).lower()
            if action in {"open", "navigate", "screenshot", "inspect"}:
                return "Explore"
        if name in {"web_search", "memory_search", "grep", "search", "rg", "ripgrep"}:
            return "Search"
        if name in {"write", "edit"}:
            return "Generate Fix"
        if name == "process":
            action = str(arguments.get("action", "")).lower()
            if action in {"poll", "log"}:
                return "Explore"
            if action in {"kill", "remove", "clear"}:
                return "Other"
    return None


def _categorize_rendered_tool_action(action: str) -> ActionCategory | None:
    text = action.strip().lower()
    if text.startswith(("web_fetch(", "image(", "pdf(")):
        return "Explore"
    if text.startswith("browser("):
        if '"action": "open"' in text or "'action': 'open'" in text:
            return "Explore"
    if text.startswith(("web_search(", "memory_search(")):
        return "Search"
    if text.startswith(("write(", "edit(")):
        return "Generate Fix"
    if text.startswith("process("):
        if '"action": "poll"' in text or '"action": "log"' in text:
            return "Explore"
        if "'action': 'poll'" in text or "'action': 'log'" in text:
            return "Explore"
        if '"action": "kill"' in text or '"action": "remove"' in text:
            return "Other"
    return None


def _categorize_exec_command(command: str) -> ActionCategory | None:
    text = f" {command.lower().strip()} "
    if _has_any(text, " pytest ", " unittest ", " npm test ", " cargo test "):
        return "Run tests"
    if _has_any(text, " mvn test ", " gradle test ", " go test ", " rspec "):
        return "Run tests"
    if _has_any(text, " playwright test ", " test.sh "):
        return "Run tests"
    if _has_any(text, " python test_", " python3 test_", " python /app/test_"):
        return "Run tests"
    if _has_any(text, " python3 /app/test_", "/python test_", "/python3 test_"):
        return "Run tests"

    if _has_any(text, " rg ", " grep ", " ripgrep ", " findstr "):
        return "Search"

    if _has_any(text, " cat <<", " apply_patch ", " tee ", " > "):
        return "Generate Fix"
    if _has_any(text, " touch ", " chmod +x "):
        return "Generate Fix"

    stripped = command.strip().lower()
    first = stripped.split(maxsplit=1)[0] if stripped else ""
    if first in {"ls", "cat", "sed", "head", "tail", "wc", "pwd"}:
        return "Explore"
    if first == "find":
        return "Explore"

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
