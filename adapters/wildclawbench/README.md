# WildClawBench Adapter

This adapter converts WildClawBench Markdown tasks into Harbor task directories.
It is a parity-oriented migration: generated tasks preserve the upstream
`/tmp_workspace` layout, warmup commands, skills, hidden `gt/` grading data, and
embedded Python graders.

## Resource Setup Guide

WildClawBench task resources are not contained in this repository checkout.
They come from the upstream Hugging Face dataset, YouTube, ModelScope, and an
upstream Docker image tarball. A fresh clone needs all of the steps below before
strict conversion can generate runnable Harbor tasks.

### 1. Initialize the upstream task repository

```bash
git submodule update --init related-projects/external-tasks/WildClawBench
```

### 2. Install downloader helpers

Use `uvx` or `uv run --with ...` so the helper dependencies do not have to be
added to Harbor itself. Include `socksio` and `httpx[socks]` if your environment
uses a SOCKS proxy; otherwise Hugging Face or ModelScope may fail with:
`ImportError: Using SOCKS proxy, but the 'socksio' package is not installed`.

```bash
uvx --from "huggingface_hub[cli]" --with "httpx[socks]" --with socksio \
  hf --help
```

For YouTube downloads, install a JavaScript runtime that `yt-dlp` can use for
YouTube signature/challenge extraction. `deno` is the simplest local option:

```bash
brew install deno
```

### 3. Download the upstream workspace

```bash
uvx --from "huggingface_hub[cli]" --with "httpx[socks]" --with socksio \
  hf download internlm/WildClawBench \
  --repo-type dataset \
  --local-dir related-projects/external-tasks/WildClawBench \
  --include "workspace/**"
```

If this command is interrupted or rate-limited, rerun the same command. The Hugging
Face cache resumes files that were already downloaded. Avoid relying on the
short positional form `hf download internlm/WildClawBench workspace`; depending
on the CLI version it may not fetch every nested workspace file.

Two upstream tasks intentionally do not ship an `exec/` workspace:
`01_Productivity_Flow_task_1_arxiv_digest` and
`01_Productivity_Flow_task_9_scp_crawl`. The adapter allows those in strict
mode. Any other missing `exec/` path normally means the workspace download is
incomplete.

### 4. Prepare generated media and model assets

The upstream preparation script downloads/derives the football match video,
lecture video, Apple event video, SAM model weights, and extracted `.git`
fixtures:

```bash
cd related-projects/external-tasks/WildClawBench

uv run \
  --with yt-dlp \
  --with modelscope \
  --with socksio \
  --with "httpx[socks]" \
  bash script/prepare.sh
```

If YouTube returns `Sign in to confirm you're not a bot`, pass cookies to
`yt-dlp`. The upstream script does not expose extra `yt-dlp` flags, so put them
in the standard `yt-dlp` config file before rerunning `prepare.sh`:

```bash
mkdir -p ~/.config/yt-dlp
printf '%s\n' '--cookies-from-browser chrome' > ~/.config/yt-dlp/config
```

You can also use an exported cookies file:

```bash
mkdir -p ~/.config/yt-dlp
printf '%s\n' '--cookies /absolute/path/to/youtube-cookies.txt' > ~/.config/yt-dlp/config
```

If YouTube reports `Requested format is not available` after extracting cookies,
make sure the JavaScript runtime is installed and visible on `PATH`:

```bash
deno --version
uvx --from yt-dlp yt-dlp \
  --js-runtimes deno \
  --list-formats "https://www.youtube.com/watch?v=93LPZJkCW2w"
```

Then rerun `prepare.sh`. Keep the cookies account/session healthy; YouTube may
still reject stale cookies or heavily rate-limited sessions.

Return to the Harbor root when preparation completes:

```bash
cd ../../..
```

### 5. Load and derive the Docker image

```bash
uvx --from "huggingface_hub[cli]" --with "httpx[socks]" --with socksio \
  hf download internlm/WildClawBench \
  --repo-type dataset \
  --local-dir related-projects/external-tasks/WildClawBench \
  --include "Images/wildclawbench-ubuntu_v1.3.tar"

docker load -i related-projects/external-tasks/WildClawBench/Images/wildclawbench-ubuntu_v1.3.tar

bash adapters/wildclawbench/docker/openclaw/build.sh
```

The derived image is tagged `wildclawbench-ubuntu-openclaw:2026.5.27` by
default. It uses `FROM wildclawbench-ubuntu:v1.3`, then installs the pinned
OpenClaw version so Harbor can use the cached binary during task runs.
The build clears the stale proxy variables baked into the upstream image. If
your Docker build requires a proxy, pass `BUILD_HTTP_PROXY` and
`BUILD_HTTPS_PROXY` explicitly.

### 6. Convert the dataset

Use `--link-assets` for full local conversion. WildClawBench's prepared
workspace is large; hardlinking keeps generated task files Docker-visible as
normal files without consuming another full copy on the same filesystem.

```bash
uv run python adapters/wildclawbench/run_adapter.py \
  --output-dir datasets/wildclawbench \
  --link-assets \
  --overwrite
```

Expected conversion notes:

- The adapter should load 60 tasks and generate 60 task directories.
- `edge-tts` may be reported as a missing optional skill. That is expected for
  the current upstream checkout unless the upstream skill is added later.
- If conversion fails with `Prepared WildClawBench workspace missing`, rerun the
  Hugging Face workspace download and `script/prepare.sh`. The error path tells
  you which task resource is missing.
- If conversion fails with `No space left on device`, rerun with `--link-assets`
  or free enough space for a second physical copy of the prepared workspace.

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
