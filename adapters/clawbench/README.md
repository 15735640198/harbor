# ClawBench Adapter

This adapter converts the ClawBench Core v1 public manifest into Harbor tasks.
The default source directory is `related-projects/external-tasks/clawbench`, and
the default task list is `tasks-public/MANIFEST.yaml`.

Generate the curated Core public set:

```bash
uv run python adapters/clawbench/src/clawbench_adapter/main.py --overwrite
```

Generate a single task:

```bash
uv run python adapters/clawbench/src/clawbench_adapter/main.py \
  --task-ids t1-bugfix-discount \
  --output-dir /tmp/clawbench-harbor \
  --overwrite
```

The adapter intentionally follows the manifest task list rather than scanning
all YAML files under `tasks-public/`; perturbed variants are present upstream
but are not part of Core v1.
