import json

import pytest

from harbor.models.trajectories import (
    Agent,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.utils.trajectory_blocks import (
    action_ngrams,
    categorize_action,
    parse_trajectory_blocks,
    parse_trajectory_file,
    write_trajectory_block_analysis,
)


def test_parse_trajectory_blocks_uses_atif_fields():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(step_id=1, source="user", message="Fix the bug"),
            Step(
                step_id=2,
                source="agent",
                message="I will update the file.",
                reasoning_content="The file is missing the requested content.",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_1",
                        function_name="bash_command",
                        arguments={"keystrokes": "echo hi > hello.txt\n"},
                    )
                ],
                observation=Observation(
                    results=[
                        ObservationResult(
                            source_call_id="call_1",
                            content="created hello.txt",
                        )
                    ]
                ),
            ),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert len(blocks) == 1
    assert blocks[0].iteration == 0
    assert blocks[0].step_id == 2
    assert blocks[0].thought == "The file is missing the requested content."
    assert blocks[0].action.startswith("bash_command(")
    assert blocks[0].result == "created hello.txt"
    assert blocks[0].action_category == "Generate Fix"
    assert blocks[0].tool_call_id == "call_1"
    assert blocks[0].result_step_id == 2
    assert blocks[0].source_step_ids == [2]
    assert blocks[0].tool_calls == [
        {
            "tool_call_id": "call_1",
            "function_name": "bash_command",
            "arguments": {"keystrokes": "echo hi > hello.txt\n"},
        }
    ]


def test_parse_trajectory_blocks_falls_back_to_message_for_no_tool_agent_step():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(step_id=1, source="agent", message="Here is my explanation."),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert blocks[0].thought == "Here is my explanation."
    assert blocks[0].action == "agent_message"
    assert blocks[0].action_category == "Explain"


def test_parse_trajectory_blocks_merges_openclaw_tool_result_step():
    trajectory = Trajectory(
        agent=Agent(name="openclaw", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_1",
                        function_name="read",
                        arguments={"path": "/app/file.txt"},
                    )
                ],
            ),
            Step(
                step_id=2,
                source="agent",
                message="file contents",
                observation=Observation(
                    results=[ObservationResult(content="file contents")]
                ),
                llm_call_count=0,
                extra={"openclaw_role": "toolResult", "tool_call_id": "call_1"},
            ),
            Step(step_id=3, source="agent", message="Done."),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert len(blocks) == 2
    assert blocks[0].step_id == 1
    assert blocks[0].action == 'read({"path": "/app/file.txt"})'
    assert blocks[0].result == "file contents"
    assert blocks[0].action_category == "Explore"
    assert blocks[0].tool_call_id == "call_1"
    assert blocks[0].result_step_id == 2
    assert blocks[0].source_step_ids == [1, 2]
    assert blocks[1].step_id == 3
    assert blocks[1].action == "agent_message"
    assert blocks[1].action_category == "Explain"


def test_parse_trajectory_blocks_splits_multi_tool_step_and_matches_extra_ids():
    trajectory = Trajectory(
        agent=Agent(name="openclaw", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_read",
                        function_name="read",
                        arguments={"path": "/app/a.txt"},
                    ),
                    ToolCall(
                        tool_call_id="call_search",
                        function_name="web_search",
                        arguments={"query": "harbor"},
                    ),
                ],
            ),
            Step(
                step_id=2,
                source="agent",
                message="read output",
                observation=Observation(
                    results=[ObservationResult(content="read output")]
                ),
                llm_call_count=0,
                extra={"openclaw_role": "toolResult", "tool_call_id": "call_read"},
            ),
            Step(
                step_id=3,
                source="agent",
                message="search output",
                observation=Observation(
                    results=[ObservationResult(content="search output")]
                ),
                llm_call_count=0,
                extra={"openclaw_role": "toolResult", "tool_call_id": "call_search"},
            ),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert len(blocks) == 2
    assert [block.tool_call_id for block in blocks] == ["call_read", "call_search"]
    assert [block.result for block in blocks] == ["read output", "search output"]
    assert [block.action_category for block in blocks] == ["Explore", "Search"]


def test_parse_trajectory_blocks_matches_result_by_source_call_id():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_1",
                        function_name="exec",
                        arguments={"command": "python test_form.py"},
                    )
                ],
                observation=Observation(
                    results=[
                        ObservationResult(
                            source_call_id="call_1",
                            content="test passed",
                        )
                    ]
                ),
            ),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert len(blocks) == 1
    assert blocks[0].result == "test passed"
    assert blocks[0].result_step_id == 1
    assert blocks[0].action_category == "Run tests"


def test_parse_trajectory_blocks_uses_positional_result_fallback():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_1",
                        function_name="read",
                        arguments={"path": "/app/a.txt"},
                    ),
                    ToolCall(
                        tool_call_id="call_2",
                        function_name="read",
                        arguments={"path": "/app/b.txt"},
                    ),
                ],
            ),
            Step(
                step_id=2,
                source="agent",
                message="a",
                observation=Observation(results=[ObservationResult(content="a")]),
                llm_call_count=0,
            ),
            Step(
                step_id=3,
                source="agent",
                message="b",
                observation=Observation(results=[ObservationResult(content="b")]),
                llm_call_count=0,
            ),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert [block.result for block in blocks] == ["a", "b"]
    assert [block.result_step_id for block in blocks] == [2, 3]


def test_parse_trajectory_blocks_skips_copied_context_by_default():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="old context",
                is_copied_context=True,
            ),
            Step(step_id=2, source="agent", message="new work"),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)
    all_blocks = parse_trajectory_blocks(trajectory, include_copied_context=True)

    assert [block.step_id for block in blocks] == [2]
    assert [block.step_id for block in all_blocks] == [1, 2]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ('bash_command({"keystrokes": "rg TODO src"})', "Search"),
        ('bash_command({"keystrokes": "uv run pytest tests/unit"})', "Run tests"),
        ('str_replace_editor({"command": "view", "path": "a.py"})', "Explore"),
        (
            'str_replace_editor({"command": "str_replace", "path": "a.py"})',
            "Generate Fix",
        ),
        ('web_fetch({"url": "https://example.com"})', "Explore"),
        ('web_search({"query": "harbor"})', "Search"),
        ('browser({"action": "open", "url": "https://example.com"})', "Explore"),
        ('image({"image": "/app/success.png"})', "Explore"),
        ('pdf({"path": "/app/report.pdf"})', "Explore"),
        ('process({"action": "poll", "sessionId": "abc"})', "Explore"),
        ('exec({"command": "python test_form.py"})', "Run tests"),
        ('exec({"command": "pip install pandas"})', "Other"),
    ],
)
def test_categorize_action(action, expected):
    assert categorize_action(action) == expected


def test_action_ngrams_counts_category_sequences():
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="search",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_1",
                        function_name="bash_command",
                        arguments={"keystrokes": "rg TODO src\n"},
                    )
                ],
            ),
            Step(
                step_id=2,
                source="agent",
                message="fix",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_2",
                        function_name="str_replace_editor",
                        arguments={"command": "str_replace", "path": "a.py"},
                    )
                ],
            ),
            Step(
                step_id=3,
                source="agent",
                message="test",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_3",
                        function_name="bash_command",
                        arguments={"keystrokes": "uv run pytest tests/unit\n"},
                    )
                ],
            ),
        ],
    )

    blocks = parse_trajectory_blocks(trajectory)

    assert action_ngrams(blocks, n=2) == {
        ("Search", "Generate Fix"): 1,
        ("Generate Fix", "Run tests"): 1,
    }


def test_write_trajectory_block_analysis_outputs_paper_style_views(tmp_path):
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="search",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_1",
                        function_name="bash_command",
                        arguments={"keystrokes": "rg TODO src\n"},
                    )
                ],
                observation=Observation(
                    results=[ObservationResult(content="found TODO")]
                ),
            ),
            Step(
                step_id=2,
                source="agent",
                message="fix",
                tool_calls=[
                    ToolCall(
                        tool_call_id="call_2",
                        function_name="str_replace_editor",
                        arguments={"command": "str_replace", "path": "a.py"},
                    )
                ],
                observation=Observation(results=[ObservationResult(content="patched")]),
            ),
        ],
    )
    trajectory_path = tmp_path / "trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory.to_json_dict()))

    written = write_trajectory_block_analysis(
        trajectory_path,
        tmp_path / "analysis",
        ngram_size=2,
    )

    assert set(written) == {
        "blocks_jsonl",
        "actions_categories",
        "action_ngrams",
        "thoughts_actions",
        "thoughts_thoughts",
        "action_actions",
        "results_actions",
        "results_thoughts",
        "parse_diagnostics",
    }
    assert "0,1,Search" in written["actions_categories"].read_text()
    assert "Search -> Generate Fix,1" in written["action_ngrams"].read_text()
    assert "Thought at Iteration 0: search" in written["thoughts_actions"].read_text()
    assert (
        "Result at Iteration 0: found TODO" in written["results_thoughts"].read_text()
    )
    assert parse_trajectory_file(trajectory_path)[0].action_category == "Search"


def test_write_trajectory_block_analysis_reports_orphan_tool_result(tmp_path):
    trajectory = Trajectory(
        agent=Agent(name="test-agent", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message="orphan result",
                observation=Observation(results=[ObservationResult(content="orphan")]),
                llm_call_count=0,
                extra={"openclaw_role": "toolResult", "tool_call_id": "missing"},
            ),
        ],
    )
    trajectory_path = tmp_path / "trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory.to_json_dict()))

    written = write_trajectory_block_analysis(trajectory_path, tmp_path / "analysis")

    diagnostics = json.loads(written["parse_diagnostics"].read_text())
    assert diagnostics["orphan_tool_result_steps"] == [
        {"step_id": 1, "tool_call_id": "missing"}
    ]
    assert written["blocks_jsonl"].read_text() == ""
