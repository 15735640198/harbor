# LiveClawBench Adapter

This adapter imports the 134 native Harbor task directories from
[Mosi-AI/LiveClawBench](https://github.com/Mosi-AI/LiveClawBench). It does not
translate trajectory data: the related
[Mosi-AI/LiveClawbench-trajectories](https://huggingface.co/datasets/Mosi-AI/LiveClawbench-trajectories)
repository contains ATIF execution traces and leaderboard records, not the
task environments, verifiers, or oracle solutions.

The upstream tasks already use Harbor's directory layout. The adapter copies
each task unchanged, except that it inserts `[task].name =
"mosi-ai/<task-id>"`; upstream task files omit this registry-required field.

## Generate the local dataset

```bash
git clone --depth 1 https://github.com/Mosi-AI/LiveClawBench.git \
  related-projects/external-tasks/liveclawbench

# Commit validated by this adapter: 2026-06-10 / v0.2.1 task corpus
git -C related-projects/external-tasks/liveclawbench checkout \
  aae6d0ad6127eb648ef9117a6e9705c4ee8dc57b

uv run python adapters/liveclawbench/src/liveclawbench_adapter/main.py --overwrite
```

The default output is `datasets/liveclawbench`. It is intentionally local in
this checkout because `datasets/` is gitignored.

Useful selection flags:

```bash
# Regenerate one task into a temporary directory
uv run python adapters/liveclawbench/src/liveclawbench_adapter/main.py \
  --source-dir related-projects/external-tasks/liveclawbench \
  --task-ids watch-shop \
  --output-dir /tmp/liveclawbench \
  --overwrite
```

## Runtime prerequisites

The task Dockerfiles reference LiveClawBench's OpenClaw base images (for
example, `liveclawbench-base:latest` and per-task base images). Build those
images with the upstream repository before running a task. This Harbor checkout
does not include the OpenClaw agent implementation, so execution also requires
an OpenClaw-enabled Harbor runtime, such as the upstream `Mosi-AI/claw-harbor`
setup used by LiveClawBench.

The import itself is self-contained and can be validated locally:

```bash
uv run python - <<'PY'
from pathlib import Path
from harbor.models.task.task import Task

tasks = sorted(Path("datasets/liveclawbench").glob("*/task.toml"))
assert len(tasks) == 134
assert all(Task(path.parent).config.task is not None for path in tasks)
print(f"validated {len(tasks)} tasks")
PY
```
