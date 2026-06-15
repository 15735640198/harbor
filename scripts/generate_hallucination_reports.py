#!/usr/bin/env python3
"""Generate hallucination reports for Harbor job trajectories with Claude Code."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobTarget:
    job_dir: Path
    trajectory_path: Path
    processed_path: Path
    verifier_dir: Path
    step_name: str | None


def parse_args() -> argparse.Namespace:
    repo_root = get_repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Generate hallucination-result.json reports for one Harbor job folder "
            "or a folder containing Harbor jobs."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "Harbor job folder, folder of jobs, or an agent/trajectory.json file. "
            "The script searches for agent/trajectory.json files underneath it."
        ),
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=repo_root / "skills" / "audit-harbor-hallucinations",
        help="Path to the audit-harbor-hallucinations skill source directory.",
    )
    parser.add_argument(
        "--preprocess-script",
        type=Path,
        default=repo_root / "scripts" / "preprocess_atif_trajectory.py",
        help="Path to scripts/preprocess_atif_trajectory.py.",
    )
    parser.add_argument(
        "--claude-bin",
        default="claude",
        help="Claude Code executable to run.",
    )
    parser.add_argument(
        "--claude-arg",
        action="append",
        default=[],
        help=(
            "Extra argument to pass to Claude Code before --print. May be repeated, "
            "for example --claude-arg=--model=claude-opus-4-1."
        ),
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=0,
        help="Claude Code timeout in seconds. Use 0 for no timeout.",
    )
    parser.add_argument(
        "--output-name",
        default="hallucination-result.json",
        help="Filename to write under each matching verifier directory.",
    )
    parser.add_argument(
        "--max-result-chars",
        type=int,
        default=4000,
        help="Forwarded to scripts/preprocess_atif_trajectory.py.",
    )
    parser.add_argument(
        "--max-arguments-chars",
        type=int,
        default=2000,
        help="Forwarded to scripts/preprocess_atif_trajectory.py.",
    )
    parser.add_argument(
        "--max-message-chars",
        type=int,
        default=4000,
        help="Forwarded to scripts/preprocess_atif_trajectory.py.",
    )
    parser.add_argument(
        "--include-copied-context",
        action="store_true",
        help="Forwarded to scripts/preprocess_atif_trajectory.py.",
    )
    parser.add_argument(
        "--include-status-basis",
        action="store_true",
        help="Forwarded to scripts/preprocess_atif_trajectory.py.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip jobs where the destination hallucination report already exists.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many discovered trajectories.",
    )
    parser.add_argument(
        "--temp-root",
        type=Path,
        default=None,
        help="Directory in which temporary Claude workspaces are created.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep successful temporary Claude workspaces for debugging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovered jobs without preprocessing or launching Claude Code.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed job instead of continuing the batch.",
    )
    return parser.parse_args()


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_path(path: Path, repo_root: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (repo_root / expanded).resolve()


def discover_targets(input_path: Path) -> list[JobTarget]:
    if input_path.is_file():
        target = target_from_trajectory(input_path)
        return [target] if target is not None else []

    candidates = sorted(
        path
        for path in input_path.rglob("trajectory.json")
        if path.parent.name == "agent"
    )
    return dedupe_targets(candidates)


def target_from_trajectory(path: Path) -> JobTarget | None:
    if path.name != "trajectory.json" or path.parent.name != "agent":
        return None

    trajectory_path = path.resolve()
    agent_dir = trajectory_path.parent

    if agent_dir.parent.parent.name == "steps":
        step_dir = agent_dir.parent
        job_dir = step_dir.parent.parent
        verifier_dir = step_dir / "verifier"
        step_name = step_dir.name
    else:
        job_dir = agent_dir.parent
        verifier_dir = job_dir / "verifier"
        step_name = None

    return JobTarget(
        job_dir=job_dir,
        trajectory_path=trajectory_path,
        processed_path=trajectory_path.with_name("trajectory.processed.json"),
        verifier_dir=verifier_dir,
        step_name=step_name,
    )


def dedupe_targets(paths: list[Path]) -> list[JobTarget]:
    """Prefer step-local trajectories over root agent trajectories for each job."""
    root_targets_by_job: dict[Path, JobTarget] = {}
    step_targets_by_job: dict[Path, list[JobTarget]] = {}

    for path in paths:
        target = target_from_trajectory(path)
        if target is None:
            continue
        if target.step_name is None:
            root_targets_by_job[target.job_dir] = target
        else:
            step_targets_by_job.setdefault(target.job_dir, []).append(target)

    targets: list[JobTarget] = []
    for job_dir in sorted(set(root_targets_by_job) | set(step_targets_by_job)):
        step_targets = step_targets_by_job.get(job_dir)
        if step_targets:
            targets.extend(
                sorted(
                    step_targets,
                    key=lambda target: (
                        target.step_name or "",
                        target.trajectory_path.as_posix(),
                    ),
                )
            )
        elif root_target := root_targets_by_job.get(job_dir):
            targets.append(root_target)

    return targets


def run_preprocess(
    target: JobTarget,
    *,
    preprocess_script: Path,
    repo_root: Path,
    args: argparse.Namespace,
) -> None:
    command = [
        sys.executable,
        str(preprocess_script),
        str(target.trajectory_path),
        "--max-result-chars",
        str(args.max_result_chars),
        "--max-arguments-chars",
        str(args.max_arguments_chars),
        "--max-message-chars",
        str(args.max_message_chars),
    ]
    if args.include_copied_context:
        command.append("--include-copied-context")
    if args.include_status_basis:
        command.append("--include-status-basis")

    completed = subprocess.run(command, cwd=repo_root, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"preprocess failed for {target.trajectory_path} "
            f"(exit {completed.returncode})"
        )
    if not target.processed_path.exists():
        raise RuntimeError(f"preprocess did not create {target.processed_path}")


def create_temp_workspace(
    *,
    target: JobTarget,
    skill_dir: Path,
    temp_root: Path | None,
) -> tuple[Path, Path]:
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="harbor-hallucination-",
            dir=temp_root,
        )
    )
    shutil.copy2(target.processed_path, temp_dir / "trajectory.processed.json")

    skill_dest = temp_dir / ".claude" / "skills" / skill_dir.name
    skill_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        skill_dir,
        skill_dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return temp_dir, skill_dest


def build_claude_prompt() -> str:
    return textwrap.dedent(
        """
        /audit-harbor-hallucinations

        Analyze ./trajectory.processed.json in the current working directory.
        Read the processed trajectory as one complete chronological transcript.
        Write ./result.json using the skill's required JSON array schema.
        If no hallucinations are detected, write [].
        Validate the result with the validator in the copied skill directory.
        Do not write reports outside the current working directory.
        """
    ).strip()


def run_claude_code(
    *,
    temp_dir: Path,
    claude_bin: str,
    claude_args: list[str],
    timeout_sec: float,
) -> Path:
    log_path = temp_dir / "claude-code.txt"
    timeout = None if timeout_sec <= 0 else timeout_sec
    command = [
        claude_bin,
        "--verbose",
        "--output-format=stream-json",
        "--permission-mode=bypassPermissions",
        *claude_args,
        "--print",
        "--",
        build_claude_prompt(),
    ]
    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    env.setdefault("IS_SANDBOX", "1")

    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            completed = subprocess.run(
                command,
                cwd=temp_dir,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Claude Code executable not found: {claude_bin!r}. "
            "Install Claude Code or pass --claude-bin."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Claude Code timed out after {timeout_sec:g}s; log: {log_path}"
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"Claude Code failed with exit {completed.returncode}; log: {log_path}"
        )
    return log_path


def validate_temp_result(temp_dir: Path, skill_dest: Path) -> Path:
    result_path = temp_dir / "result.json"
    if not result_path.exists():
        raise RuntimeError(f"Claude Code did not create {result_path}")

    validator = skill_dest / "scripts" / "validate_result.py"
    if not validator.exists():
        raise RuntimeError(f"Skill validator not found: {validator}")

    completed = subprocess.run(
        [sys.executable, str(validator), str(result_path)],
        cwd=temp_dir,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"hallucination result validation failed: {result_path}")
    return result_path


def process_target(
    target: JobTarget,
    *,
    index: int,
    total: int,
    args: argparse.Namespace,
    repo_root: Path,
    preprocess_script: Path,
    skill_dir: Path,
    temp_root: Path | None,
) -> str:
    destination = target.verifier_dir / args.output_name
    if args.skip_existing and destination.exists():
        print(f"[{index}/{total}] skip existing: {destination}", flush=True)
        return "skipped"

    print(f"[{index}/{total}] preprocess: {target.trajectory_path}", flush=True)
    run_preprocess(
        target,
        preprocess_script=preprocess_script,
        repo_root=repo_root,
        args=args,
    )

    temp_dir: Path | None = None
    succeeded = False
    try:
        temp_dir, skill_dest = create_temp_workspace(
            target=target,
            skill_dir=skill_dir,
            temp_root=temp_root,
        )
        print(f"[{index}/{total}] claude: {target.job_dir}", flush=True)
        log_path = run_claude_code(
            temp_dir=temp_dir,
            claude_bin=args.claude_bin,
            claude_args=args.claude_arg,
            timeout_sec=args.timeout_sec,
        )
        result_path = validate_temp_result(temp_dir, skill_dest)

        target.verifier_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result_path, destination)
        succeeded = True
        if args.keep_temp:
            print(
                f"[{index}/{total}] wrote: {destination} (log: {log_path})", flush=True
            )
        else:
            print(f"[{index}/{total}] wrote: {destination}", flush=True)
        return "generated"
    finally:
        if temp_dir and temp_dir.exists():
            if args.keep_temp or not succeeded:
                print(f"[{index}/{total}] temp retained: {temp_dir}", flush=True)
            else:
                shutil.rmtree(temp_dir)


def validate_inputs(
    *,
    input_path: Path,
    preprocess_script: Path,
    skill_dir: Path,
    temp_root: Path | None,
) -> None:
    if not input_path.exists():
        raise SystemExit(f"Input path does not exist: {input_path}")
    if not preprocess_script.is_file():
        raise SystemExit(f"Preprocess script does not exist: {preprocess_script}")
    if not (skill_dir / "SKILL.md").is_file():
        raise SystemExit(f"Skill directory is missing SKILL.md: {skill_dir}")
    if temp_root is not None:
        temp_root.mkdir(parents=True, exist_ok=True)


def main() -> int:
    args = parse_args()
    repo_root = get_repo_root()
    input_path = resolve_path(args.input, repo_root)
    preprocess_script = resolve_path(args.preprocess_script, repo_root)
    skill_dir = resolve_path(args.skill_dir, repo_root)
    temp_root = (
        resolve_path(args.temp_root, repo_root) if args.temp_root is not None else None
    )

    validate_inputs(
        input_path=input_path,
        preprocess_script=preprocess_script,
        skill_dir=skill_dir,
        temp_root=temp_root,
    )

    targets = discover_targets(input_path)
    if args.limit is not None:
        targets = targets[: args.limit]

    if not targets:
        raise SystemExit(f"No agent/trajectory.json files found under: {input_path}")

    print(f"discovered {len(targets)} trajectory target(s)", flush=True)
    if args.dry_run:
        for target in targets:
            print(
                f"target: trajectory={target.trajectory_path} "
                f"verifier={target.verifier_dir}",
                flush=True,
            )
        return 0

    counts = {"generated": 0, "skipped": 0, "failed": 0}
    for index, target in enumerate(targets, start=1):
        try:
            status = process_target(
                target,
                index=index,
                total=len(targets),
                args=args,
                repo_root=repo_root,
                preprocess_script=preprocess_script,
                skill_dir=skill_dir,
                temp_root=temp_root,
            )
            counts[status] += 1
        except Exception as exc:
            counts["failed"] += 1
            print(
                f"[{index}/{len(targets)}] failed: {target.trajectory_path}",
                file=sys.stderr,
            )
            print(f"  {exc}", file=sys.stderr)
            if args.fail_fast:
                break

    print(
        "summary: "
        f"generated={counts['generated']} "
        f"skipped={counts['skipped']} "
        f"failed={counts['failed']}",
        flush=True,
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
