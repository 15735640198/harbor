# Pinchbench Adapter

This adapter converts Pinchbench task markdown files into Harbor task directories.

By default, conversion runs through a Claude Code harness. The adapter copies the
adapter-local `pinchbench-to-harbor` skill into the active Claude Code config
directory (`$CLAUDE_CONFIG_DIR/skills` or `~/.claude/skills` by default),
asks Claude Code to use `$pinchbench-to-harbor`, and validates each generated
Harbor task.

## Usage

Generate one task through Claude Code:

```bash
uv run python adapters/pinchbench/src/pinchbench_adapter/main.py \
  --task-ids task_weather \
  --overwrite
```

Generate the Pinchbench core subset:

```bash
uv run python adapters/pinchbench/src/pinchbench_adapter/main.py \
  --core \
  --overwrite
```

For deterministic local smoke tests that do not call an agent, use the direct
skill-script harness:

```bash
uv run python adapters/pinchbench/src/pinchbench_adapter/main.py \
  --harness direct \
  --task-ids task_weather \
  --output-dir /tmp/pinchbench-harbor \
  --overwrite
```

The default source directory is `related-projects/external-tasks/skill`, which
is expected to contain Pinchbench `tasks/` and `assets/`.

## Notes

- Automated Pinchbench checks are converted into deterministic Harbor verifier
  scripts that execute the embedded `grade(transcript, workspace_path)` function.
- `llm_judge` and `hybrid` tasks generate an Anthropic-based verifier modeled
  after Harbor's `examples/tasks/llm-judge-example`.
- The upstream Pinchbench corpus does not provide oracle solutions, so this
  adapter does not emit `solution/solve.sh`.
