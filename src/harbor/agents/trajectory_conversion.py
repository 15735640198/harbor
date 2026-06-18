"""Standalone conversion of native agent harness logs to ATIF trajectories."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from harbor.models.trajectories import Trajectory
from harbor.utils.trajectory_utils import format_trajectory_json
from harbor.utils.trajectory_validator import TrajectoryValidator


class TrajectoryConversionError(RuntimeError):
    """Raised when native agent output cannot be converted to ATIF."""


@dataclass(frozen=True)
class TrajectoryConverter:
    """Agent-specific converter entry registered with the CLI."""

    agent_name: str
    is_candidate: Callable[[Path], bool]
    convert: Callable[[Path], Trajectory | None]


@dataclass(frozen=True)
class ConversionOutcome:
    """Result for a single conversion target."""

    input_dir: Path
    output_path: Path
    status: str
    message: str | None = None


@dataclass(frozen=True)
class ConversionSummary:
    """Aggregate result for a conversion command."""

    outcomes: list[ConversionOutcome]

    @property
    def converted(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "converted")

    @property
    def skipped(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "failed")


def list_converter_names() -> list[str]:
    """Return supported agent names for native-output conversion."""

    return sorted(_CONVERTERS)


def get_converter(agent_name: str) -> TrajectoryConverter:
    """Return converter for an agent name, or raise a helpful error."""

    converter = _CONVERTERS.get(agent_name)
    if converter is None:
        supported = ", ".join(list_converter_names())
        raise TrajectoryConversionError(
            f"Unsupported agent for trajectory conversion: {agent_name}. "
            f"Supported agents: {supported}"
        )
    return converter


def convert_one(
    *,
    agent_name: str,
    input_dir: Path,
    output_path: Path | None = None,
    force: bool = False,
    validate: bool = True,
) -> ConversionOutcome:
    """Convert one native harness output directory to an ATIF trajectory file."""

    converter = get_converter(agent_name)
    input_dir = input_dir.resolve()
    if not input_dir.exists():
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=output_path or input_dir / "trajectory.json",
            status="failed",
            message=f"Input path does not exist: {input_dir}",
        )
    if not input_dir.is_dir():
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=output_path or input_dir / "trajectory.json",
            status="failed",
            message=f"Input path is not a directory: {input_dir}",
        )
    if not converter.is_candidate(input_dir):
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=output_path or input_dir / "trajectory.json",
            status="failed",
            message=f"No native {agent_name} trajectory output found in {input_dir}",
        )

    resolved_output = (output_path or input_dir / "trajectory.json").resolve()
    if resolved_output.exists() and not force:
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=resolved_output,
            status="skipped",
            message="output exists; pass --force to overwrite",
        )

    try:
        trajectory = converter.convert(input_dir)
    except Exception as exc:
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=resolved_output,
            status="failed",
            message=f"conversion failed: {exc}",
        )

    if trajectory is None:
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=resolved_output,
            status="failed",
            message="converter produced no trajectory",
        )

    trajectory_data = trajectory.to_json_dict()
    if validate:
        validator = TrajectoryValidator()
        if not validator.validate(trajectory_data, validate_images=False):
            return ConversionOutcome(
                input_dir=input_dir,
                output_path=resolved_output,
                status="failed",
                message="validation failed: " + "; ".join(validator.get_errors()),
            )

    try:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(format_trajectory_json(trajectory_data))
    except OSError as exc:
        return ConversionOutcome(
            input_dir=input_dir,
            output_path=resolved_output,
            status="failed",
            message=f"write failed: {exc}",
        )

    return ConversionOutcome(
        input_dir=input_dir,
        output_path=resolved_output,
        status="converted",
    )


def convert_recursive(
    *,
    agent_name: str,
    root: Path,
    force: bool = False,
    validate: bool = True,
) -> ConversionSummary:
    """Convert all matching agent log directories under a root."""

    converter = get_converter(agent_name)
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        return ConversionSummary(
            [
                ConversionOutcome(
                    input_dir=root,
                    output_path=root / "trajectory.json",
                    status="failed",
                    message=f"Recursive root is not a directory: {root}",
                )
            ]
        )

    candidates = _discover_agent_dirs(root, converter)
    if not candidates:
        return ConversionSummary(
            [
                ConversionOutcome(
                    input_dir=root,
                    output_path=root / "trajectory.json",
                    status="failed",
                    message=f"No native {agent_name} trajectory outputs found under {root}",
                )
            ]
        )

    outcomes = [
        convert_one(
            agent_name=agent_name,
            input_dir=candidate,
            force=force,
            validate=validate,
        )
        for candidate in candidates
    ]
    return ConversionSummary(outcomes)


def _discover_agent_dirs(root: Path, converter: TrajectoryConverter) -> list[Path]:
    candidates: list[Path] = []
    if converter.is_candidate(root):
        candidates.append(root)

    for path in sorted(root.rglob("agent")):
        if not path.is_dir():
            continue
        if path in candidates:
            continue
        if converter.is_candidate(path):
            candidates.append(path)
    return candidates


def _instantiate(agent_cls: type, logs_dir: Path):
    return agent_cls(logs_dir=logs_dir)


def _has_any(path: Path, names: tuple[str, ...]) -> bool:
    return any((path / name).exists() for name in names)


def _convert_session_agent(agent_cls: type, logs_dir: Path) -> Trajectory | None:
    agent = _instantiate(agent_cls, logs_dir)
    session_dir = agent._get_session_dir()
    if session_dir is None:
        return None
    return agent._convert_events_to_trajectory(session_dir)


def _convert_openhands(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.openhands import OpenHands

    agent = OpenHands(logs_dir=logs_dir)
    session_dir = agent._get_session_dir()
    if session_dir is None:
        return None
    events_dir = session_dir / "events"
    if not events_dir.exists():
        return None
    return agent._convert_events_to_trajectory(events_dir)


def _convert_gemini(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.gemini_cli import GeminiCli

    agent = GeminiCli(logs_dir=logs_dir)
    for name in ("gemini-cli.trajectory.jsonl", "gemini-cli.trajectory.json"):
        candidate = logs_dir / name
        if candidate.exists():
            raw = agent._load_gemini_session(candidate)
            return agent._convert_gemini_to_atif(raw) if raw else None
    return None


def _convert_openclaw(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.openclaw import (
        OpenClaw,
        openclaw_session_jsonl_to_atif_steps,
    )

    agent = OpenClaw(logs_dir=logs_dir)
    envelope = agent._parse_stdout()
    json_path = logs_dir / "openclaw.json"
    if envelope is None and json_path.exists():
        envelope = agent._load_json_object(json_path.read_text(errors="replace"))
    if not envelope:
        return None
    instruction_path = logs_dir / "instruction.txt"
    instruction = ""
    if instruction_path.exists():
        instruction = instruction_path.read_text(errors="replace")
    session_path = logs_dir / "openclaw.session.jsonl"
    session_steps = openclaw_session_jsonl_to_atif_steps(
        session_path,
        instruction=instruction,
        model_name=agent.model_name or "",
    )
    if session_steps:
        return agent._trajectory_from_envelope_with_steps(envelope, session_steps)
    return agent._convert_envelope_to_trajectory(envelope, instruction)


def _convert_opencode(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.opencode import OpenCode

    agent = OpenCode(logs_dir=logs_dir)
    events = agent._parse_stdout()
    return agent._convert_events_to_trajectory(events) if events else None


def _convert_qwen(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.qwen_code import QwenCode

    agent = QwenCode(logs_dir=logs_dir)
    events = agent._parse_jsonl()
    return agent._convert_events_to_trajectory(events) if events else None


def _convert_goose(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.goose import Goose

    txt_path = logs_dir / "goose.txt"
    if not txt_path.exists():
        return None
    agent = Goose(logs_dir=logs_dir)
    log_text = txt_path.read_text(errors="replace")
    session_id = str(uuid.uuid4())
    try:
        trajectory = agent._convert_goose_stream_json_to_atif(log_text, session_id)
    except Exception:
        trajectory = None
    if trajectory is None:
        return agent._convert_goose_to_atif(log_text, session_id)
    return trajectory


def _convert_copilot(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.copilot_cli import CopilotCli

    agent = CopilotCli(logs_dir=logs_dir)
    return agent._convert_jsonl_to_trajectory(logs_dir / agent._TRAJECTORY_FILENAME)


def _convert_cline(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.cline.cline import ClineCli
    from harbor.agents.installed.cline.trajectory import convert_messages_to_trajectory

    agent = ClineCli(logs_dir=logs_dir)
    session_file = agent._find_session_messages_file()
    if session_file is None:
        return None
    messages_doc = json.loads(session_file.read_text(encoding="utf-8"))
    return convert_messages_to_trajectory(
        messages_doc,
        agent_name=agent.name(),
        agent_version=agent.version() or "unknown",
    )


def _convert_trae(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.trae_agent import TraeAgent

    agent = TraeAgent(logs_dir=logs_dir)
    raw = agent._load_trajectory()
    return agent._convert_trajectory_to_atif(raw) if raw else None


def _convert_mini_swe(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.mini_swe_agent import convert_mini_swe_agent_to_atif

    path = logs_dir / "mini-swe-agent.trajectory.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    return convert_mini_swe_agent_to_atif(raw, str(uuid.uuid4()))


def _convert_swe(logs_dir: Path) -> Trajectory | None:
    from harbor.agents.installed.swe_agent import SweAgent, convert_swe_agent_to_atif

    agent = SweAgent(logs_dir=logs_dir)
    path = agent._find_trajectory_file() or logs_dir / "swe-agent.trajectory.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    return convert_swe_agent_to_atif(raw, str(uuid.uuid4()))


def _codex_candidate(path: Path) -> bool:
    return (path / "sessions").is_dir() and any((path / "sessions").rglob("*.jsonl"))


def _claude_candidate(path: Path) -> bool:
    return (path / "sessions" / "projects").is_dir() and any(
        (path / "sessions" / "projects").rglob("*.jsonl")
    )


def _openhands_candidate(path: Path) -> bool:
    return (path / "sessions").is_dir() and any(
        child.is_dir() and (child / "events").is_dir()
        for child in (path / "sessions").iterdir()
    )


def _qwen_candidate(path: Path) -> bool:
    return (path / "qwen-sessions").is_dir() and any(
        (path / "qwen-sessions").rglob("*.jsonl")
    )


def _cline_candidate(path: Path) -> bool:
    return (path / "sessions").is_dir() and any(
        (path / "sessions").glob("*/*.messages.json")
    )


_CONVERTERS: dict[str, TrajectoryConverter] = {}


def _register(converter: TrajectoryConverter) -> None:
    _CONVERTERS[converter.agent_name] = converter


def _register_default_converters() -> None:
    from harbor.agents.installed.claude_code import ClaudeCode
    from harbor.agents.installed.codex import Codex

    _register(
        TrajectoryConverter(
            agent_name="codex",
            is_candidate=_codex_candidate,
            convert=lambda path: _convert_session_agent(Codex, path),
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="claude-code",
            is_candidate=_claude_candidate,
            convert=lambda path: _convert_session_agent(ClaudeCode, path),
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="openhands",
            is_candidate=_openhands_candidate,
            convert=_convert_openhands,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="gemini-cli",
            is_candidate=lambda path: _has_any(
                path, ("gemini-cli.trajectory.jsonl", "gemini-cli.trajectory.json")
            ),
            convert=_convert_gemini,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="openclaw",
            is_candidate=lambda path: _has_any(path, ("openclaw.json", "openclaw.txt")),
            convert=_convert_openclaw,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="opencode",
            is_candidate=lambda path: (path / "opencode.txt").exists(),
            convert=_convert_opencode,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="qwen-coder",
            is_candidate=_qwen_candidate,
            convert=_convert_qwen,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="goose",
            is_candidate=lambda path: (path / "goose.txt").exists(),
            convert=_convert_goose,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="copilot-cli",
            is_candidate=lambda path: (path / "copilot-cli.jsonl").exists(),
            convert=_convert_copilot,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="cline-cli",
            is_candidate=_cline_candidate,
            convert=_convert_cline,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="trae-agent",
            is_candidate=lambda path: (path / "trae-trajectory.json").exists(),
            convert=_convert_trae,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="mini-swe-agent",
            is_candidate=lambda path: (
                path / "mini-swe-agent.trajectory.json"
            ).exists(),
            convert=_convert_mini_swe,
        )
    )
    _register(
        TrajectoryConverter(
            agent_name="swe-agent",
            is_candidate=lambda path: (
                (path / "swe-agent.trajectory.json").exists()
                or any(path.glob("**/*.traj"))
            ),
            convert=_convert_swe,
        )
    )


_register_default_converters()
