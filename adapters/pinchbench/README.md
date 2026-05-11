# PinchBench Adapter for Harbor

Adapter to convert [PinchBench](https://github.com/pinchbench/skill) benchmark tasks to Harbor format for agent evaluation.

## Overview

PinchBench is a real-world benchmark for AI agents containing **23 tasks across 7 categories**:
- 📅 Productivity
- 🔬 Research
- ✍️ Writing
- 💻 Coding
- 📊 Analysis
- 📧 Email
- 🧠 Memory

This adapter converts all valid PinchBench tasks to Harbor's standard task format, supporting all three PinchBench grading modes:
- **automated**: Scored by embedded Python `grade()` function
- **llm_judge**: Scored by LLM using task-specific rubric
- **hybrid**: Average of automated and LLM judge scores

## Quick Start

### 1. Prerequisites
- Python 3.11+
- `uv` package manager
- Cloned PinchBench repository
- OpenAI API Key (for LLM judge grading)

### 2. Clone PinchBench repository
```bash
git clone https://github.com/pinchbench/skill.git /tmp/pinchbench-skill
```

### 3. Generate Harbor tasks
```bash
cd adapters/pinchbench

# Generate all valid tasks
uv run run_adapter.py generate --repo-path /tmp/pinchbench-skill

# Or generate a limited number of tasks
uv run run_adapter.py generate --repo-path /tmp/pinchbench-skill --limit 5
```

### 4. Run evaluation
```bash
# Set your OpenAI API Key (for LLM judge)
export OPENAI_API_KEY="sk-..."

# Run the full benchmark with an agent
uv run harbor run --dataset pinchbench --agent claude-code --model anthropic/claude-3-5-sonnet

# Or run a single task
uv run harbor trial start --path ../../datasets/pinchbench/task_calendar --agent claude-code
```

## Task List

Run `list_tasks` to see all available tasks:
```bash
uv run run_adapter.py list_tasks --repo-path /tmp/pinchbench-skill
```

### Skipped Tasks
The following tasks are skipped by default (they depend on external services not generally available):
- `task_clawdhub` - Requires ClawHub service
- `task_skill_search` - Requires ClawHub service
- `task_openclaw_comprehension` - Specific to OpenClaw platform
- `task_image_gen` - Requires image generation API
- `task_email_triage` - Requires email service access
- `task_email_search` - Requires email service access

## Generated Task Structure

Each generated task follows Harbor's standard structure:
```
datasets/pinchbench/task_{name}/
├── task.toml               # Harbor task configuration
├── instruction.md          # Agent instructions
├── environment/
│   └── Dockerfile          # Task environment definition
├── tests/
│   ├── test.sh             # Grading entry point
│   ├── ground_truth.json   # Task metadata
│   ├── grade_runner.py     # Automated grading (if applicable)
│   └── judge.py            # LLM judge grading (if applicable)
├── assets/                 # Workspace files (if applicable)
└── solution/
    └── solve.sh            # Oracle solution stub
```

## Grading Logic

### Automated Grading
For `automated` and `hybrid` tasks, runs the embedded `grade()` function extracted directly from the PinchBench task definition. The function checks workspace files and agent actions against expected criteria.

### LLM Judge Grading
For `llm_judge` and `hybrid` tasks, uses the task-specific rubric to evaluate agent output. Default judge model is `gpt-5-mini` (configurable via `LLM_JUDGE_MODEL` environment variable).

### Hybrid Grading
Final score is the average of automated and LLM judge scores.

## Configuration

### Environment Variables
| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for LLM judge |
| `OPENAI_BASE_URL` | No | Custom OpenAI API endpoint (for proxies) |
| `LLM_JUDGE_MODEL` | No | Judge model name (default: `gpt-5-mini`) |

### Task Configuration
Task timeouts, resource requirements, and grading type are all extracted from the original PinchBench task definition.

## Development

### Adding Support for Skipped Tasks
To enable skipped tasks:
1. Edit `SKIP_TASKS` set in `adapter.py`
2. Add required environment variables for external services
3. Update the Dockerfile to include any needed dependencies

### Modifying Grading Logic
- Automated grading: Edit the `grade()` function extraction logic in `adapter.py`
- LLM judge: Edit the prompt template in `template/tests/judge.py`

## Reference

- [PinchBench GitHub Repository](https://github.com/pinchbench/skill)
- [Harbor Documentation](https://github.com/harbor-framework/harbor)
