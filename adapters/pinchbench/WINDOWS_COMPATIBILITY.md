# Windows/PowerShell 环境兼容性报告

## ✅ 已兼容部分
### 1. Python 代码
- 所有 Python 代码使用 `pathlib.Path` 处理路径，自动适配 Windows 路径格式
- 文件读写使用 `encoding="utf-8"`，避免中文乱码
- 路径拼接使用 `/` 操作符，`pathlib` 自动转换为 Windows `\`

### 2. 适配器命令
✅ 命令可以直接在 PowerShell 中运行：
```powershell
# 列出任务
python run_adapter.py list-tasks --repo-path C:\temp\pinchbench-skill

# 生成任务
python run_adapter.py generate --repo-path C:\temp\pinchbench-skill --limit 2
```
(路径格式与 PowerShell 完全兼容)

### 3. Docker 环境
- 任务运行在 Linux 容器中，与 Windows 主机环境隔离
- Dockerfile 基于标准 Python 镜像，跨平台兼容

## ⚠️ 潜在不兼容问题及解决方案
### 问题 1: 评分脚本使用 `bc` 命令
**问题描述**：`tests/test.sh` 第 32 行使用 `bc` 命令计算平均分数，该命令在 BusyBox 环境可能未安装
**修复方案**：改用 Python 计算分数：
```bash
# 替换 test.sh 第32行
FINAL_SCORE=$(python3 -c "print(($AUTOMATED_SCORE + $JUDGE_SCORE) / 2)")
```

### 问题 2: jq 命令可能缺失
**问题描述**：`test.sh` 使用 `jq` 解析 JSON，基础 Python 镜像可能未预装
**修复方案**：在 Dockerfile 中添加 jq 安装：
```dockerfile
# 在 Dockerfile 第6行后添加
RUN apt-get update && apt-get install -y --no-install-recommends jq bc && rm -rf /var/lib/apt/lists/*
```

### 问题 3: 路径大小写敏感
**问题描述**：PinchBench 仓库的文件名大小写与 Linux 容器可能不匹配
**修复方案**：适配器已自动处理文件路径，使用 `Path.exists()` 检查文件

### 问题 4: 换行符问题
**问题描述**：Windows 换行符 `CRLF` 可能导致 bash 脚本执行失败
**修复方案**：已使用 LF 换行符保存所有模板文件，生成的脚本自动使用 LF

## ✅ 修复后的文件
### 1. 更新 Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /workspace

# Install required dependencies for grading
RUN apt-get update && apt-get install -y --no-install-recommends jq bc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir openai>=1.0.0 pyyaml>=6.0.1

# Copy assets if any
COPY assets/ /workspace/ 2>/dev/null || true
```

### 2. 可选：更新 test.sh 移除 bc 依赖
```bash
# 替换第32行的 bc 计算为 Python
FINAL_SCORE=$(python3 -c "print(f\"{($AUTOMATED_SCORE + $JUDGE_SCORE) / 2:.2f}\")")
```

## 📋 Windows 用户使用指南
### 前置要求
1. Docker Desktop 已启动（Linux 容器模式，默认设置即可）
2. Python 3.11+ 已安装
3. 已克隆 PinchBench 仓库：`git clone https://github.com/pinchbench/skill.git C:\temp\pinchbench-skill`

### 使用步骤
```powershell
# 1. 进入适配器目录
cd C:\Users\admin\Documents\harbor\zt-harbor\harbor\adapters\pinchbench

# 2. 安装依赖
pip install typer markdown-it-py pyyaml openai

# 3. 查看可用任务
python run_adapter.py list-tasks --repo-path C:\temp\pinchbench-skill

# 4. 生成所有任务
python run_adapter.py generate --repo-path C:\temp\pinchbench-skill

# 5. 运行任务测试
uv run harbor trial start --path ..\..\datasets\pinchbench\task_access_log_anomaly --agent claude-code
```

## 🎯 兼容性验证
```powershell
# 验证1：生成任务正常
python run_adapter.py generate --repo-path C:\temp\pinchbench-skill --limit 1

# 验证2：生成的文件结构正常
ls ..\..\datasets\pinchbench\task_access_log_anomaly
```
