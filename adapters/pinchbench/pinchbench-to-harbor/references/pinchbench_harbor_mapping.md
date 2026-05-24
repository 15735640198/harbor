# Pinchbench To Harbor Mapping

## Pinchbench Source Shape

Pinchbench tasks are markdown files with YAML frontmatter followed by `##` sections.

Expected frontmatter fields:

- `id`, `name`, `category`, `grading_type`, `timeout_seconds`
- `grading_weights` for many `hybrid` tasks
- `workspace_files`, with either `source` plus `dest` or inline `path` plus `content`
- optional `multi_session: true` and `sessions`

Expected body sections:

- `## Prompt`: agent instruction
- `## Expected Behavior`: useful for judge prompt context, not shown to the agent
- `## Grading Criteria`: checklist used as fallback rubric
- `## Automated Checks`: Python code block containing `grade(transcript, workspace_path)`
- `## LLM Judge Rubric`: rubric text for `llm_judge` and `hybrid`
- `## Additional Notes`: useful for humans, not required in the Harbor task

## Harbor Output Shape

The converter emits:

- `task.toml`
- `instruction.md` for single-prompt tasks
- `steps/<session-id>/instruction.md` for multi-session tasks
- `environment/Dockerfile`
- `environment/workspace/...` for files visible to the agent under `/app`
- `tests/test.sh` plus verifier Python for single-step tasks
- `steps/<name>/tests/test.sh` for multi-step final and placeholder verification

Default container details:

- `WORKDIR /app`
- `environment/workspace/` is copied into `/app/`
- Ubuntu base image includes Python, uv, git, curl, jq, Node.js, and npm as a broad default for mixed Pinchbench tasks

## Verifier Mapping

Automated:

- Extract the Python code block from `## Automated Checks`.
- Execute it inside `/tests/run_pinchbench_grade.py`.
- Call `grade(transcript, "/app")`.
- Compute `reward` as the arithmetic mean of numeric criterion scores.
- Write `/logs/verifier/reward.json` with `reward`, `automated`, and per-criterion keys.

LLM judge:

- Generate `/tests/llm_judge.py` using `uv` script dependencies.
- Use Anthropic structured output with `ANTHROPIC_API_KEY` and `MODEL_NAME` from `[verifier.env]`.
- Pass task prompt, expected behavior, summarized transcript, visible workspace text files, and rubric.
- Write `reward` and `llm_judge` scores to `/logs/verifier/reward.json`.

Hybrid:

- Run automated scoring first.
- Run the LLM judge second.
- Combine with `grading_weights.automated` and `grading_weights.llm_judge`, defaulting to `0.5` each.
- Preserve component and criterion scores in `reward.json`.

## Manual Review Checklist

- Confirm every `workspace_files.source` resolved from Pinchbench `assets/`.
- If an automated checker requires a transcript-specific tool call, inspect the generated transcript loader and consider adapting it for the target agent trajectory format.
- If a task has binary inputs, verify they are copied into `environment/workspace/` and not read into the LLM judge context.
- If a task requires browser, Kubernetes, or specialized system packages, adjust `environment/Dockerfile`.
- If a multi-session task relies on truly fresh conversations via `new_session`, review whether Harbor steps provide the desired agent lifecycle for the target agent.
- Validate with `uv run python -c "from harbor.models.task.task import Task; Task('/path/to/generated/task')"`.
