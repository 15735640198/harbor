#!/usr/bin/env python3
"""Collect a compact evidence summary for one Harbor OpenClaw trial folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(errors="replace"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        return {"_error": f"JSON parse error: {exc}"}


def shorten(text: Any, limit: int) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\r", "")
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + f"\n... [truncated {len(value) - limit} chars]"


def nested_get(data: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def print_kv(label: str, value: Any) -> None:
    if value not in (None, "", [], {}):
        print(f"- {label}: `{value}`")


def summarize_result(job: Path, max_chars: int) -> None:
    result = load_json(job / "result.json")
    config = load_json(job / "config.json")

    print("## Result")
    if not isinstance(result, dict):
        print("- result.json: missing or unreadable")
        return

    rewards = nested_get(result, "verifier_result", "rewards") or {}
    exception = result.get("exception_info")
    agent_info = result.get("agent_info") or {}
    model_info = agent_info.get("model_info") or {}

    print_kv("trial_name", result.get("trial_name") or job.name)
    print_kv("task_name", result.get("task_name"))
    print_kv("source", result.get("source"))
    print_kv(
        "task_path",
        nested_get(config, "task", "path") or nested_get(result, "task_id", "path"),
    )
    print_kv("agent", agent_info.get("name"))
    print_kv("agent_version", agent_info.get("version"))
    print_kv(
        "model",
        "/".join(
            str(x) for x in (model_info.get("provider"), model_info.get("name")) if x
        ),
    )
    print_kv("started_at", result.get("started_at"))
    print_kv("finished_at", result.get("finished_at"))
    print_kv("reward", rewards.get("reward") if isinstance(rewards, dict) else None)

    if isinstance(rewards, dict) and rewards:
        print("\n### Rewards and sub-scores")
        for key in sorted(rewards):
            print(f"- `{key}`: `{rewards[key]}`")
    else:
        print("\n### Rewards and sub-scores\n- No verifier rewards recorded.")

    if exception:
        print("\n### Exception")
        if isinstance(exception, dict):
            print_kv(
                "exception_type",
                exception.get("exception_type") or exception.get("type"),
            )
            print_kv(
                "exception_message",
                exception.get("exception_message") or exception.get("message"),
            )
            print_kv("occurred_at", exception.get("occurred_at"))
            traceback = exception.get("exception_traceback") or exception.get(
                "traceback"
            )
            if traceback:
                print("\n```text")
                print(shorten(traceback, max_chars))
                print("```")
        else:
            print(f"- {shorten(exception, max_chars)}")

    step_results = result.get("step_results")
    if isinstance(step_results, list):
        print("\n### Step results")
        for step in step_results:
            if not isinstance(step, dict):
                continue
            step_rewards = nested_get(step, "verifier_result", "rewards") or {}
            step_exception = step.get("exception_info")
            summary = []
            if isinstance(step_rewards, dict) and "reward" in step_rewards:
                summary.append(f"reward={step_rewards['reward']}")
            if step_exception:
                if isinstance(step_exception, dict):
                    summary.append(
                        "exception="
                        + str(
                            step_exception.get("exception_type")
                            or step_exception.get("type")
                            or "yes"
                        )
                    )
                else:
                    summary.append("exception=yes")
            print(
                f"- `{step.get('step_name')}`: {', '.join(summary) or 'no reward/exception summary'}"
            )


def summarize_files(job: Path, max_chars: int) -> None:
    print("\n## Evidence files")
    interesting = [
        "result.json",
        "config.json",
        "trial.log",
        "exception.txt",
        "verifier/reward.json",
        "verifier/test-stdout.txt",
        "agent/trajectory.json",
        "agent/openclaw-output.txt",
        "agent/openclaw-session.jsonl",
        "agent/tar_blocks/action_actions.txt",
        "agent/tar_blocks/results_actions.txt",
        "agent/tar_blocks/results_thoughts.txt",
    ]
    for rel in interesting:
        path = job / rel
        if path.exists():
            print(f"- present: `{rel}` ({path.stat().st_size} bytes)")
        else:
            print(f"- missing: `{rel}`")

    prior = [
        p
        for p in job.glob("*.md")
        if p.name != "FAILURE_ATTRIBUTION.md" and "attribution" in p.name.lower()
    ]
    if prior:
        print("\n### Prior attribution notes")
        for path in sorted(prior):
            print(f"- `{path.name}` ({path.stat().st_size} bytes)")

    for rel in ("verifier/test-stdout.txt", "exception.txt"):
        path = job / rel
        if path.exists():
            print(f"\n### Preview: {rel}")
            print("```text")
            print(shorten(path.read_text(errors="replace"), max_chars))
            print("```")


def summarize_agent(job: Path, max_chars: int) -> None:
    print("\n## Agent trace")
    trajectory = load_json(job / "agent" / "trajectory.json")
    if isinstance(trajectory, dict):
        steps = trajectory.get("steps")
        print_kv("schema_version", trajectory.get("schema_version"))
        print_kv("session_id", trajectory.get("session_id"))
        print_kv(
            "total_steps",
            nested_get(trajectory, "final_metrics", "total_steps")
            or (len(steps) if isinstance(steps, list) else None),
        )
        print_kv(
            "prompt_tokens",
            nested_get(trajectory, "final_metrics", "total_prompt_tokens"),
        )
        print_kv(
            "completion_tokens",
            nested_get(trajectory, "final_metrics", "total_completion_tokens"),
        )
        print_kv(
            "cached_tokens",
            nested_get(trajectory, "final_metrics", "total_cached_tokens"),
        )
        if isinstance(steps, list):
            first_user = next(
                (s for s in steps if isinstance(s, dict) and s.get("source") == "user"),
                None,
            )
            if first_user:
                print("\n### First user instruction")
                print("```text")
                print(shorten(first_user.get("message"), max_chars))
                print("```")

            print("\n### Tool calls and observations")
            count = 0
            for step in steps:
                if not isinstance(step, dict):
                    continue
                tool_calls = step.get("tool_calls")
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        args = call.get("arguments")
                        print(
                            f"- step {step.get('step_id')}: `{call.get('function_name')}` {shorten(args, 500)}"
                        )
                        count += 1
                message = step.get("message")
                extra = step.get("extra") if isinstance(step.get("extra"), dict) else {}
                if message and (
                    extra.get("isError") or extra.get("exec_exit_code") not in (None, 0)
                ):
                    print(
                        f"- step {step.get('step_id')} observation/error: {shorten(message, 500)}"
                    )
                    count += 1
            if count == 0:
                print("- No compact tool/error summary found in trajectory.")
    else:
        print("- agent/trajectory.json missing or unreadable")

    for rel in (
        "agent/tar_blocks/action_actions.txt",
        "agent/tar_blocks/results_actions.txt",
        "agent/openclaw-output.txt",
    ):
        path = job / rel
        if path.exists():
            print(f"\n### Preview: {rel}")
            print("```text")
            print(shorten(path.read_text(errors="replace"), max_chars))
            print("```")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_folder", type=Path)
    parser.add_argument("--max-chars", type=int, default=2500)
    args = parser.parse_args()

    job = args.job_folder.expanduser().resolve()
    print(f"# Harbor job context: {job}")
    if not job.exists() or not job.is_dir():
        raise SystemExit(f"Not a directory: {job}")
    if not (job / "result.json").exists():
        print(
            "\nWarning: result.json is missing. Make sure this is a single Harbor trial folder."
        )

    summarize_result(job, args.max_chars)
    summarize_files(job, args.max_chars)
    summarize_agent(job, args.max_chars)


if __name__ == "__main__":
    main()
