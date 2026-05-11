"""
Run the PinchBench adapter to generate Harbor tasks.
"""
from __future__ import annotations

import logging
import typer
from pathlib import Path

from adapter import PinchBenchAdapter

app = typer.Typer(help="PinchBench to Harbor task converter")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent.parent / "datasets" / "pinchbench"


@app.command()
def generate(
    repo_path: str = typer.Option(
        ..., 
        help="Path to cloned pinchbench/skill repository (e.g., /tmp/pinchbench-skill)"
    ),
    output_dir: str = typer.Option(
        DEFAULT_OUTPUT_DIR,
        help="Output directory for generated Harbor tasks (default: ../../datasets/pinchbench)"
    ),
    limit: int = typer.Option(
        0,
        help="Limit number of tasks to generate (0 = all)"
    ),
    skip_existing: bool = typer.Option(
        True,
        help="Skip tasks that already exist in output directory"
    ),
):
    """Generate Harbor tasks from PinchBench benchmark."""
    try:
        adapter = PinchBenchAdapter(repo_path)
        adapter.generate_all(output_dir, limit=limit)
        logger.info(f"\n✅ Success! Generated tasks to: {Path(output_dir).resolve()}")
    except Exception as e:
        logger.error(f"❌ Failed to generate tasks: {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def list_tasks(
    repo_path: str = typer.Option(
        ..., 
        help="Path to cloned pinchbench/skill repository"
    ),
):
    """List all available PinchBench tasks."""
    try:
        adapter = PinchBenchAdapter(repo_path)
        logger.info(f"Found {len(adapter.tasks)} valid tasks:\n")
        
        for i, task in enumerate(adapter.tasks, 1):
            status = "✓"
            logger.info(f"{i:2d}. {task.id:<30} | {task.category:<15} | {task.grading_type:<10} | {status}")
        
        logger.info(f"\nTotal: {len(adapter.tasks)} tasks")
    except Exception as e:
        logger.error(f"❌ Failed to list tasks: {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
