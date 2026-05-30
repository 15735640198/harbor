# WildClawBench To Harbor Mapping

## WildClawBench Source Shape

WildClawBench tasks are Markdown files under six category directories:

- `01_Productivity_Flow` - 10 tasks
- `02_Code_Intelligence` - 12 tasks
- `03_Social_Interaction` - 6 tasks
- `04_Search_Retrieval` - 11 tasks
- `05_Creative_Synthesis` - 11 tasks
- `06_Safety_Alignment` - 10 tasks

Each task has YAML frontmatter:

- `id`, `name`, `category`, `timeout_seconds`, `modality`

Each task body has these `##` sections:

- `Prompt` - sent to the agent
- `Expected Behavior` - human/grader context only
- `Grading Criteria` - human-readable checklist
- `Automated Checks` - Python code block defining `grade(...)`
- `Workspace Path` - path under upstream `workspace/`
- `Skills` - skill directories under upstream `skills/`
- `Env` - environment variable names expected by prompt or grader
- `Warmup` - shell commands to run before the agent starts

The task data itself is not stored in the GitHub repository. It is downloaded
from the Hugging Face dataset and prepared by upstream `script/prepare.sh`.
Each prepared task workspace may contain:

- `exec/` - files visible to the agent
- `tmp/` - temporary service fixtures copied to `/tmp_workspace/tmp`
- `gt/` - hidden ground truth copied only to Harbor `tests/`

## Harbor Output Shape

The adapter emits one Harbor multi-step task per upstream task:

- `task.toml`
- `environment/Dockerfile`
- `environment/workspace/...` copied from upstream `exec/`
- `environment/skills/...` copied from requested upstream skills when present
- `steps/run/instruction.md`
- `steps/run/workdir/setup.sh`
- `steps/run/tests/test.sh`
- `tests/grade_source.py`
- `tests/run_wildclawbench_grade.py`
- `tests/gt/...` when upstream hidden ground truth exists

The generated Dockerfile uses `wildclawbench-ubuntu:v1.3` by default, sets
`WORKDIR /tmp_workspace`, and symlinks `/app` to `/tmp_workspace` for Harbor
agent compatibility.

## Verifier Mapping

The verifier executes the embedded upstream `grade(...)` function directly.

- `tests/gt/` is copied to `/tmp_workspace/gt` immediately before grading.
- Transcript candidates are loaded from `/logs/agent`, `/logs`, OpenClaw's
  session path, and Claude Code's compatibility path.
- Compatibility transcript files are written to hard-coded OpenClaw and Claude
  Code paths before the grader runs, because several upstream graders inspect
  those paths directly.
- The verifier calls `grade(transcript=..., workspace_path="/tmp_workspace")`.
- `overall_score` is used as Harbor `reward` when present; otherwise the reward
  is the arithmetic mean of numeric scores.
- On verifier exceptions, Harbor receives zero reward and the traceback is
  written to `/logs/verifier/error.txt`.

## Environment And Model Mapping

Generated verifiers accept both WildClawBench-style OpenRouter variables and the
PinchBench Harbor job config convention:

- `OPENROUTER_API_KEY` falls back to `ANTHROPIC_API_KEY`
- `OPENROUTER_BASE_URL` falls back to `ANTHROPIC_BASE_URL`
- `JUDGE_MODEL` falls back to `MODEL_NAME`

The default example job mirrors `examples/configs/pinchbench-job.yaml`:

- OpenClaw agent
- `model_name: anthropic/kimi-k2.6`
- `context_window: 200000`
- `max_tokens: 8192`
- verifier `MODEL_NAME: glm-5.1`

## Manual Review Checklist

- Confirm upstream workspace data was downloaded and `script/prepare.sh` ran.
- Confirm `wildclawbench-ubuntu:v1.3` is loaded locally before running tasks.
- Confirm generated `environment/` trees do not contain upstream `gt/`.
- Inspect tasks with warmup services, especially Social Interaction tasks, to
  ensure background service commands stay running.
- Inspect tasks requesting missing optional skills, currently `edge-tts`, and
  either provide the skill upstream or accept the warning.
- Validate generated task configs with
  `from harbor.models.task.task import Task; Task('/path/to/task')`.
