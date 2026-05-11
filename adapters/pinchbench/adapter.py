import re
import json
import yaml
from pathlib import Path
from markdown_it import MarkdownIt
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

TEMPLATE_DIR = Path(__file__).parent / "template"

@dataclass
class PinchBenchTask:
    """表示一个PinchBench任务"""
    id: str
    title: str
    description: str
    instruction: str
    grading_type: str
    automated_grading_code: Optional[str]
    llm_judge_rubric: Optional[str]
    difficulty: str
    category: str
    workspace_files: Dict[str, str]
    multi_session: bool = False

class PinchBenchAdapter:
    """PinchBench到Harbor格式的适配器"""
    
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.tasks_dir = self.repo_path / "tasks"
        self.md = MarkdownIt()
    
    def list_tasks(self) -> List[Path]:
        """列出所有任务文件"""
        return list(self.tasks_dir.glob("task_*.md"))
    
    def parse_task(self, task_file: Path) -> Optional[PinchBenchTask]:
        """解析单个任务文件"""
        try:
            content = task_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"无法读取文件 {task_file}: {e}")
            return None
        
        # 分割frontmatter和内容
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
            frontmatter_raw = parts[1].strip()
            content = parts[2].strip()
            
            try:
                frontmatter = yaml.safe_load(frontmatter_raw)
            except Exception as e:
                print(f"无法解析frontmatter {task_file}: {e}")
                return None
        else:
            frontmatter = {}
        
        task_id = task_file.stem
        
        # 提取元数据
        title = frontmatter.get("title", task_id.replace("_", " ").title())
        description = frontmatter.get("description", "")
        difficulty = frontmatter.get("difficulty", "medium")
        category = frontmatter.get("category", "general")
        grading_type = frontmatter.get("grading_type", "llm_judge")
        multi_session = frontmatter.get("multi_session", False)
        
        # 提取自动化评分代码
        automated_grading_code = None
        llm_judge_rubric = None
        
        if grading_type == "automated":
            # 查找```python代码块，包含grade函数
            code_blocks = re.findall(r"```python\n(.*?)\n```", content, re.DOTALL)
            for block in code_blocks:
                if "def grade(" in block:
                    automated_grading_code = block
                    break
        else:
            # 查找评分标准
            rubric_match = re.search(r"## (评分标准|Rubric)\n(.*?)(?=\n##|$)", content, re.DOTALL)
            if rubric_match:
                llm_judge_rubric = rubric_match.group(2).strip()
        
        # 提取工作区文件
        workspace_files = {}
        file_blocks = re.findall(r"```(.+?)\n(.*?)\n```", content, re.DOTALL)
        for ext, content_block in file_blocks:
            ext = ext.strip()
            # 支持两种格式：path=filename 或 source=filename dest=filename
            path_match = re.match(r"path\s*=\s*(.+)", ext)
            if path_match:
                filename = path_match.group(1).strip()
                workspace_files[filename] = content_block
            else:
                dest_match = re.match(r".*dest\s*=\s*(.+)", ext)
                if dest_match:
                    filename = dest_match.group(1).strip()
                    workspace_files[filename] = content_block
        
        # 清理内容，移除代码块和frontmatter
        instruction = re.sub(r"```.*?```", "", content, flags=re.DOTALL).strip()
        instruction = re.sub(r"---.*?---", "", instruction, flags=re.DOTALL).strip()
        
        # 跳过需要外部服务的任务
        skip_keywords = ["email", "mail", "claw", "server", "api key", "token"]
        if any(keyword in instruction.lower() for keyword in skip_keywords):
            print(f"跳过需要外部服务的任务: {task_id}")
            return None
        
        return PinchBenchTask(
            id=task_id,
            title=title,
            description=description,
            instruction=instruction,
            grading_type=grading_type,
            automated_grading_code=automated_grading_code,
            llm_judge_rubric=llm_judge_rubric,
            difficulty=difficulty,
            category=category,
            workspace_files=workspace_files,
            multi_session=multi_session
        )
    
    def generate_harbor_task(self, task: PinchBenchTask, output_dir: Path) -> None:
        """生成Harbor格式的任务"""
        task_dir = output_dir / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 生成task.toml
        config_template = (TEMPLATE_DIR / "task.toml").read_text(encoding="utf-8")
        # 转换任务名称为合法格式：使用pinchbench/前缀，替换空格为连字符，转小写
        valid_task_name = f"pinchbench/{task.title.replace(' ', '-').lower()}"
        config_content = config_template.replace("$$TASK_NAME$$", valid_task_name)
        config_content = config_content.replace("$$TASK_DESCRIPTION$$", task.description)
        config_content = config_content.replace("$$TASK_DIFFICULTY$$", task.difficulty)
        config_content = config_content.replace("$$TASK_CATEGORY$$", task.category)
        
        timeout_sec = 900 if task.multi_session else 300
        config_content = config_content.replace("$$TIMEOUT_SEC$$", str(timeout_sec))
        
        (task_dir / "task.toml").write_text(config_content, encoding="utf-8")
        
        # 2. 生成instruction.md
        (task_dir / "instruction.md").write_text(task.instruction, encoding="utf-8")
        
        # 3. 复制环境文件
        env_dir = task_dir / "environment"
        env_dir.mkdir(exist_ok=True)
        
        dockerfile_content = (TEMPLATE_DIR / "environment" / "Dockerfile").read_text(encoding="utf-8")
        (env_dir / "Dockerfile").write_text(dockerfile_content, encoding="utf-8")
        
        # 4. 生成测试文件
        tests_dir = task_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        
        # 复制test.sh
        test_script = (TEMPLATE_DIR / "tests" / "test.sh").read_text(encoding="utf-8")
        (tests_dir / "test.sh").write_text(test_script, encoding="utf-8")
        
        # 生成grade_runner.py （automated/hybrid评分）
        if task.grading_type in ("automated", "hybrid"):
            grade_template = (TEMPLATE_DIR / "tests" / "grade_runner.py").read_text(encoding="utf-8")
            grade_content = grade_template.replace("$$GRADING_CODE$$", task.automated_grading_code or "")
            (tests_dir / "grade_runner.py").write_text(grade_content, encoding="utf-8")
        
        # 生成judge.py （llm_judge/hybrid评分）
        if task.grading_type in ("llm_judge", "hybrid"):
            judge_template = (TEMPLATE_DIR / "tests" / "judge-anthropic.py").read_text(encoding="utf-8")
            # 替换任务ID和评分rubric
            judge_content = judge_template.replace("$$TASK_ID$$", task.id)
            judge_content = judge_content.replace("$$RUBRIC$$", task.llm_judge_rubric or "")
            (tests_dir / "judge.py").write_text(judge_content, encoding="utf-8")
        
        # 5. 生成工作区文件
        assets_dir = task_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        
        for filename, content in task.workspace_files.items():
            file_path = assets_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        
        # 6. 生成解决方案目录（占位）
        solution_dir = task_dir / "solution"
        solution_dir.mkdir(exist_ok=True)
        (solution_dir / "solve.sh").write_text("#!/bin/bash\necho \"Solution not provided\"", encoding="utf-8")
        
        print(f"生成任务: {task.id}")
    
    def generate_all(self, output_dir: str | Path, limit: Optional[int] = None) -> None:
        """生成所有任务"""
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        task_files = self.list_tasks()
        print(f"找到 {len(task_files)} 个任务文件")
        
        tasks = []
        for task_file in task_files:
            task = self.parse_task(task_file)
            if task:
                tasks.append(task)
        
        print(f"成功加载 {len(tasks)} 个有效任务")
        
        if limit and limit > 0:
            tasks = tasks[:limit]
            print(f"限制生成前 {limit} 个任务")
        
        for task in tasks:
            self.generate_harbor_task(task, output_dir)