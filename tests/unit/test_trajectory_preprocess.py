from harbor.models.trajectories import (
    Agent,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.utils.trajectory_preprocess import preprocess_trajectory


def _agent_messages(packet):
    return [item.agent_message for item in packet.transcript if item.agent_message]


def _tool_invocations(packet):
    return [
        item.tool_invocation
        for item in packet.transcript
        if item.tool_invocation is not None
    ]


def test_preprocess_builds_chronological_transcript_with_joined_tool_result():
    trajectory = Trajectory(
        agent=Agent(name="openclaw", version="1.0"),
        steps=[
            Step(step_id=1, source="user", message="Fix the bug."),
            Step(
                step_id=2,
                source="agent",
                message="Running tests.",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_tests",
                        function_name="exec",
                        arguments={"command": "pytest"},
                    )
                ],
            ),
            Step(
                step_id=3,
                source="agent",
                message="2 failed, 18 passed",
                observation=Observation(
                    results=[ObservationResult(content="2 failed, 18 passed")]
                ),
                llm_call_count=0,
                extra={
                    "openclaw_role": "toolResult",
                    "tool_call_id": "call_tests",
                    "exec_exit_code": 1,
                    "exec_status": "failed",
                    "isError": False,
                },
            ),
            Step(step_id=4, source="agent", message="All tests pass now."),
        ],
    )

    packet = preprocess_trajectory(trajectory)

    assert packet.task.user_message == "Fix the bug."
    assert _agent_messages(packet) == ["Running tests.", "All tests pass now."]
    assert packet.summary.agent_messages == 2
    assert packet.summary.tool_invocations == 1

    invocation = _tool_invocations(packet)[0]
    assert invocation.invocation_id == "call_tests"
    assert invocation.name == "exec"
    assert invocation.result.success is True
    assert invocation.result.status_basis is None
    assert invocation.result.content_excerpt == "2 failed, 18 passed"

    packet_data = packet.to_json_dict()
    assert packet_data["transcript"][0] == {"agent_message": "Running tests."}
    assert (
        "status_basis" not in packet_data["transcript"][1]["tool_invocation"]["result"]
    )
    assert (
        "original_char_count"
        not in packet_data["transcript"][1]["tool_invocation"]["result"]
    )
    assert (
        "subsequent_agent_message"
        not in packet_data["transcript"][1]["tool_invocation"]
    )
    assert packet_data["transcript"][2] == {"agent_message": "All tests pass now."}


def test_preprocess_can_include_status_basis():
    trajectory = Trajectory(
        agent=Agent(name="openclaw", version="1.0"),
        steps=[
            Step(step_id=1, source="user", message="Fix the bug."),
            Step(
                step_id=2,
                source="agent",
                message="Running tests.",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_tests",
                        function_name="exec",
                        arguments={"command": "pytest"},
                    )
                ],
            ),
            Step(
                step_id=3,
                source="agent",
                message="2 failed, 18 passed",
                observation=Observation(
                    results=[ObservationResult(content="2 failed, 18 passed")]
                ),
                llm_call_count=0,
                extra={
                    "openclaw_role": "toolResult",
                    "tool_call_id": "call_tests",
                    "exec_exit_code": 1,
                },
            ),
        ],
    )

    packet = preprocess_trajectory(trajectory, include_status_basis=True)

    invocation = _tool_invocations(packet)[0]
    assert invocation.result.status_basis == "process completed with exit code 1"
    result_data = packet.to_json_dict()["transcript"][1]["tool_invocation"]["result"]
    assert result_data["status_basis"] == "process completed with exit code 1"


def test_preprocess_marks_shell_command_not_found_as_failed_execution():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(step_id=1, source="user", message="Inspect the database."),
            Step(
                step_id=2,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_sqlite",
                        function_name="exec",
                        arguments={"command": "sqlite3 users.db .schema"},
                    )
                ],
            ),
            Step(
                step_id=3,
                source="agent",
                message="/usr/bin/sh: 1: sqlite3: not found\n\nCommand not found",
                observation=Observation(
                    results=[
                        ObservationResult(
                            content=(
                                "/usr/bin/sh: 1: sqlite3: not found\n\n"
                                "Command not found"
                            )
                        )
                    ]
                ),
                llm_call_count=0,
                extra={
                    "openclaw_role": "toolResult",
                    "tool_call_id": "call_sqlite",
                    "exec_exit_code": 127,
                    "exec_status": "failed",
                    "isError": False,
                },
            ),
        ],
    )

    packet = preprocess_trajectory(trajectory, include_status_basis=True)

    invocation = _tool_invocations(packet)[0]
    assert invocation.result.success is False
    assert invocation.result.status_basis == (
        "process failed to start or invoke command: exit code 127"
    )


def test_preprocess_marks_missing_result():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(step_id=1, source="user", message="Use a tool."),
            Step(
                step_id=2,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_missing",
                        function_name="magic_search",
                        arguments={"query": "alpha"},
                    )
                ],
            ),
        ],
    )

    packet = preprocess_trajectory(trajectory)

    invocation = _tool_invocations(packet)[0]
    assert invocation.result.success is False
    assert (
        invocation.result.content_excerpt
        == "No corresponding tool result was recorded."
    )


def test_preprocess_ignores_structured_skill_invocations():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(step_id=1, source="user", message="Use a skill."),
            Step(
                step_id=2,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_terminal",
                        function_name="terminal",
                        arguments={"command": "pwd"},
                    )
                ],
                observation=Observation(
                    results=[
                        ObservationResult(
                            source_call_id="call_terminal",
                            content="/workspace",
                        )
                    ]
                ),
                extra={
                    "skill_invocations": [
                        {
                            "id": "skill_1",
                            "name": "python-script-writer",
                            "arguments": {"task": "summarize"},
                            "success": True,
                            "result": "generated summary",
                        }
                    ]
                },
            ),
        ],
    )

    packet = preprocess_trajectory(trajectory)

    invocations = _tool_invocations(packet)
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.name == "terminal"
    assert invocation.result.content_excerpt == "/workspace"

    packet_data = packet.to_json_dict()
    tool_invocation_data = [
        item["tool_invocation"]
        for item in packet_data["transcript"]
        if "tool_invocation" in item
    ][0]
    assert set(packet_data) == {"task", "transcript", "summary"}
    assert "invocations" not in packet_data
    assert "agent" not in packet_data
    assert "schema_version" not in packet_data
    assert "final_agent_message" not in packet_data["task"]
    assert "step_id" not in tool_invocation_data
    assert "result_step_id" not in tool_invocation_data
    assert "original_arguments_char_count" not in tool_invocation_data
    assert "agent_message_before_invocation" not in tool_invocation_data
    assert "subsequent_agent_message" not in tool_invocation_data
    assert "exists" not in tool_invocation_data
    assert "metadata" not in tool_invocation_data["result"]
    assert "original_char_count" not in tool_invocation_data["result"]
    assert "skill_invocations" not in packet_data["summary"]
