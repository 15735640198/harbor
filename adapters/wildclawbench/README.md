# WildClawBench Adapter

This adapter converts WildClawBench Markdown tasks into Harbor task directories.
It is a parity-oriented migration: generated tasks preserve the upstream
`/tmp_workspace` layout, warmup commands, skills, hidden `gt/` grading data, and
embedded Python graders.

## Prerequisites

Initialize the WildClawBench submodule, download the external workspace data,
prepare the large media/model assets, load the upstream base image, and build
the Harbor derived image with the current OpenClaw cached inside:

```bash
git submodule update --init related-projects/external-tasks/WildClawBench

hf download internlm/WildClawBench workspace \
  --repo-type dataset \
  --local-dir related-projects/external-tasks/WildClawBench

bash related-projects/external-tasks/WildClawBench/script/prepare.sh

hf download internlm/WildClawBench Images/wildclawbench-ubuntu_v1.3.tar \
  --repo-type dataset \
  --local-dir related-projects/external-tasks/WildClawBench

docker load -i related-projects/external-tasks/WildClawBench/Images/wildclawbench-ubuntu_v1.3.tar

bash adapters/wildclawbench/docker/openclaw/build.sh
```

The derived image is tagged `wildclawbench-ubuntu-openclaw:2026.5.27` by
default. It uses `FROM wildclawbench-ubuntu:v1.3`, then installs the pinned
OpenClaw version so Harbor can use the cached binary during task runs.
The build clears the stale proxy variables baked into the upstream image. If
your Docker build requires a proxy, pass `BUILD_HTTP_PROXY` and
`BUILD_HTTPS_PROXY` explicitly.

## Usage

Generate all tasks:

```bash
uv run python adapters/wildclawbench/src/wildclawbench_adapter/main.py \
  --output-dir datasets/wildclawbench \
  --link-assets \
  --overwrite
```

Generate a structural smoke subset without downloaded assets:

```bash
uv run python adapters/wildclawbench/src/wildclawbench_adapter/main.py \
  --task-ids 06_Safety_Alignment_task_7_skill_injection \
  --no-strict-assets \
  --output-dir /tmp/wildclawbench-harbor \
  --overwrite
```

Run the generated dataset with the default Harbor config:

```bash
uv run harbor run -c examples/configs/wildclawbench-job.yaml
```

## Notes

- The adapter copies upstream `exec/` files into the agent-visible workspace.
  Pass `--link-assets` to hardlink large workspace and `gt/` files instead of
  duplicating the prepared WildClawBench workspace on disk.
- Upstream `gt/` files are copied only under hidden `tests/` and staged into
  `/tmp_workspace/gt` during verification.
- Generated tasks use `wildclawbench-ubuntu-openclaw:2026.5.27` by default.
  Pass `--base-image` to target a different local derivative.
- Generated task Dockerfiles pin `--platform=linux/amd64` because upstream
  WildClawBench images are amd64-only. Pass `--base-platform ""` to omit it.
- The generated verifier aliases `OPENROUTER_*` from `ANTHROPIC_*` when needed,
  and aliases `JUDGE_MODEL` from `MODEL_NAME`.
- WildClawBench does not ship oracle solutions, so this adapter does not emit
  `solution/solve.sh`.
