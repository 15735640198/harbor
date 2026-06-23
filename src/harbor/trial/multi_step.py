from typing import Any, override
import json
import shlex
from pathlib import Path

from harbor.environments.base import HealthcheckError
from harbor.models.task.config import MultiStepRewardStrategy, StepConfig
from harbor.models.task.task import Task
from harbor.models.trajectories import Trajectory
from harbor.models.trajectories.final_metrics import FinalMetrics
from harbor.models.task.verifier_mode import (
    VerifierEnvironmentMode,
    resolve_step_verifier_mode,
)
from harbor.models.trial.config import TrialConfig
from harbor.models.trial.result import ExceptionInfo, StepResult, TimingInfo
from harbor.models.verifier.result import VerifierResult
from harbor.trial.hooks import TrialEvent
from harbor.trial.trial import Trial


class MultiStepTrial(Trial):
    """A trial made of sequential named steps."""

    def __init__(
        self,
        config: TrialConfig,
        *,
        _task: Task | None = None,
    ):
        if _task is not None and not _task.has_steps:
            raise ValueError("MultiStepTrial requires a task with [[steps]].")
        super().__init__(config, _task=_task)

    @override
    async def _run(self) -> None:
        self.result.step_results = []

        steps = self.task.config.steps or []
        for index, step in enumerate(steps, start=1):
            step_result = StepResult(step_name=step.name)
            self.result.step_results.append(step_result)

            await self._run_step(
                step,
                step_result,
                index=index,
                total=len(steps),
            )

            if self._should_stop_after_step(step, step_result):
                break

        self.result.verifier_result = self._select_multi_step_reward()
        self._write_multi_step_trajectory()

        await self._stop_agent_environment()

        self.paths.cleanup_empty_mount_dirs()

    @override
    async def _recover_outputs(self) -> None:
        await self._sync_agent_output(self.result)
        await self._stop_agent_environment()

    async def _run_step(
        self,
        step: StepConfig,
        step_result: StepResult,
        *,
        index: int,
        total: int,
    ) -> None:
        self.logger.debug(f"Starting step {index}/{total}: {step.name}")

        self._create_step_dirs(step)
        self._reset_agent_post_run_state_for_step()

        await self._prepare_step(step, step_result)

        if step_result.exception_info is not None:
            self._archive_step_outputs(step)
            return

        await self._run_step_agent(step, step_result)
        self._write_multi_step_verifier_transcript()
        await self._upload_agent_logs()

        mode = resolve_step_verifier_mode(self.task.config, step)
        # The main service may only be stopped before sidecar collection when
        # the agent env has no further use: separate verifier on the last step.
        artifacts_dir = await self._collect_step_artifacts(
            step,
            stop_main_before_sidecars=(
                mode == VerifierEnvironmentMode.SEPARATE and index == total
            ),
        )

        if mode == VerifierEnvironmentMode.SEPARATE and index == total:
            await self._stop_agent_environment()

        await self._run_step_verifier(
            step,
            step_result,
            artifacts_dir=artifacts_dir,
            mode=mode,
        )

        self._archive_step_outputs(step)

    async def _prepare_step(self, step: StepConfig, step_result: StepResult) -> None:
        self._are_agent_logs_downloaded = False
        await self._reset_agent_logs_for_step()

        with self.agent_environment.with_default_user(self._step_agent_user(step)):
            workdir = await self._upload_step_workdir(step)
            await self._run_step_setup(step, step_result, workdir)
            await self._run_step_healthcheck(step, step_result)

    async def _run_step_agent(
        self,
        step: StepConfig,
        step_result: StepResult,
    ) -> None:
        try:
            await self._run_agent_phase(
                target=step_result,
                instruction=self.task.step_instruction(step.name),
                timeout_sec=self._step_agent_timeout_sec(step),
                user=self._step_agent_user(step),
                step_cfg=step,
            )
        except Exception as exc:
            step_result.exception_info = ExceptionInfo.from_exception(exc)
        finally:
            await self._sync_agent_output(step_result)

    async def _run_step_verifier(
        self,
        step: StepConfig,
        step_result: StepResult,
        *,
        artifacts_dir: Path,
        mode: VerifierEnvironmentMode,
    ) -> None:
        if self.config.verifier.disable:
            return

        step_result.verifier = TimingInfo(started_at=self._now())
        user = self._step_verifier_user(step)

        try:
            await self._emit(TrialEvent.VERIFICATION_START)

            if mode == VerifierEnvironmentMode.SEPARATE:
                step_result.verifier_result = await self._run_separate_verifier(
                    key=step.name,
                    timeout_sec=self._step_verifier_timeout_sec(step),
                    artifacts_dir=artifacts_dir,
                    artifacts=step.artifacts,
                    step_cfg=step,
                    user=user,
                    env=step.verifier.env or None,
                )
            else:
                await self._reset_shared_step_verifier_dirs()
                step_result.verifier_result = await self._run_shared_verifier(
                    timeout_sec=self._step_verifier_timeout_sec(step),
                    user=user,
                    env=step.verifier.env or None,
                    step_name=step.name,
                    step_cfg=step,
                )
        except Exception as exc:
            if step_result.exception_info is None:
                step_result.exception_info = ExceptionInfo.from_exception(exc)
        finally:
            step_result.verifier.finished_at = self._now()

    def _should_stop_after_step(
        self,
        step: StepConfig,
        step_result: StepResult,
    ) -> bool:
        if step_result.exception_info and not step_result.verifier_result:
            self.logger.warning(f"Step '{step.name}' failed, aborting remaining steps")
            return True

        if step.min_reward is None:
            return False

        if self.config.verifier.disable:
            self.logger.debug(
                f"Step '{step.name}' has min_reward={step.min_reward} "
                "but verification is globally disabled; skipping threshold check"
            )
            return False

        rewards = (
            step_result.verifier_result.rewards if step_result.verifier_result else None
        )

        failure = self._min_reward_failure(rewards, step.min_reward)

        if failure is None:
            return False

        self.logger.debug(f"Step '{step.name}' {failure}, aborting remaining steps")

        return True

    def _select_multi_step_reward(self) -> VerifierResult | None:
        if self.task.config.multi_step_reward_strategy is MultiStepRewardStrategy.FINAL:
            if not self.result.step_results:
                return None
            return self.result.step_results[-1].verifier_result
        return self._aggregate_step_rewards()

    def _aggregate_step_rewards(self) -> VerifierResult | None:
        """Compute per-key means across steps with verifier results.

        Missing keys count as 0. Steps without a verifier result are excluded from
        the denominator.
        """
        if not self.result.step_results:
            return None

        valid_rewards = [
            result.verifier_result.rewards or {}
            for result in self.result.step_results
            if result.verifier_result is not None
        ]
        if not valid_rewards:
            return None

        all_keys = {key for rewards in valid_rewards for key in rewards}
        if not all_keys:
            return None

        count = len(valid_rewards)
        return VerifierResult(
            rewards={
                key: sum(rewards.get(key, 0) for rewards in valid_rewards) / count
                for key in all_keys
            }
        )

    @staticmethod
    def _min_reward_failure(
        rewards: dict[str, float | int] | None,
        min_reward: float | dict[str, float],
    ) -> str | None:
        """Return a human-readable min_reward failure, or None when it passes."""
        thresholds = (
            {"reward": min_reward}
            if isinstance(min_reward, (int, float))
            else min_reward
        )
        for key, threshold in thresholds.items():
            actual = rewards.get(key, float("-inf")) if rewards else float("-inf")
            if actual < threshold:
                return f"{key}={actual} below min_reward {threshold}"
        return None

    def _create_step_dirs(self, step: StepConfig) -> None:
        self.paths.step_agent_dir(step.name).mkdir(parents=True, exist_ok=True)
        self.paths.step_verifier_dir(step.name).mkdir(parents=True, exist_ok=True)

    def _reset_agent_post_run_state_for_step(self) -> None:
        """Allow installed agents to parse logs independently for each step."""
        agent = getattr(self, "agent", None)
        if agent is not None and hasattr(agent, "_post_run_completed"):
            setattr(agent, "_post_run_completed", False)

    def _write_multi_step_trajectory(self) -> None:
        """Write a trial-level ATIF trajectory aggregated from per-step trajectories."""
        if not self.result.step_results:
            return

        step_trajectories: list[tuple[str, Trajectory]] = []
        skipped: list[dict[str, str]] = []
        for step_result in self.result.step_results:
            path = self.paths.step_agent_dir(step_result.step_name) / "trajectory.json"
            if not path.exists():
                skipped.append(
                    {
                        "step_name": step_result.step_name,
                        "reason": "missing trajectory.json",
                    }
                )
                continue
            try:
                step_trajectories.append(
                    (
                        step_result.step_name,
                        Trajectory.model_validate_json(path.read_text()),
                    )
                )
            except Exception as exc:
                skipped.append(
                    {
                        "step_name": step_result.step_name,
                        "reason": f"invalid trajectory.json: {exc}",
                    }
                )

        if not step_trajectories:
            return

        merged_steps = []
        for step_name, trajectory in step_trajectories:
            for step in trajectory.steps:
                extra = dict(step.extra or {})
                extra.setdefault("harbor_step_name", step_name)
                extra.setdefault("harbor_original_step_id", step.step_id)
                merged_steps.append(
                    step.model_copy(
                        update={
                            "step_id": len(merged_steps) + 1,
                            "extra": extra,
                        }
                    )
                )

        final_metrics = self._aggregate_multi_step_final_metrics(
            [trajectory for _, trajectory in step_trajectories],
            total_steps=len(merged_steps),
        )
        extra: dict[str, Any] = {
            "harbor_multi_step": True,
            "source": "multi_step_aggregate",
            "step_trajectories": [
                {
                    "step_name": step_name,
                    "path": f"steps/{step_name}/agent/trajectory.json",
                    "steps": len(trajectory.steps),
                }
                for step_name, trajectory in step_trajectories
            ],
        }
        if skipped:
            extra["skipped_step_trajectories"] = skipped

        aggregate = Trajectory(
            schema_version="ATIF-v1.7",
            session_id=self.config.trial_name,
            trajectory_id=f"{self.config.trial_name}:multi-step",
            agent=step_trajectories[0][1].agent,
            steps=merged_steps,
            notes=(
                "Aggregated from per-step trajectories. Some step trajectories "
                "were missing or invalid; see extra.skipped_step_trajectories."
                if skipped
                else "Aggregated from per-step trajectories."
            ),
            final_metrics=final_metrics,
            extra=extra,
        )

        self.paths.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.agent_dir / "trajectory.json").write_text(
            json.dumps(aggregate.to_json_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_multi_step_verifier_transcript(self) -> None:
        """Write a verifier-friendly transcript for completed multi-step logs."""
        result = getattr(self, "_result", None)
        if result is None or not result.step_results:
            return

        messages: list[dict[str, Any]] = []
        sources: list[dict[str, str | int]] = []

        for step_result in result.step_results:
            step_name = step_result.step_name
            trajectory_path = self.paths.step_agent_dir(step_name) / "trajectory.json"
            if not trajectory_path.exists():
                current_step_index = len(result.step_results) - 1
                if step_result is result.step_results[current_step_index]:
                    trajectory_path = self.paths.agent_dir / "trajectory.json"
            if not trajectory_path.exists():
                continue

            try:
                trajectory = Trajectory.model_validate_json(trajectory_path.read_text())
            except Exception:
                continue

            sources.append(
                {
                    "step_name": step_name,
                    "path": trajectory_path.relative_to(
                        self.paths.trial_dir
                    ).as_posix(),
                    "steps": len(trajectory.steps),
                }
            )
            for step in trajectory.steps:
                role = "assistant" if step.source == "agent" else "user"
                step_payload = step.model_dump(mode="json", exclude_none=True)
                messages.append(
                    {
                        "type": "message",
                        "message": {
                            "role": role,
                            "content": step_payload["message"],
                        },
                        "harbor_step_name": step_name,
                        "harbor_original_step_id": step.step_id,
                        "source": step.source,
                    }
                )

        if not messages:
            return

        payload = {
            "messages": messages,
            "harbor_multi_step": True,
            "source": "multi_step_verifier_transcript",
            "step_trajectories": sources,
        }
        self.paths.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.agent_dir / "000-multi-step-transcript.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _aggregate_multi_step_final_metrics(
        self, trajectories: list[Trajectory], *, total_steps: int
    ) -> FinalMetrics | None:
        totals: dict[str, int | float | None] = {
            "total_prompt_tokens": None,
            "total_completion_tokens": None,
            "total_cached_tokens": None,
            "total_cost_usd": None,
        }

        for trajectory in trajectories:
            metrics = trajectory.final_metrics
            if metrics is None:
                continue
            for field in totals:
                value = getattr(metrics, field)
                if value is None:
                    continue
                totals[field] = (totals[field] or 0) + value

        if all(value is None for value in totals.values()):
            return FinalMetrics(total_steps=total_steps)

        return FinalMetrics(
            total_prompt_tokens=(
                int(totals["total_prompt_tokens"])
                if totals["total_prompt_tokens"] is not None
                else None
            ),
            total_completion_tokens=(
                int(totals["total_completion_tokens"])
                if totals["total_completion_tokens"] is not None
                else None
            ),
            total_cached_tokens=(
                int(totals["total_cached_tokens"])
                if totals["total_cached_tokens"] is not None
                else None
            ),
            total_cost_usd=(
                float(totals["total_cost_usd"])
                if totals["total_cost_usd"] is not None
                else None
            ),
            total_steps=total_steps,
        )

    async def _collect_step_artifacts(
        self,
        step: StepConfig,
        *,
        stop_main_before_sidecars: bool = False,
    ) -> Path:
        artifacts_dir = (
            self.paths.artifacts_dir
            if self.agent_environment.capabilities.mounted
            else self.paths.step_artifacts_dir(step.name)
        )
        await self._collect_artifacts_phased(
            artifacts_dir=artifacts_dir,
            step_cfg=step,
            step_artifacts=step.artifacts,
            stop_main_before_sidecars=stop_main_before_sidecars,
        )
        return artifacts_dir

    async def _reset_agent_logs_for_step(self) -> None:
        if self.agent_environment.capabilities.mounted:
            return

        await self.agent_environment.empty_dirs(
            [self.agent_env_paths.agent_dir],
            chmod=True,
        )

    async def _reset_shared_step_verifier_dirs(self) -> None:
        await self.agent_environment.empty_dirs(
            [self.agent_env_paths.verifier_dir],
            chmod=True,
        )
        await self.agent_environment.empty_dirs(
            [self.agent_env_paths.tests_dir], chmod=False
        )

    async def _upload_step_workdir(self, step: StepConfig) -> str:
        workdir_result = await self.agent_environment.exec("pwd")
        workdir = (workdir_result.stdout or "/").strip()
        step_workdir_dir = self.task.paths.steps_dir / step.name / "workdir"
        if step_workdir_dir.exists():
            await self.agent_environment.upload_dir(
                source_dir=step_workdir_dir,
                target_dir=workdir,
            )
        return workdir

    async def _run_step_setup(
        self,
        step: StepConfig,
        step_result: StepResult,
        workdir: str,
    ) -> None:
        setup_script = self.task.paths.steps_dir / step.name / "workdir" / "setup.sh"
        if not setup_script.exists():
            return

        script_path = f"{workdir.rstrip('/')}/setup.sh"
        try:
            result = await self.agent_environment.exec(
                f"bash {shlex.quote(script_path)}"
            )
            if result.return_code == 0:
                return

            raise RuntimeError(
                f"Step '{step.name}' setup.sh exited with code "
                f"{result.return_code}: {result.stderr}"
            )
        except Exception as exc:
            self.logger.warning(f"Step '{step.name}' setup.sh failed: {exc}")
            step_result.exception_info = ExceptionInfo.from_exception(exc)

    async def _run_step_healthcheck(
        self,
        step: StepConfig,
        step_result: StepResult,
    ) -> None:
        if step.healthcheck is None or step_result.exception_info is not None:
            return

        try:
            await self.agent_environment.run_healthcheck(step.healthcheck)
        except HealthcheckError as exc:
            self.logger.warning(f"Step '{step.name}' healthcheck failed: {exc}")
            step_result.exception_info = ExceptionInfo.from_exception(exc)

    def _archive_step_outputs(self, step: StepConfig) -> None:
        self._artifact_handler.move_dir_contents(
            self.paths.verifier_dir, self.paths.step_verifier_dir(step.name)
        )
        self._artifact_handler.move_dir_contents(
            self.paths.agent_dir, self.paths.step_agent_dir(step.name)
        )
        # The convention publish dir is a live bind-mount source; moving the
        # directory itself would detach the container's /logs/artifacts from
        # the trial dir for subsequent steps. Move contents only along that
        # chain, and everything else wholesale.
        self._artifact_handler.move_dir_contents_preserving(
            self.paths.artifacts_dir,
            self.paths.step_artifacts_dir(step.name),
            preserve_dirs=[self._main_artifacts_mount_dir],
        )

    def _step_agent_timeout_sec(self, step: StepConfig) -> float | None:
        default_timeout_sec = (
            step.agent.timeout_sec
            if step.agent.timeout_sec is not None
            else self.task.config.agent.timeout_sec
        )
        base_timeout_sec = self.config.agent.override_timeout_sec or default_timeout_sec
        if base_timeout_sec is None:
            return None

        return self._resolve_timeout_sec(
            base_sec=base_timeout_sec,
            max_sec=self.config.agent.max_timeout_sec,
            multiplier=self.config.agent_timeout_multiplier,
        )

    def _step_verifier_timeout_sec(self, step: StepConfig) -> float | None:
        default_timeout_sec = (
            step.verifier.timeout_sec
            if step.verifier.timeout_sec is not None
            else self.task.config.verifier.timeout_sec
        )
        return self._resolve_timeout_sec(
            base_sec=self.config.verifier.override_timeout_sec or default_timeout_sec,
            max_sec=self.config.verifier.max_timeout_sec,
            multiplier=self.config.verifier_timeout_multiplier,
        )

    def _step_agent_user(self, step: StepConfig) -> str | int | None:
        if step.agent.user is not None:
            return step.agent.user
        return self.task.config.agent.user

    def _step_verifier_user(self, step: StepConfig) -> str | int | None:
        if step.verifier.user is not None:
            return step.verifier.user
        return self.task.config.verifier.user
