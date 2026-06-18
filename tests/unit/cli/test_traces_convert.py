import json

from typer.testing import CliRunner

from harbor.agents.trajectory_conversion import (
    convert_one,
    get_converter,
    list_converter_names,
)
from harbor.cli.main import app


runner = CliRunner()


def _write_copilot_jsonl(agent_dir):
    rows = [
        {
            "type": "message",
            "role": "user",
            "content": "Create hello.txt",
        },
        {
            "type": "message",
            "role": "assistant",
            "content": "Done",
            "model": "gpt-4.1",
        },
        {
            "type": "usage",
            "input_tokens": 12,
            "output_tokens": 3,
        },
    ]
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "copilot-cli.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_converter_registry_contains_expected_agents():
    names = list_converter_names()

    assert "copilot-cli" in names
    assert "codex" in names
    assert get_converter("copilot-cli").agent_name == "copilot-cli"


def test_convert_one_refuses_existing_output_without_force(tmp_path):
    agent_dir = tmp_path / "agent"
    _write_copilot_jsonl(agent_dir)
    output = agent_dir / "trajectory.json"
    output.write_text("{}", encoding="utf-8")

    outcome = convert_one(agent_name="copilot-cli", input_dir=agent_dir)

    assert outcome.status == "skipped"
    assert "pass --force" in (outcome.message or "")
    assert output.read_text(encoding="utf-8") == "{}"


def test_convert_one_force_overwrites_existing_output(tmp_path):
    agent_dir = tmp_path / "agent"
    _write_copilot_jsonl(agent_dir)
    output = agent_dir / "trajectory.json"
    output.write_text("{}", encoding="utf-8")

    outcome = convert_one(agent_name="copilot-cli", input_dir=agent_dir, force=True)

    assert outcome.status == "converted"
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["agent"]["name"] == "copilot-cli"
    assert data["final_metrics"]["total_prompt_tokens"] == 12


def test_convert_one_codex_session_layout(tmp_path):
    session_dir = tmp_path / "agent" / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    events = [
        {"type": "session_meta", "payload": {"id": "session-1"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Done."}],
            },
        },
    ]
    (session_dir / "session.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    outcome = convert_one(agent_name="codex", input_dir=tmp_path / "agent")

    assert outcome.status == "converted"
    data = json.loads((tmp_path / "agent" / "trajectory.json").read_text())
    assert data["schema_version"] == "ATIF-v1.7"
    assert data["agent"]["name"] == "codex"


def test_convert_one_openclaw_envelope(tmp_path):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "instruction.txt").write_text("Say hello", encoding="utf-8")
    (agent_dir / "openclaw.txt").write_text(
        json.dumps(
            {
                "meta": {
                    "agentMeta": {
                        "sessionId": "openclaw-session",
                        "usage": {"input": 10, "output": 2, "cacheRead": 3},
                    }
                },
                "payloads": [{"text": "Hello", "isReasoning": False}],
            }
        ),
        encoding="utf-8",
    )

    outcome = convert_one(agent_name="openclaw", input_dir=agent_dir)

    assert outcome.status == "converted"
    data = json.loads((agent_dir / "trajectory.json").read_text())
    assert data["agent"]["name"] == "openclaw"
    assert data["session_id"] == "openclaw-session"
    assert data["final_metrics"]["total_prompt_tokens"] == 13


def test_traces_convert_single_writes_trajectory(tmp_path):
    agent_dir = tmp_path / "agent"
    _write_copilot_jsonl(agent_dir)

    result = runner.invoke(
        app,
        [
            "traces",
            "convert",
            "--agent",
            "copilot-cli",
            "--path",
            str(agent_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "converted=1" in result.output
    data = json.loads((agent_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert data["agent"]["name"] == "copilot-cli"


def test_traces_convert_out_rejected_with_recursive(tmp_path):
    result = runner.invoke(
        app,
        [
            "traces",
            "convert",
            "--agent",
            "copilot-cli",
            "--path",
            str(tmp_path),
            "--recursive",
            "--out",
            str(tmp_path / "trajectory.json"),
        ],
    )

    assert result.exit_code == 1
    assert "--out is only supported without --recursive" in result.output


def test_traces_convert_recursive_writes_each_agent_dir(tmp_path):
    first = tmp_path / "trial-1" / "agent"
    second = tmp_path / "trial-2" / "agent"
    _write_copilot_jsonl(first)
    _write_copilot_jsonl(second)

    result = runner.invoke(
        app,
        [
            "traces",
            "convert",
            "--agent",
            "copilot-cli",
            "--path",
            str(tmp_path),
            "--recursive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "converted=2" in result.output
    assert (first / "trajectory.json").exists()
    assert (second / "trajectory.json").exists()


def test_traces_convert_recursive_reports_partial_failure(tmp_path, monkeypatch):
    import harbor.agents.trajectory_conversion as conversion

    first = tmp_path / "trial-1" / "agent"
    second = tmp_path / "trial-2" / "agent"
    _write_copilot_jsonl(first)
    _write_copilot_jsonl(second)

    original = conversion._CONVERTERS["copilot-cli"]

    def convert(path):
        if path == second.resolve():
            raise RuntimeError("bad native log")
        return original.convert(path)

    monkeypatch.setitem(
        conversion._CONVERTERS,
        "copilot-cli",
        conversion.TrajectoryConverter(
            agent_name=original.agent_name,
            is_candidate=original.is_candidate,
            convert=convert,
        ),
    )

    result = runner.invoke(
        app,
        [
            "traces",
            "convert",
            "--agent",
            "copilot-cli",
            "--path",
            str(tmp_path),
            "--recursive",
        ],
    )

    assert result.exit_code == 1
    assert "converted=1" in result.output
    assert "failed=1" in result.output
