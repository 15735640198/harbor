#!/usr/bin/env python3
"""Generate FAILURE_ATTRIBUTION.md for Harbor trial folders using Claude Code CLI + harbor-failure-attribution skill.

The script invokes ``claude -p`` (headless mode). Claude Code reads the skill
definition, runs the evidence collector, inspects evidence files, and writes
FAILURE_ATTRIBUTION.md — all autonomously. No external Python packages required.

Usage:
    # Single trial
    python generate_failure_attribution.py jobs/my-job/my-trial

    # Batch: process all trials in a job folder
    python generate_failure_attribution.py jobs/my-job --batch

    # With task source files
    python generate_failure_attribution.py jobs/my-job/my-trial --task-source examples/tasks/my-task

    # Preview the claude command without running
    python generate_failure_attribution.py jobs/my-job/my-trial --dry-run

    # Skip permission prompts (for fully automated runs)
    python generate_failure_attribution.py jobs/my-job/my-trial --claude-args "--dangerously-skip-permissions"

    # Use a different model
    python generate_failure_attribution.py jobs/my-job/my-trial --model opus
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# --- Paths ---
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
COLLECT_SCRIPT = SKILL_DIR / "scripts" / "collect_job_context.py"
PROJECT_ROOT = SKILL_DIR.parent.parent

# --- Defaults ---
DEFAULT_MODEL = "sonnet"
DEFAULT_MAX_TURNS = 30
DEFAULT_TOOLS = "Bash,Read,Write,Edit,Glob,Grep"
DEFAULT_TIMEOUT = 300
DEFAULT_BATCH_DELAY = 5.0


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_prompt(trial_folder: Path, task_source: Path | None) -> str:
    """Build the prompt that tells Claude Code what to do."""
    lines = [
        "Use the harbor-failure-attribution skill to generate a FAILURE_ATTRIBUTION.md report "
        "for this Harbor OpenClaw trial folder.",
        "",
        f"Trial folder: {trial_folder}",
        "",
        "Follow these steps:",
        f"1. Read the skill definition at: {SKILL_MD}",
        f"2. Run the evidence collector: python {COLLECT_SCRIPT} \"{trial_folder}\"",
        "3. Read the key files called out by the collector:",
        "   - result.json (full scoring and exception details)",
        "   - trial.log (runtime errors, setup issues)",
        "   - At least one agent trace source (trajectory.json, openclaw-output.txt, tar_blocks, etc.)",
        f"4. Write FAILURE_ATTRIBUTION.md in {trial_folder} following the exact report structure "
        "and writing rules defined in the skill.",
    ]
    if task_source:
        if task_source.is_dir():
            lines.append(
                f"5. Task source files are available at: {task_source}"
            )
            lines.append(
                "   Inspect instruction.md, verifier scripts, and relevant task fixtures "
                "as described in the skill."
            )
        else:
            lines.append(f"5. Task source path provided but invalid: {task_source}")
    lines.append("")
    lines.append("Do not ask for confirmation at any step. Complete the task and write the file.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude CLI command construction
# ---------------------------------------------------------------------------

def build_claude_command(
    prompt: str,
    trial_folder: Path,
    args: argparse.Namespace,
) -> list[str]:
    """Build the ``claude`` CLI command vector."""
    cmd: list[str] = ["claude", "-p", prompt]
    cmd.extend(["--allowedTools", args.tools])
    cmd.extend(["--model", args.model])
    cmd.extend(["--max-turns", str(args.max_turns)])

    # Allow Claude to access the trial folder if it lives outside the project root
    _add_dir_if_outside(cmd, trial_folder)
    if args.task_source and args.task_source.is_dir():
        _add_dir_if_outside(cmd, args.task_source)

    # Extra user-supplied flags (e.g. --dangerously-skip-permissions)
    if args.claude_args:
        cmd.extend(args.claude_args.split())

    return cmd


def _add_dir_if_outside(cmd: list[str], target: Path) -> None:
    """Append ``--add-dir <path>`` when *target* is outside PROJECT_ROOT."""
    try:
        target.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        cmd.extend(["--add-dir", str(target.resolve())])


# ---------------------------------------------------------------------------
# Trial processing
# ---------------------------------------------------------------------------

def process_trial(trial_folder: Path, args: argparse.Namespace) -> bool:
    """Process a single trial folder. Returns True on success."""
    report_path = trial_folder / "FAILURE_ATTRIBUTION.md"
    if report_path.exists() and not args.force:
        print(f"  skip: {report_path} exists (use --force to overwrite)", file=sys.stderr)
        return False

    prompt = build_prompt(trial_folder, args.task_source)
    cmd = build_claude_command(prompt, trial_folder, args)
    cwd = str(args.cwd.resolve()) if args.cwd else str(PROJECT_ROOT)

    if args.dry_run:
        print(f"  [dry-run] cwd: {cwd}", file=sys.stderr)
        print(f"  [dry-run] cmd: {' '.join(cmd[:4])} ... <prompt {len(prompt)} chars>", file=sys.stderr)
        return True

    if args.verbose:
        print(f"  running claude (cwd={cwd})...", file=sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=not args.verbose,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  error: claude timed out after {args.timeout}s", file=sys.stderr)
        return False

    if result.returncode != 0:
        print(f"  error: claude exited with code {result.returncode}", file=sys.stderr)
        if not args.verbose and result.stderr:
            print(f"  stderr: {result.stderr[:1000]}", file=sys.stderr)
        return False

    # Verify the report was actually written
    if report_path.exists():
        size = report_path.stat().st_size
        print(f"  written: {report_path} ({size} bytes)", file=sys.stderr)
        return True

    print(f"  error: FAILURE_ATTRIBUTION.md was not created in {trial_folder}", file=sys.stderr)
    if not args.verbose and result.stdout:
        print(f"  claude output (last 1000 chars): {result.stdout[-1000:]}", file=sys.stderr)
    return False


def find_trials(job_folder: Path) -> list[Path]:
    """Find all trial subdirectories that contain result.json."""
    trials = {result_json.parent for result_json in job_folder.rglob("result.json")}
    return sorted(trials)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate FAILURE_ATTRIBUTION.md for Harbor trial folders "
            "using Claude Code CLI + harbor-failure-attribution skill."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Single trial
  python generate_failure_attribution.py jobs/my-job/my-trial

  # Batch: process all trials in a job folder
  python generate_failure_attribution.py jobs/my-job --batch

  # With task source files
  python generate_failure_attribution.py jobs/my-job/my-trial --task-source examples/tasks/my-task

  # Preview the command without running
  python generate_failure_attribution.py jobs/my-job/my-trial --dry-run

  # Skip permission prompts (fully automated CI)
  python generate_failure_attribution.py jobs/my-job/my-trial --claude-args "--dangerously-skip-permissions"

  # Use a different model
  python generate_failure_attribution.py jobs/my-job/my-trial --model opus
""",
    )
    parser.add_argument("path", type=Path, help="Path to a trial folder (or job folder with --batch)")
    parser.add_argument("--batch", action="store_true", help="Process all trials found under a job folder")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model name or alias (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help=f"Max conversation turns (default: {DEFAULT_MAX_TURNS})")
    parser.add_argument("--tools", default=DEFAULT_TOOLS, help=f"Comma-separated allowed tools (default: {DEFAULT_TOOLS})")
    parser.add_argument("--task-source", type=Path, default=None, help="Path to task source directory (instruction.md, tests/)")
    parser.add_argument("--cwd", type=Path, default=None, help="Working directory for claude (default: project root)")
    parser.add_argument("--claude-args", default="", help="Extra flags for claude CLI (e.g. '--dangerously-skip-permissions')")
    parser.add_argument("--force", action="store_true", help="Overwrite existing FAILURE_ATTRIBUTION.md")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without running claude")
    parser.add_argument("--verbose", "-v", action="store_true", help="Stream claude output instead of capturing")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Timeout per trial in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--delay", type=float, default=DEFAULT_BATCH_DELAY, help=f"Delay between trials in batch mode, seconds (default: {DEFAULT_BATCH_DELAY})")
    args = parser.parse_args()

    # Prerequisites
    if not shutil.which("claude"):
        print("Error: 'claude' CLI not found in PATH.", file=sys.stderr)
        print("Install Claude Code: https://docs.anthropic.com/en/docs/claude-code", file=sys.stderr)
        sys.exit(1)
    if not SKILL_MD.exists():
        print(f"Error: SKILL.md not found at {SKILL_MD}", file=sys.stderr)
        sys.exit(1)
    if not COLLECT_SCRIPT.exists():
        print(f"Error: collect_job_context.py not found at {COLLECT_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    target = args.path.resolve()
    if not target.is_dir():
        print(f"Error: not a directory: {target}", file=sys.stderr)
        sys.exit(1)

    if args.batch:
        trials = find_trials(target)
        if not trials:
            print(f"Error: no trial folders (with result.json) found under {target}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(trials)} trial(s) under {target}", file=sys.stderr)
        success = 0
        skipped = 0
        failed = 0
        for i, trial in enumerate(trials):
            print(f"[{i + 1}/{len(trials)}] {trial}", file=sys.stderr)
            try:
                if process_trial(trial, args):
                    success += 1
                else:
                    skipped += 1
            except Exception as exc:
                print(f"  error: {exc}", file=sys.stderr)
                failed += 1
            if i < len(trials) - 1 and args.delay > 0:
                time.sleep(args.delay)
        print(
            f"\nDone: {success} generated, {skipped} skipped, {failed} failed",
            file=sys.stderr,
        )
    else:
        if not (target / "result.json").exists():
            print(
                f"Warning: {target} does not contain result.json. "
                "Are you sure this is a trial folder?",
                file=sys.stderr,
            )
        if not process_trial(target, args):
            sys.exit(1)


if __name__ == "__main__":
    main()
