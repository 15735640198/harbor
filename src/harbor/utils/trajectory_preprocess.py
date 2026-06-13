"""Create compact analysis packets from ATIF trajectories."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from harbor.models.trajectories import (
    ContentPart,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)

_ERROR_PATTERNS = (
    "command not found",
    "no such file or directory",
    "permission denied",
    "timed out",
    "timeout",
    "traceback",
    "exception",
    "error",
    "failed",
    "forbidden",
    "access denied",
)
_SUCCESS_STATUSES = {"ok", "success", "succeeded", "completed", "complete", "done"}
_FAILURE_STATUSES = {
    "aborted",
    "blocked",
    "cancelled",
    "canceled",
    "error",
    "failed",
    "failure",
    "invalid",
    "rejected",
    "timeout",
    "timed_out",
}
_SHELL_TOOL_NAMES = {
    "bash",
    "bash_command",
    "exec",
    "shell",
    "terminal",
    "run_command",
}


class CompactedText(BaseModel):
    """A compact text excerpt plus truncation state."""

    content_excerpt: str | None = None
    truncated: bool = False

    model_config = {"extra": "forbid"}


class ProcessedResult(CompactedText):
    """A normalized tool execution result."""

    success: bool
    status_basis: str | None = None


class ProcessedInvocation(BaseModel):
    """A joined invocation/result pair for a chronological transcript."""

    invocation_id: str
    name: str
    arguments_excerpt: str | None = None
    arguments_truncated: bool = False
    result: ProcessedResult

    model_config = {"extra": "forbid"}


class ProcessedTranscriptItem(BaseModel):
    """One chronological item for whole-trajectory LLM consumption."""

    agent_message: str | None = None
    tool_invocation: ProcessedInvocation | None = None

    model_config = {"extra": "forbid"}


class ProcessedTask(BaseModel):
    """Task-level user and system context kept for downstream judges."""

    user_message: str | None = None
    system_messages: list[str] | None = None

    model_config = {"extra": "forbid"}


class PreprocessSummary(BaseModel):
    """Cheap counts for sanity-checking the processed packet."""

    agent_messages: int
    tool_invocations: int

    model_config = {"extra": "forbid"}


class ProcessedTrajectory(BaseModel):
    """Compact ATIF projection suitable for parsing, analysis, or LLM judges."""

    task: ProcessedTask
    transcript: list[ProcessedTranscriptItem]
    summary: PreprocessSummary

    model_config = {"extra": "forbid"}

    def to_json_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        """Return a JSON-ready dictionary."""
        return self.model_dump(mode="json", exclude_none=exclude_none)


class _MatchedResult(BaseModel):
    content: str | None
    step: Step | None = None
    observation_result: ObservationResult | None = None
    missing: bool = False

    model_config = {"arbitrary_types_allowed": True}


def load_trajectory(path: Path) -> Trajectory:
    """Load and validate an ATIF trajectory file."""
    return Trajectory.model_validate_json(path.read_text())


def preprocess_trajectory_file(
    trajectory_path: Path,
    *,
    max_result_chars: int = 4000,
    max_arguments_chars: int = 2000,
    max_message_chars: int = 4000,
    include_copied_context: bool = False,
    include_status_basis: bool = False,
) -> ProcessedTrajectory:
    """Load an ATIF file and preprocess it into a compact analysis packet."""
    return preprocess_trajectory(
        load_trajectory(trajectory_path),
        max_result_chars=max_result_chars,
        max_arguments_chars=max_arguments_chars,
        max_message_chars=max_message_chars,
        include_copied_context=include_copied_context,
        include_status_basis=include_status_basis,
    )


def preprocess_trajectory(
    trajectory: Trajectory,
    *,
    max_result_chars: int = 4000,
    max_arguments_chars: int = 2000,
    max_message_chars: int = 4000,
    include_copied_context: bool = False,
    include_status_basis: bool = False,
) -> ProcessedTrajectory:
    """Project ATIF into a compact packet for hallucination-style analysis.

    The transformer keeps observable user/system/agent text and joins structured
    tool calls to their recorded results in one chronological transcript.
    """
    if max_result_chars < 1:
        raise ValueError("max_result_chars must be at least 1")
    if max_arguments_chars < 1:
        raise ValueError("max_arguments_chars must be at least 1")
    if max_message_chars < 1:
        raise ValueError("max_message_chars must be at least 1")

    steps = [
        step
        for step in trajectory.steps
        if include_copied_context or not step.is_copied_context
    ]
    transcript: list[ProcessedTranscriptItem] = []
    for index, step in enumerate(steps):
        if step.source != "agent" or _is_tool_result_step(step):
            continue

        message = _compact_optional_text(
            _content_to_text(step.message).strip(),
            max_chars=max_message_chars,
        )
        if message:
            transcript.append(ProcessedTranscriptItem(agent_message=message))

        for tool_index, tool_call in enumerate(step.tool_calls or []):
            match = _match_tool_result(step, tool_call, tool_index, steps, index)
            result = _build_result(
                tool_call.function_name,
                match,
                max_chars=max_result_chars,
                include_status_basis=include_status_basis,
            )
            transcript.append(
                ProcessedTranscriptItem(
                    tool_invocation=_build_invocation(
                        name=tool_call.function_name,
                        invocation_id=tool_call.tool_call_id,
                        arguments=tool_call.arguments,
                        result=result,
                        max_arguments_chars=max_arguments_chars,
                    )
                )
            )

    return ProcessedTrajectory(
        task=_extract_task(steps, max_chars=max_message_chars),
        transcript=transcript,
        summary=PreprocessSummary(
            agent_messages=sum(1 for item in transcript if item.agent_message),
            tool_invocations=sum(1 for item in transcript if item.tool_invocation),
        ),
    )


def normalize_name(name: str) -> str:
    """Normalize a status or tool name for simple comparisons."""
    return name.strip().lower()


def compact_text(text: str | None, *, max_chars: int = 4000) -> CompactedText:
    """Keep the beginning and end of long text."""
    if not text:
        return CompactedText(content_excerpt=None)

    if len(text) <= max_chars:
        return CompactedText(
            content_excerpt=text,
            truncated=False,
        )

    marker = "\n...[TRUNCATED]...\n"
    if max_chars <= len(marker) + 2:
        excerpt = text[:max_chars]
    else:
        content_chars = max_chars - len(marker)
        head_chars = min(1500, max(1, content_chars // 3))
        tail_chars = max(1, content_chars - head_chars)
        excerpt = text[:head_chars] + marker + text[-tail_chars:]
    return CompactedText(
        content_excerpt=excerpt,
        truncated=True,
    )


def _build_invocation(
    *,
    name: str,
    invocation_id: str,
    arguments: Any,
    result: ProcessedResult,
    max_arguments_chars: int,
) -> ProcessedInvocation:
    arguments_text = _json_text(arguments)
    compacted_arguments = compact_text(arguments_text, max_chars=max_arguments_chars)
    return ProcessedInvocation(
        invocation_id=invocation_id,
        name=name,
        arguments_excerpt=compacted_arguments.content_excerpt,
        arguments_truncated=compacted_arguments.truncated,
        result=result,
    )


def _build_result(
    tool_name: str,
    match: _MatchedResult,
    *,
    max_chars: int,
    include_status_basis: bool,
) -> ProcessedResult:
    if match.missing:
        compacted = compact_text(
            "No corresponding tool result was recorded.",
            max_chars=max_chars,
        )
        return ProcessedResult(
            content_excerpt=compacted.content_excerpt,
            truncated=compacted.truncated,
            success=False,
            status_basis=(
                "no corresponding tool result was recorded"
                if include_status_basis
                else None
            ),
        )

    success, status_basis, _metadata = _infer_tool_success(
        tool_name,
        result_step=match.step,
        observation_result=match.observation_result,
        content=match.content,
    )
    compacted = compact_text(match.content, max_chars=max_chars)
    return ProcessedResult(
        content_excerpt=compacted.content_excerpt,
        truncated=compacted.truncated,
        success=success,
        status_basis=status_basis if include_status_basis else None,
    )


def _match_tool_result(
    action_step: Step,
    tool_call: ToolCall,
    tool_index: int,
    steps: list[Step],
    action_index: int,
) -> _MatchedResult:
    source_match = _find_source_call_id_match(action_step, tool_call)
    if source_match is not None:
        return source_match

    result_run = _collect_following_tool_result_steps(steps, action_index + 1)
    for result_step in result_run:
        source_match = _find_source_call_id_match(result_step, tool_call)
        if source_match is not None:
            return source_match

    for result_step in result_run:
        if _step_tool_call_id(result_step) == tool_call.tool_call_id:
            return _MatchedResult(
                content=_extract_result_text(result_step),
                step=result_step,
                observation_result=_first_observation_result(result_step),
            )

    if action_step.observation is not None and len(action_step.tool_calls or []) == 1:
        return _MatchedResult(
            content=_extract_observation_text(action_step),
            step=action_step,
            observation_result=_first_observation_result(action_step),
        )

    if tool_index < len(result_run):
        result_step = result_run[tool_index]
        return _MatchedResult(
            content=_extract_result_text(result_step),
            step=result_step,
            observation_result=_first_observation_result(result_step),
        )

    return _MatchedResult(content=None, missing=True)


def _collect_following_tool_result_steps(
    steps: list[Step],
    start_index: int,
) -> list[Step]:
    result_steps = []
    for step in steps[start_index:]:
        if step.source == "user":
            break
        if step.tool_calls:
            break
        if not _is_tool_result_step(step):
            break
        result_steps.append(step)
    return result_steps


def _find_source_call_id_match(
    step: Step,
    tool_call: ToolCall,
) -> _MatchedResult | None:
    if step.observation is None:
        return None
    for result in step.observation.results:
        if result.source_call_id == tool_call.tool_call_id:
            return _MatchedResult(
                content=_observation_result_to_text(result),
                step=step,
                observation_result=result,
            )
    return None


def _infer_tool_success(
    tool_name: str,
    *,
    result_step: Step | None,
    observation_result: ObservationResult | None,
    content: str | None,
) -> tuple[bool, str, dict[str, Any]]:
    metadata = _collect_status_metadata(result_step, observation_result, content)
    if _metadata_truthy(metadata, "timed_out", "timedOut", "timeout"):
        return False, "tool execution timed out", metadata

    normalized_tool_name = normalize_name(tool_name)
    if normalized_tool_name in _SHELL_TOOL_NAMES:
        shell_result = _infer_shell_success(metadata, content)
        if shell_result is not None:
            return (*shell_result, metadata)

    is_error = _metadata_bool(metadata, "isError", "is_error", "error")
    if is_error is True:
        return False, "explicit structured error flag", metadata
    if is_error is False:
        return True, "explicit structured success flag", metadata

    status = _metadata_status(metadata)
    if status in _SUCCESS_STATUSES:
        return True, f"explicit structured status: {status}", metadata
    if status in _FAILURE_STATUSES:
        return False, f"explicit structured status: {status}", metadata

    http_status = _metadata_int(metadata, "http_status", "httpStatus", "status_code")
    if http_status is not None:
        success = 200 <= http_status < 400
        return success, f"HTTP status {http_status}", metadata

    if content and _looks_like_error_text(content):
        return False, "conservative error-pattern inference", metadata
    if content:
        return True, "tool result content was recorded", metadata
    return False, "tool execution success could not be established", metadata


def _infer_shell_success(
    metadata: Mapping[str, Any],
    content: str | None,
) -> tuple[bool, str] | None:
    exit_code = _metadata_int(
        metadata,
        "exec_exit_code",
        "exit_code",
        "exitCode",
        "returncode",
        "return_code",
    )
    if exit_code is not None:
        if exit_code in {126, 127}:
            return (
                False,
                f"process failed to start or invoke command: exit code {exit_code}",
            )
        return True, f"process completed with exit code {exit_code}"

    status = _metadata_status(metadata)
    if status in {"completed", "complete", "success", "succeeded", "ok"}:
        return True, f"explicit structured status: {status}"
    if status in {"timeout", "timed_out", "cancelled", "canceled", "rejected"}:
        return False, f"explicit structured status: {status}"

    if content and _looks_like_command_start_failure(content):
        return False, "command could not be started"
    return None


def _collect_status_metadata(
    result_step: Step | None,
    observation_result: ObservationResult | None,
    content: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if observation_result and observation_result.extra:
        metadata.update(observation_result.extra)
    if result_step and result_step.extra:
        metadata.update(result_step.extra)
    parsed = _parse_json_object(content)
    if parsed is not None:
        _merge_known_status_fields(metadata, parsed)
    return metadata


def _merge_known_status_fields(
    metadata: dict[str, Any], parsed: Mapping[str, Any]
) -> None:
    for key in (
        "error",
        "exitCode",
        "exit_code",
        "httpStatus",
        "http_status",
        "isError",
        "is_error",
        "status",
        "statusCode",
        "status_code",
        "timedOut",
        "timed_out",
        "timeout",
    ):
        if key in parsed and key not in metadata:
            metadata[key] = parsed[key]


def _parse_json_object(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _metadata_status(metadata: Mapping[str, Any]) -> str | None:
    for key in ("exec_status", "status", "state", "result"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_name(value).replace("-", "_")
    return None


def _metadata_bool(metadata: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
    return None


def _metadata_truthy(metadata: Mapping[str, Any], *keys: str) -> bool:
    return any(bool(metadata.get(key)) for key in keys)


def _metadata_int(metadata: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            return int(value)
    return None


def _looks_like_error_text(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in _ERROR_PATTERNS)


def _looks_like_command_start_failure(text: str) -> bool:
    lowered = text.lower()
    return any(
        pattern in lowered
        for pattern in (
            "command not found",
            "executable file not found",
            "no such file or directory",
            "permission denied",
            "could not start",
        )
    )


def _extract_task(steps: list[Step], *, max_chars: int) -> ProcessedTask:
    user_message = None
    for step in steps:
        if step.source != "user":
            continue
        compacted = _compact_optional_text(
            _content_to_text(step.message), max_chars=max_chars
        )
        if compacted:
            user_message = compacted
            break

    system_messages = [
        compacted
        for step in steps
        if step.source == "system"
        for compacted in [
            _compact_optional_text(_content_to_text(step.message), max_chars=max_chars)
        ]
        if compacted
    ]
    return ProcessedTask(
        user_message=user_message,
        system_messages=system_messages or None,
    )


def _compact_optional_text(text: str | None, *, max_chars: int) -> str | None:
    return compact_text(text, max_chars=max_chars).content_excerpt


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
    result = _extract_observation_text(step)
    if result:
        return result
    text = _content_to_text(step.message).strip()
    return text or None


def _extract_observation_text(step: Step) -> str | None:
    if step.observation is None:
        return None
    parts = []
    for result in step.observation.results:
        text = _observation_result_to_text(result)
        if text:
            parts.append(text)
    text = "\n\n".join(parts)
    return text or None


def _first_observation_result(step: Step) -> ObservationResult | None:
    if step.observation is None or not step.observation.results:
        return None
    return step.observation.results[0]


def _observation_result_to_text(result: ObservationResult) -> str | None:
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


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
