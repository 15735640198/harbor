from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = (
    ROOT
    / "adapters"
    / "clawbench"
    / "src"
    / "clawbench_adapter"
    / "verifier_runtime.py"
)


def load_runtime():
    spec = importlib.util.spec_from_file_location(
        "clawbench_verifier_runtime_test", RUNTIME_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_execution_check_partial_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    monkeypatch.setattr(runtime, "WORKSPACE", tmp_path)
    (tmp_path / "ok.txt").write_text("hello\n", encoding="utf-8")
    task = {
        "completion": {
            "execution_checks": [
                {"name": "pass", "command": "cat ok.txt", "stdout_contains": ["hello"]},
                {
                    "name": "fail",
                    "command": "cat ok.txt",
                    "stdout_contains": ["missing"],
                },
            ]
        }
    }

    result = asyncio.run(
        runtime.verify_completion(
            task, {"messages": []}, runtime.runtime_values({"id": "x"})
        )
    )

    assert result["total_assertions"] == 2
    assert result["passed_assertions"] == 1
    assert result["score"] == 0.5


@pytest.mark.unit
def test_file_and_memory_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    monkeypatch.setattr(runtime, "WORKSPACE", tmp_path)
    (tmp_path / "evidence.md").write_text(
        "maintenance_notes.md says 18 months\n", encoding="utf-8"
    )
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "beta-regions.md").write_text(
        "us and eu\n", encoding="utf-8"
    )
    task = {
        "completion": {
            "files": [
                {
                    "path": "evidence.md",
                    "content_contains": ["maintenance_notes.md", "18 months"],
                }
            ],
            "memory": [
                {
                    "key_pattern": "beta.*region|region.*beta",
                    "value_contains": ["us", "eu"],
                }
            ],
        }
    }

    result = asyncio.run(
        runtime.verify_completion(
            task, {"messages": []}, runtime.runtime_values({"id": "x"})
        )
    )

    assert result["score"] == 1.0


@pytest.mark.unit
def test_trajectory_normalizes_atif_shell_steps() -> None:
    runtime = load_runtime()
    transcript = {
        "messages": [
            {
                "role": "assistant",
                "text": "I will inspect first.",
                "tool_calls": [
                    runtime.normalize_tool_call(
                        {
                            "name": "shell",
                            "input": {"command": "cat pricing.py"},
                            "output": "ok",
                        }
                    ),
                    runtime.normalize_tool_call(
                        {
                            "name": "apply_patch",
                            "input": {"path": "pricing.py"},
                            "output": "ok",
                        }
                    ),
                    runtime.normalize_tool_call(
                        {
                            "name": "shell",
                            "input": {"command": "pytest -q"},
                            "output": "passed",
                        }
                    ),
                ],
            }
        ]
    }

    result = runtime.evaluate_trajectory(
        transcript,
        {
            "required_families": ["read", "edit", "execute"],
            "min_distinct_families": 3,
            "require_read_before_mutation": True,
            "require_self_verification": True,
        },
    )

    assert result["score"] > 0.8
    assert result["self_verified"] is True


@pytest.mark.unit
def test_trajectory_normalizes_atif_tool_call_fields() -> None:
    runtime = load_runtime()
    transcript = {
        "messages": [
            {
                "role": "assistant",
                "text": "",
                "tool_calls": [
                    runtime.normalize_tool_call(
                        {
                            "tool_call_id": "call_read",
                            "function_name": "read",
                            "arguments": {"path": "/workspace/pipeline.py"},
                        }
                    ),
                    runtime.normalize_tool_call(
                        {
                            "tool_call_id": "call_edit",
                            "function_name": "edit",
                            "arguments": {
                                "path": "/workspace/pipeline.py",
                                "edits": [],
                            },
                        }
                    ),
                    runtime.normalize_tool_call(
                        {
                            "tool_call_id": "call_exec",
                            "function_name": "exec",
                            "arguments": {
                                "command": "python3 pipeline.py input/sales.csv"
                            },
                        }
                    ),
                ],
            }
        ]
    }

    calls = runtime.tool_call_sequence(transcript)
    result = runtime.evaluate_trajectory(
        transcript,
        {
            "required_families": ["read", "edit", "execute"],
            "min_distinct_families": 3,
            "require_read_before_mutation": True,
            "require_self_verification": True,
        },
    )

    assert [call["id"] for call in calls] == ["call_read", "call_edit", "call_exec"]
    assert result["distinct_families"] == ["edit", "execute", "read"]
    assert result["required_families_missing"] == []
    assert result["self_verified"] is True
    assert result["score"] > 0.8


@pytest.mark.unit
def test_behavior_scoring_detects_plan_progress_and_blocker() -> None:
    runtime = load_runtime()
    transcript = {
        "messages": [
            {
                "role": "assistant",
                "text": "I will first inspect the files, then run tests.",
                "tool_calls": [],
            },
            {
                "role": "assistant",
                "text": "Checking the failure now.",
                "tool_calls": [],
            },
            {
                "role": "assistant",
                "text": "I cannot access one optional source, but the fix is done.",
                "tool_calls": [],
            },
        ]
    }

    result = runtime.evaluate_behavior(
        {
            "require_plan": True,
            "require_progress_updates": True,
            "require_blocker_explanation": True,
        },
        transcript,
    )

    assert result["score"] == 1.0


@pytest.mark.unit
def test_judge_parser_and_composite_rules() -> None:
    runtime = load_runtime()

    parsed = runtime.parse_judge_response(
        '```json\n{"score": 0.8, "confidence": 0.7, "reason": "ok", "rubric_hits": ["a"], "rubric_misses": []}\n```',
        0.7,
    )
    malformed = runtime.parse_judge_response("no json here", 0.7)
    deterministic_failed = runtime.combine_run_score(
        0.5,
        1.0,
        1.0,
        1.0,
        has_deterministic_verifier=True,
        include_judge=True,
    )
    deterministic_passed = runtime.combine_run_score(
        1.0,
        1.0,
        1.0,
        0.5,
        has_deterministic_verifier=True,
        include_judge=True,
    )

    assert parsed["score"] == 0.8
    assert parsed["passed"] is True
    assert malformed["error"]
    assert deterministic_failed < 1.0
    assert deterministic_passed == 0.95


@pytest.mark.unit
def test_write_reward_keeps_harbor_rewards_numeric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime()
    reward_path = tmp_path / "reward.json"
    details_path = tmp_path / "clawbench_details.json"
    monkeypatch.setattr(runtime, "REWARD_PATH", reward_path)
    monkeypatch.setattr(runtime, "DETAILS_PATH", details_path)

    runtime.write_reward(
        {
            "reward": 0.75,
            "clawbench.run_score": 0.75,
            "clawbench.delivery_outcome": "pass",
            "completion_result": {"score": 1.0},
        }
    )

    reward_payload = runtime.json.loads(reward_path.read_text(encoding="utf-8"))
    details_payload = runtime.json.loads(details_path.read_text(encoding="utf-8"))

    assert reward_payload == {
        "reward": 0.75,
        "clawbench.run_score": 0.75,
    }
    assert details_payload["clawbench.delivery_outcome"] == "pass"
    assert details_payload["completion_result"] == {"score": 1.0}


@pytest.mark.unit
def test_openai_compatible_judge_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"score\\": 1.0, '
                b'\\"confidence\\": 0.8, \\"reason\\": \\"ok\\", '
                b'\\"rubric_hits\\": [], \\"rubric_misses\\": []}"}}]}'
            )

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = runtime.json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "custom-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("JUDGE_API_FORMAT", "openai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setattr(runtime.urllib.request, "urlopen", fake_urlopen)

    text = runtime.call_judge_provider("score this", "glm-5.1")

    assert '"score": 1.0' in text
    assert captured["url"] == "https://judge.example/v1/chat/completions"
    assert captured["timeout"] == 120
    assert captured["headers"]["Authorization"] == "Bearer custom-key"
    assert captured["payload"]["model"] == "glm-5.1"
    assert captured["payload"]["messages"][0]["content"] == "score this"
