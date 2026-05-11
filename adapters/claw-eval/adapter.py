"""
Claw-Eval Adapter - Towards Trustworthy Evaluation of Autonomous Agents.

300 human-verified tasks across 9 categories: Agents perceive, reason, create, and deliver.
Grading dimensions: Completion, Safety, Robustness.

Source: https://github.com/claw-eval/claw-eval
"""

from __future__ import annotations

import json
import logging
import shutil
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "template"
SOURCE_TASKS_DIR = Path(__file__).parent / "temp-repo" / "tasks"

# Tasks excluded due to known issues
EXCLUDED_TASKS = set()

# Task category mapping for tags
CATEGORY_TAGS = {
    "user_agent": "multi-turn-conversation",
    "general": "general-agent",
    "multimodal": "multimodal",
    "productivity": "productivity",
    "finance": "finance",
    "ops": "operations",
    "coding": "coding",
    "design": "design",
    "research": "research",
}


class ClawEvalTask:
    """Represents a single Claw-Eval task with associated metadata and rubrics."""

    def __init__(self, task_dir: Path):
        self.task_dir = task_dir
        self.task_id = task_dir.name
        
        # Load task metadata
        task_yaml_path = task_dir / "task.yaml"
        with open(task_yaml_path, "r", encoding="utf-8") as f:
            self.task_meta = yaml.safe_load(f)
            
        self.task_name = self.task_meta.get("task_name", self.task_id)
        self.language = self.task_meta.get("prompt", {}).get("language", "zh")
        self.category = self.task_meta.get("category", "general")
        self.difficulty = self.task_meta.get("difficulty", "medium")
        self.tags = self.task_meta.get("tags", [])
        self.prompt = self.task_meta.get("prompt", {}).get("text", "")
        self.user_agent_config = self.task_meta.get("user_agent", {})
        self.judge_rubric = self.task_meta.get("judge_rubric", "")
        self.reference_solution = self.task_meta.get("reference_solution", "")
        self.scoring_components = self.task_meta.get("scoring_components", [])
        
        # Load grader.py if exists
        grader_path = task_dir / "grader.py"
        self.grader_code = None
        if grader_path.exists():
            self.grader_code = grader_path.read_text(encoding="utf-8")

    @property
    def is_multi_turn(self) -> bool:
        """Check if this is a multi-turn user agent task."""
        return self.user_agent_config.get("enabled", False)

    @property
    def has_user_persona(self) -> bool:
        """Check if this task has a user persona for multi-turn interactions."""
        return "persona" in self.user_agent_config


class ClawEvalAdapter:
    """Converts Claw-Eval tasks into Harbor format."""

    NAME = "claw-eval"

    @staticmethod
    def make_local_task_id(source_task_id: str) -> str:
        """Convert source benchmark ID to Harbor task ID."""
        return f"claw-eval-{source_task_id.lower()}"

    def __init__(self, task_dir: Path, source_tasks_dir: Path | None = None):
        self.task_dir = Path(task_dir)
        self.source_tasks_dir = source_tasks_dir or SOURCE_TASKS_DIR
        
        # Load all tasks
        self.tasks = self._load_all_tasks()
        logger.info(f"Loaded {len(self.tasks)} Claw-Eval tasks")

    def _load_all_tasks(self) -> list[ClawEvalTask]:
        """Load all Claw-Eval tasks from the source directory."""
        tasks = []
        for task_dir in self.source_tasks_dir.iterdir():
            if not task_dir.is_dir() or task_dir.name in EXCLUDED_TASKS:
                continue
                
            try:
                task = ClawEvalTask(task_dir)
                tasks.append(task)
            except Exception as e:
                logger.warning(f"Failed to load task {task_dir.name}: {e}")
                
        return sorted(tasks, key=lambda t: t.task_id)

    def _build_instruction(self, task: ClawEvalTask) -> str:
        """Build instruction.md with task description and requirements."""
        template = (TEMPLATE_DIR / "instruction.md").read_text(encoding="utf-8")
        
        # Add multi-turn notice if applicable
        multi_turn_notice = ""
        if task.is_multi_turn:
            multi_turn_notice = (
                "## Important: Multi-turn Interaction\n"
                "This is a multi-turn user agent task. You will need to interact with a simulated user to collect information and provide assistance.\n"
                "Respond to the user naturally and professionally.\n\n"
            )
        
        instruction = template.replace("{task_name}", task.task_name)
        instruction = instruction.replace("{task_prompt}", task.prompt)
        instruction = instruction.replace("{multi_turn_notice}", multi_turn_notice)
        instruction = instruction.replace("{language}", task.language)
        
        return instruction

    def _prepare_task(self, task: ClawEvalTask, output_dir: Path) -> None:
        """Generate a single task directory from template."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy environment template
        env_dir = output_dir / "environment"
        env_dir.mkdir(exist_ok=True)
        shutil.copy2(TEMPLATE_DIR / "environment" / "Dockerfile", env_dir / "Dockerfile")
        
        # Create task-specific environment files
        # Copy any fixtures if they exist (note: full fixtures are on Hugging Face)
        fixtures_dir = self.source_tasks_dir.parent / "data" / "fixtures"
        if fixtures_dir.exists():
            task_fixtures = []  # Would get from task_meta['fixture'] in full dataset
            dest_fixtures_dir = env_dir / "fixtures"
            dest_fixtures_dir.mkdir(exist_ok=True)
            for fixture in task_fixtures:
                src = fixtures_dir / fixture
                if src.exists():
                    shutil.copy2(src, dest_fixtures_dir / fixture)
        
        # Generate tests directory
        tests_dir = output_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        shutil.copy2(TEMPLATE_DIR / "tests" / "test.sh", tests_dir / "test.sh")
        shutil.copy2(TEMPLATE_DIR / "tests" / "llm_judge.py", tests_dir / "llm_judge.py")
        
        # Generate ground_truth.json with all task metadata
        ground_truth = {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "language": task.language,
            "category": task.category,
            "difficulty": task.difficulty,
            "question": task.prompt,
            "judge_rubric": task.judge_rubric,
            "reference_solution": task.reference_solution,
            "scoring_components": task.scoring_components,
            "is_multi_turn": task.is_multi_turn,
            "user_persona": task.user_agent_config.get("persona", "") if task.is_multi_turn else "",
            "max_rounds": task.user_agent_config.get("max_rounds", 0) if task.is_multi_turn else 0,
        }
        (tests_dir / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")
        
        # Copy task-specific grader if exists
        if task.grader_code:
            (tests_dir / "task_grader.py").write_text(task.grader_code, encoding="utf-8")
        
        # Generate task.toml with category-specific tags
        task_toml = (TEMPLATE_DIR / "task.toml").read_text(encoding="utf-8")
        category_tag = CATEGORY_TAGS.get(task.category, task.category.lower())
        tags = [
            "claw-eval",
            category_tag,
            f"lang:{task.language}",
            f"difficulty:{task.difficulty}",
        ]
        if task.is_multi_turn:
            tags.append("multi-turn")
        
        tags_str = f'[{ ", ".join(f'"{t}"' for t in tags) }]'
        task_toml = task_toml.replace('tags = ["claw-eval"]', f"tags = {tags_str}")
        task_toml = task_toml.replace('category = "agent-tasks"', f'category = "{task.category}"')
        task_toml = task_toml.replace('difficulty = "medium"', f'difficulty = "{task.difficulty}"')
        
        local_task_id = self.make_local_task_id(task.task_id)
        task_toml = task_toml.replace("{task_name}", f"claw-eval/{local_task_id}")
        (output_dir / "task.toml").write_text(task_toml, encoding="utf-8")
        
        # Generate instruction.md
        instruction = self._build_instruction(task)
        (output_dir / "instruction.md").write_text(instruction, encoding="utf-8")
        
        # Generate solution
        solution_dir = output_dir / "solution"
        solution_dir.mkdir(exist_ok=True)
        solution_content = f"# Reference Solution for {task.task_name}\n\n{task.reference_solution}\n"
        (solution_dir / "SOLUTION.md").write_text(solution_content, encoding="utf-8")
        solve_sh = (TEMPLATE_DIR / "solution" / "solve.sh").read_text()
        (solution_dir / "solve.sh").write_text(solve_sh)

    def generate_all_tasks(self, limit: int | None = None, categories: list[str] | None = None) -> None:
        """Generate all (or limited) task directories."""
        tasks_to_generate = self.tasks
        
        # Filter by category if specified
        if categories:
            tasks_to_generate = [t for t in tasks_to_generate if t.category in categories]
            logger.info(f"Filtered to {len(tasks_to_generate)} tasks in categories: {categories}")
        
        # Apply limit
        if limit is not None:
            tasks_to_generate = tasks_to_generate[:limit]
            
        for i, task in enumerate(tasks_to_generate):
            local_task_id = self.make_local_task_id(task.task_id)
            output_dir = self.task_dir / local_task_id
            self._prepare_task(task, output_dir)
            if (i + 1) % 50 == 0:
                logger.info(f"Progress: {i + 1}/{len(tasks_to_generate)}")
                
        logger.info(f"Generated {len(tasks_to_generate)} tasks in {self.task_dir}")

    def generate_task(self, source_task_id: str, local_task_id: str | None = None) -> None:
        """Generate a single Harbor task from a source identifier."""
        task = next((t for t in self.tasks if t.task_id == source_task_id), None)
        if task is None:
            raise ValueError(f"Task with ID {source_task_id} not found")
            
        if not local_task_id:
            local_task_id = self.make_local_task_id(source_task_id)
            
        output_dir = self.task_dir / local_task_id
        self._prepare_task(task, output_dir)
        logger.info(f"Generated task: {local_task_id}")
