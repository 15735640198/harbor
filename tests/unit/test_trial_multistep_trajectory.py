import json
from pathlib import Path
from types import SimpleNamespace

from harbor.agents.installed.openclaw import OpenClaw
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Agent, FinalMetrics, Step, Trajectory
from harbor.models.trial.paths import TrialPaths
from harbor.models.trial.result import StepResult
from harbor.trial.trial import Trial


def _write_step_trajectory(
    path: Path,
    *,
    session_id: str,
    message: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    trajectory = Trajectory(
        schema_version="ATIF-v1.7",
        session_id=session_id,
        trajectory_id=session_id,
        agent=Agent(name="openclaw", version="1.0"),
        steps=[
            Step(
                step_id=1,
                source="agent",
                message=message,
                extra={"openclaw_role": "assistant"},
            )
        ],
        final_metrics=FinalMetrics(
            total_prompt_tokens=prompt_tokens,
            total_completion_tokens=completion_tokens,
            total_steps=1,
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(trajectory.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_trial(tmp_path: Path) -> Trial:
    trial = object.__new__(Trial)
    trial.config = SimpleNamespace(trial_name="trial-1")
    trial._trial_paths = TrialPaths(trial_dir=tmp_path / "trial")
    trial._trial_paths.mkdir()
    trial._logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    trial._result = SimpleNamespace(step_results=[])
    return trial


def test_write_multi_step_trajectory_aggregates_step_trajectories(
    tmp_path: Path,
) -> None:
    trial = _make_trial(tmp_path)
    trial.result.step_results = [
        StepResult(step_name="first"),
        StepResult(step_name="second"),
    ]
    _write_step_trajectory(
        trial._trial_paths.step_agent_dir("first") / "trajectory.json",
        session_id="s1",
        message="first step",
        prompt_tokens=10,
        completion_tokens=2,
    )
    _write_step_trajectory(
        trial._trial_paths.step_agent_dir("second") / "trajectory.json",
        session_id="s2",
        message="second step",
        prompt_tokens=20,
        completion_tokens=3,
    )

    trial._write_multi_step_trajectory()

    aggregate = Trajectory.model_validate_json(
        (trial._trial_paths.agent_dir / "trajectory.json").read_text()
    )
    assert aggregate.session_id == "trial-1"
    assert aggregate.trajectory_id == "trial-1:multi-step"
    assert [step.step_id for step in aggregate.steps] == [1, 2]
    assert [step.message for step in aggregate.steps] == ["first step", "second step"]
    assert aggregate.steps[0].extra == {
        "openclaw_role": "assistant",
        "harbor_step_name": "first",
        "harbor_original_step_id": 1,
    }
    assert aggregate.final_metrics is not None
    assert aggregate.final_metrics.total_prompt_tokens == 30
    assert aggregate.final_metrics.total_completion_tokens == 5
    assert aggregate.final_metrics.total_steps == 2
    assert aggregate.extra is not None
    assert aggregate.extra["harbor_multi_step"] is True


def test_write_multi_step_trajectory_records_missing_step_trajectories(
    tmp_path: Path,
) -> None:
    trial = _make_trial(tmp_path)
    trial.result.step_results = [
        StepResult(step_name="first"),
        StepResult(step_name="timed-out"),
    ]
    _write_step_trajectory(
        trial._trial_paths.step_agent_dir("first") / "trajectory.json",
        session_id="s1",
        message="first step",
        prompt_tokens=10,
        completion_tokens=2,
    )

    trial._write_multi_step_trajectory()

    aggregate = Trajectory.model_validate_json(
        (trial._trial_paths.agent_dir / "trajectory.json").read_text()
    )
    assert [step.message for step in aggregate.steps] == ["first step"]
    assert aggregate.extra is not None
    assert aggregate.extra["skipped_step_trajectories"] == [
        {"step_name": "timed-out", "reason": "missing trajectory.json"}
    ]


def test_write_multi_step_verifier_transcript_includes_prior_and_current_steps(
    tmp_path: Path,
) -> None:
    trial = _make_trial(tmp_path)
    trial.result.step_results = [
        StepResult(step_name="first"),
        StepResult(step_name="second"),
    ]
    _write_step_trajectory(
        trial._trial_paths.step_agent_dir("first") / "trajectory.json",
        session_id="s1",
        message="first step",
        prompt_tokens=10,
        completion_tokens=2,
    )
    _write_step_trajectory(
        trial._trial_paths.agent_dir / "trajectory.json",
        session_id="s2",
        message="second step",
        prompt_tokens=20,
        completion_tokens=3,
    )

    trial._write_multi_step_verifier_transcript()

    payload = json.loads(
        (trial._trial_paths.agent_dir / "000-multi-step-transcript.json").read_text()
    )
    assert payload["harbor_multi_step"] is True
    assert [message["message"]["content"] for message in payload["messages"]] == [
        "first step",
        "second step",
    ]
    assert [message["message"]["role"] for message in payload["messages"]] == [
        "assistant",
        "assistant",
    ]
    assert payload["step_trajectories"] == [
        {
            "step_name": "first",
            "path": "steps/first/agent/trajectory.json",
            "steps": 1,
        },
        {"step_name": "second", "path": "agent/trajectory.json", "steps": 1},
    ]


def test_reset_agent_post_run_state_for_step_resets_reused_installed_agent(
    tmp_path: Path,
) -> None:
    trial = _make_trial(tmp_path)

    class AgentWithPostRunGuard:
        _post_run_completed = True

        def populate_context_post_run(self, context: AgentContext) -> None:
            pass

    trial._agent = AgentWithPostRunGuard()

    trial._reset_agent_post_run_state_for_step()

    assert trial._agent._post_run_completed is False


def test_maybe_populate_agent_context_runs_when_context_nonempty_but_no_trajectory(
    tmp_path: Path,
) -> None:
    trial = _make_trial(tmp_path)
    agent = OpenClaw(logs_dir=trial._trial_paths.agent_dir)
    calls = []

    def populate(context: AgentContext) -> None:
        calls.append(context)

    agent.populate_context_post_run = populate
    trial._agent = agent
    context = AgentContext(n_input_tokens=1)

    trial._maybe_populate_agent_context(context)

    assert calls == [context]


def test_maybe_populate_agent_context_skips_when_context_and_trajectory_exist(
    tmp_path: Path,
) -> None:
    trial = _make_trial(tmp_path)
    agent = OpenClaw(logs_dir=trial._trial_paths.agent_dir)
    (trial._trial_paths.agent_dir / "trajectory.json").write_text("{}")
    calls = []

    def populate(context: AgentContext) -> None:
        calls.append(context)

    agent.populate_context_post_run = populate
    trial._agent = agent

    trial._maybe_populate_agent_context(AgentContext(n_input_tokens=1))

    assert calls == []
