# Claw-Eval Harbor Adapter

This adapter converts the [Claw-Eval benchmark](https://github.com/claw-eval/claw-eval) into the Harbor task format for agent evaluation.

## Overview

Claw-Eval is a comprehensive benchmark for trustworthy evaluation of autonomous agents, featuring:
- 300 human-verified tasks across 9 categories
- Evaluation across 3 dimensions: Completion, Safety, Robustness
- Multi-turn user agent interaction tasks
- Multimodal perception and creation tasks
- General agent capability tasks

## Task Categories

| Category | Count | Description |
|----------|-------|-------------|
| general | 161 | Core agent tasks across communication, finance, ops, productivity, etc. |
| multimodal | 101 | Perception and creation tasks including webpage generation, video QA, document extraction, etc. |
| user_agent | 38 | Conversational tasks with simulated user personas for clarification and advice |

## Usage

### Generate All Tasks

```bash
cd adapters/claw-eval
python run_adapter.py --output-dir ../../datasets/claw-eval
```

### Generate Parity Subset (30 tasks)

```bash
python run_adapter.py --parity --output-dir ../../datasets/claw-eval-parity
```

### Generate Specific Task IDs

```bash
python run_adapter.py --task-ids C01zh_mortgage_prepay C03en_real_estate_finance --output-dir ../../datasets/claw-eval-subset
```

### Filter by Category

```bash
python run_adapter.py --categories finance coding --output-dir ../../datasets/claw-eval-finance-coding
```

### CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--output-dir` | Directory to write generated tasks | `datasets/claw-eval` |
| `--limit` | Maximum number of tasks to generate | All 300 |
| `--parity` | Generate parity subset (30 representative tasks) | False |
| `--overwrite` | Overwrite existing task directories | False |
| `--task-ids` | Only generate specific task IDs | None |
| `--categories` | Only generate tasks from specified categories | None |
| `--source-dir` | Path to Claw-Eval source tasks directory | `./temp-repo/tasks` |

## Running Evaluation

Once tasks are generated, you can run evaluation using Harbor:

```bash
# Run on all Claw-Eval tasks
harbor run --dataset claw-eval --agent <your-agent-name> --n-concurrent 4

# Run on parity subset
harbor run --dataset claw-eval-parity --agent <your-agent-name>
```

## Grading Methodology

The adapter uses LLM-as-judge grading following Claw-Eval's official rubrics:

1. **Single-turn tasks**: Evaluate the final answer against the task rubric and reference solution
2. **Multi-turn tasks**: Evaluate the entire conversation flow, including clarification quality and final response quality
3. **Scoring**: 0.0-1.0 scale, with PASS threshold at 0.6
4. **Default judge model**: gpt-5-mini (configurable via `MODEL_NAME` environment variable)

## Requirements

- Python 3.11+
- PyYAML
- OpenAI Python SDK >= 1.0.0
- OPENAI_API_KEY environment variable set for grading

## Notes

- The GitHub repository does not include large fixture files (videos, datasets). The complete dataset with all fixtures is available on [Hugging Face](https://huggingface.co/datasets/claw-eval/Claw-Eval).
- Multi-turn conversation evaluation requires the agent to log conversation history to `/workspace/conversation_history.json`.
- For more information about Claw-Eval, visit the [official website](https://claw-eval.github.io) or read the [paper](https://arxiv.org/abs/2604.06132).

## License

This adapter is released under the MIT License, same as the original Claw-Eval benchmark.
