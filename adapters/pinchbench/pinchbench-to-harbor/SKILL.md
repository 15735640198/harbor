---
name: pinchbench-to-harbor
description: Convert Pinchbench benchmark task markdown files from related-projects/external-tasks/skill/tasks into Harbor task directories. Use when a user provides a Pinchbench task .md file or asks to build a Harbor adapter/task from Pinchbench, including automated, llm_judge, hybrid, workspace_files, and multi_session task specs.
---

# Pinchbench To Harbor

## Overview

Convert one Pinchbench task markdown file into a runnable Harbor task scaffold. Prefer the bundled converter for the mechanical transformation, then inspect the generated verifier when a task has unusual workspace files, transcript-dependent checks, or multi-session behavior. Generated Harbor task environments must copy `scripts/Dockerfile` from this skill into `environment/Dockerfile`.

## Quick Start

Run the converter from a Harbor checkout:

```bash
uv run adapters/pinchbench/pinchbench-to-harbor/scripts/convert_pinchbench_task.py \
  related-projects/external-tasks/skill/tasks/task_csv_stations_by_elevation.md \
  --output-dir /tmp/harbor-pinchbench/task-csv-stations-by-elevation
```

For tasks outside the standard submodule location, pass `--pinchbench-root` pointing at the Pinchbench repo root so `workspace_files.source` entries can be resolved from its `assets/` directory.

## Workflow

1. Parse the Pinchbench markdown frontmatter and body sections.
2. Generate Harbor `task.toml`, `instruction.md` or `steps/*/instruction.md`, `environment/Dockerfile`, and verifier files.
3. Copy this skill's `scripts/Dockerfile` to the generated task's `environment/Dockerfile`.
4. Copy `workspace_files` into `environment/workspace/`; the Dockerfile copies that tree into `/app`.
5. For `automated` tasks, run the embedded Pinchbench `grade(transcript, workspace_path)` function directly in the verifier and write `/logs/verifier/reward.json`.
6. For `llm_judge` tasks, generate a Harbor-style `uv run /tests/llm_judge.py` verifier using a prompt-only JSON response contract. Do not use provider-specific structured-output request fields such as Anthropic `output_config`.
7. For `hybrid` tasks, run deterministic automated scoring first, run the LLM judge second, then combine scores with Pinchbench `grading_weights` or a 0.5/0.5 default.

## Review Points

- Keep automated checks deterministic. Do not call an LLM to execute or reinterpret the `## Automated Checks` Python code.
- Inspect generated verifier scripts when automated checks depend on transcript tool calls. The converter provides best-effort transcript loading from `/logs/agent`, but workspace-state checks are more reliable across agents.
- For LLM judge tasks, keep judge API keys in `[verifier.env]` and never expose rubric-only answer material in `/app`.
- For LLM judge requests, tell the model the required JSON shape in the prompt and parse/coerce the returned text; do not rely on model/provider response-format parameters.
- Do not synthesize the Harbor environment Dockerfile inline; use `scripts/Dockerfile` from this skill as the environment template.
- For `workspace_files.source`, copy from Pinchbench `assets/` into Harbor `environment/workspace/`; tests remain hidden in `tests/`.
- For multi-session Pinchbench tasks, the converter creates Harbor steps and uses `multi_step_reward_strategy = "final"`. Non-final step verifiers write `1.0`; the final step runs the real verifier.
- When using the adapter, prefer its `claude-code` harness: it stages this skill into Claude Code's skills directory, asks Claude Code to use `$pinchbench-to-harbor`, and validates the generated Harbor task. Use the adapter's `direct` harness only for deterministic local smoke tests.

## References

Read `references/pinchbench_harbor_mapping.md` when you need details about the Pinchbench markdown structure, Harbor file mapping, generated verifier behavior, or manual cleanup for edge cases.
