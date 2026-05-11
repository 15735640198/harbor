# 📋 第三方Benchmark转换为Harbor Dataset完整流程

## 🔖 概述
将第三方Benchmark适配到Harbor平台，本质是将其转换为符合Harbor规范的**Dataset格式**，并创建对应的**Adapter适配器**完成自动化转换和执行。

---

## 🚀 完整转换流程

### 1. 前期准备与分析
```bash
# 1.1 拉取第三方Benchmark代码
git clone <第三方bench仓库地址> ./3rd-party-bench
cd ./3rd-party-bench

# 1.2 分析Benchmark结构和特性
# 重点了解：
# - 用例组织结构（按什么维度分类？每个用例包含哪些文件？）
# - 任务类型（代码生成、文本生成、推理任务、多模态任务？）
# - 评判标准（自动评测、人工评测、LLM评测？）
# - 依赖环境（需要什么操作系统、编程语言、软件包？）
# - 输出格式（预期生成什么文件？什么格式？）
```

### 2. 创建Adapter适配器
Adapter是转换的核心，负责将第三方Benchmark的用例批量转换为Harbor格式的Task。

```bash
# 2.1 在Harbor的adapters目录下创建新adapter目录
cd $HARBOR_ROOT/adapters
mkdir my-new-bench
cd my-new-bench

# 2.2 创建必备文件
touch adapter.py      # 核心转换逻辑
touch run_adapter.py  # 转换执行入口
touch README.md       # 适配说明文档
touch adapter_metadata.json  # 元数据配置
mkdir template        # Task模板目录
```

#### 2.3 编写Task模板（template目录）
每个Task必须包含3个核心文件，作为模板：
```
template/
├── task.toml         # 任务配置模板
├── instruction.md    # 任务指令模板
└── environment/
    └── Dockerfile    # 环境配置模板
```

**task.toml示例：**
```toml
[metadata]
name = "${TASK_NAME}"
description = "${TASK_DESCRIPTION}"
tags = ["${TASK_TAG}", "my-new-bench"]
difficulty = "${TASK_DIFFICULTY}"

[environment]
image = "python:3.11-slim"
cpu = 2
memory = "4G"
timeout_sec = 1800

[verifier]
grading_type = "${GRADING_TYPE}"  # llm_judge / automated / hybrid
```

**Dockerfile示例：**
```dockerfile
FROM python:3.11-slim
# 安装所有需要的依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
# 安装Python依赖
RUN pip install --no-cache-dir pytest requests anthropic
```

### 3. 编写转换逻辑（adapter.py）
实现将第三方用例批量转换为Harbor Task的逻辑：
```python
import os
import shutil
from pathlib import Path
from typing import List, Dict

class MyBenchAdapter:
    def __init__(self, source_dir: str, output_dir: str):
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.template_dir = Path(__file__).parent / "template"
        
    def convert_all(self, filter_tags: List[str] = None) -> int:
        """转换所有符合条件的用例"""
        converted_count = 0
        
        # 遍历第三方bench的所有用例
        for case_dir in self.source_dir.glob("cases/*"):
            # 1. 读取第三方用例元数据
            case_meta = self._read_case_metadata(case_dir)
            
            # 2. 用例过滤（跳过不需要的用例）
            if not self._should_include(case_meta, filter_tags):
                continue
                
            # 3. 生成Harbor格式的Task
            self._convert_single_case(case_dir, case_meta)
            converted_count += 1
            
        return converted_count
        
    def _should_include(self, case_meta: Dict, filter_tags: List[str] = None) -> bool:
        """用例过滤规则"""
        # 跳过规则：
        # 1. 跳过需要特殊硬件（GPU等）的用例
        if case_meta.get("requires_gpu"):
            return False
        # 2. 跳过含有违法违规内容的用例
        if case_meta.get("is_sensitive"):
            return False
        # 3. 跳过执行时间过长的用例（>30分钟）
        if case_meta.get("timeout", 0) > 1800:
            return False
        # 4. 跳过不支持的编程语言
        if case_meta.get("language") not in ["python", "javascript"]:
            return False
        # 5. 根据传入的标签过滤
        if filter_tags and not any(tag in case_meta.get("tags", []) for tag in filter_tags):
            return False
            
        return True
        
    def _convert_single_case(self, case_dir: Path, case_meta: Dict):
        """转换单个用例为Harbor Task格式"""
        task_name = case_meta["name"]
        task_dir = self.output_dir / task_name
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 生成task.toml
        task_toml = self.template_dir / "task.toml"
        target_toml = task_dir / "task.toml"
        content = task_toml.read_text()
        content = content.replace("${TASK_NAME}", task_name)
        content = content.replace("${TASK_DESCRIPTION}", case_meta["description"])
        content = content.replace("${GRADING_TYPE}", case_meta["grading_type"])
        target_toml.write_text(content)
        
        # 2. 生成instruction.md
        instruction = self.template_dir / "instruction.md"
        target_instruction = task_dir / "instruction.md"
        content = instruction.read_text()
        content = content.replace("${TASK_PROMPT}", case_meta["prompt"])
        target_instruction.write_text(content)
        
        # 3. 复制environment目录
        env_dir = task_dir / "environment"
        shutil.copytree(self.template_dir / "environment", env_dir)
        
        # 4. 复制测试文件到tests目录
        tests_dir = task_dir / "tests"
        tests_dir.mkdir()
        # 复制第三方用例中的测试脚本、ground truth等
        for test_file in case_dir.glob("test_*.py"):
            shutil.copy(test_file, tests_dir)
        for gt_file in case_dir.glob("ground_truth.*"):
            shutil.copy(gt_file, tests_dir)
            
        # 5. 生成验证脚本test.sh
        self._generate_test_script(tests_dir, case_meta)
```

### 4. 编写转换执行入口（run_adapter.py）
```python
import argparse
from adapter import MyBenchAdapter

def main():
    parser = argparse.ArgumentParser(description="Convert MyBench to Harbor dataset format")
    parser.add_argument("--source", required=True, help="Path to MyBench source directory")
    parser.add_argument("--output", default="./dataset", help="Output directory for converted dataset")
    parser.add_argument("--filter-tags", nargs="+", help="Filter cases by tags")
    
    args = parser.parse_args()
    
    adapter = MyBenchAdapter(args.source, args.output)
    count = adapter.convert_all(args.filter_tags)
    print(f"✅ Successfully converted {count} cases to Harbor dataset format")
    print(f"📂 Output directory: {args.output}")

if __name__ == "__main__":
    main()
```

### 5. 执行转换生成Dataset
```bash
# 5.1 执行转换脚本
cd $HARBOR_ROOT/adapters/my-new-bench
python run_adapter.py --source ../../3rd-party-bench --output ../../datasets/my-new-bench

# 5.2 查看生成的Dataset结构
# 理想结构：
datasets/my-new-bench/
├── task_case_1/
│   ├── task.toml
│   ├── instruction.md
│   ├── environment/
│   │   └── Dockerfile
│   └── tests/
│       ├── test.sh
│       ├── test_case.py
│       └── ground_truth.json
├── task_case_2/
└── ...
```

### 6. 本地验证Dataset有效性
```bash
# 6.1 单独测试一个用例，确保可以正常运行
cd $HARBOR_ROOT
uv run harbor run --task datasets/my-new-bench/task_case_1 --agent claude-code

# 6.2 验证用例运行流程：
# - 环境是否正常创建
# - 智能体是否能接收到指令
# - 结果是否能正常生成
# - 验证器是否能正常评分
# - 结果是否能正常保存
```

### 7. 注册Dataset到Harbor（可选）
如果需要在Harbor中作为内置Dataset使用：
```bash
# 7.1 添加到registry.json
{
  "datasets": [
    {
      "name": "my-new-bench",
      "description": "My new benchmark dataset",
      "path": "./datasets/my-new-bench",
      "tags": ["code-generation", "text-generation"],
      "version": "1.0.0"
    }
  ]
}

# 7.2 同步到数据库（如果使用远程存储）
uv run python scripts/sync_registry_to_supabase.py
```

---

## 🧪 转换后运行测试用例

### 单个用例运行
```bash
# 运行单个指定Task
uv run harbor run --task datasets/my-new-bench/task_case_1 --agent claude-code --model anthropic/claude-3-opus

# 传递环境变量给智能体
uv run harbor run --task datasets/my-new-bench/task_case_1 --agent claude-code \
  --ae ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --ae OPENAI_API_KEY=$OPENAI_API_KEY

# 传递环境变量给验证器
uv run harbor run --task datasets/my-new-bench/task_case_1 --agent claude-code \
  --ve OPENAI_API_KEY=$OPENAI_API_KEY
```

### 批量运行整个Dataset
```bash
# 运行整个Dataset，并发度4
uv run harbor run --dataset my-new-bench --agent claude-code --n-concurrent 4

# 只运行包含指定标签的用例
uv run harbor run --dataset my-new-bench --agent claude-code --tags python easy

# 每个用例运行多次取平均值
uv run harbor run --dataset my-new-bench --agent claude-code --runs-per-task 3
```

### 运行配置文件模式（推荐）
创建`benchmark-config.yaml`：
```yaml
dataset: my-new-bench
agent: claude-code
model: anthropic/claude-3-5-sonnet-20241022
n_concurrent: 4
tags: ["python"]
agent_env:
  ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
verifier_env:
  OPENAI_API_KEY: "${OPENAI_API_KEY}"
```

运行：
```bash
uv run harbor run -c benchmark-config.yaml
```

### 结果查看与分析
```bash
# 查看所有运行结果
uv run harbor view jobs

# 查看某个具体Job的详细结果
uv run harbor view jobs/2026-05-09__17-37-49

# 生成分析报告
uv run harbor analyze jobs/2026-05-09__17-37-49 --report output.html
```

---

## ⚠️ 注意事项与最佳实践
1. **用例过滤原则**：
   - ❌ 跳过需要特殊硬件（GPU、TPU等）的用例
   - ❌ 跳过包含敏感、违法内容的用例
   - ❌ 跳过执行时间过长（>30分钟）的用例
   - ❌ 跳过依赖不明确、难以复现环境的用例
   - ✅ 优先转换环境依赖简单、测试逻辑清晰的用例

2. **环境配置原则**：
   - ✅ Docker镜像尽量使用官方基础镜像，保持轻量化
   - ✅ 所有依赖明确版本，避免使用latest标签
   - ✅ 国内环境建议配置镜像源，加速构建

3. **验证脚本原则**：
   - ✅ test.sh必须保证无论执行成功失败，都生成reward.txt
   - ✅ 所有错误都要有回退机制，避免出现RewardFileNotFoundError
   - ✅ LLM评测提示词要明确、具体，减少主观判断偏差

4. **性能优化原则**：
   - ✅ 常用镜像提前pull到本地，避免重复构建
   - ✅ 大体积Dataset建议使用增量转换
   - ✅ 批量运行时根据机器资源合理设置并发度