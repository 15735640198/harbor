# OpenClaw 测试 PinchBench 快速开始指南

## 前置要求
✅ 环境变量已设置：
- `OPENAI_API_KEY` - 用于 LLM 法官评分（必须）
- `ANTHROPIC_API_KEY` - 如果使用 Anthropic 模型（根据你的模型配置）

✅ 已生成 PinchBench 任务到 `datasets/pinchbench/` 目录

## 运行测试
```powershell
# 进入harbor根目录
cd C:\Users\admin\Documents\harbor\zt-harbor\harbor

# 运行测试
uv run harbor run -c adapters/pinchbench/pinchbench-openclaw-test.yaml
```

## 测试说明
### 阶段1：基础验证（默认只开启这两个）
1. **task_access_log_anomaly** - 日志异常分析任务
   - 评分方式：automated（自动验证输出格式和内容）
   - 预期：Agent 应该分析日志文件，找出异常条目
2. **task_blog** - 博客写作任务
   - 评分方式：llm_judge（AI 法官根据评分标准打分）
   - 预期：Agent 应该根据要求生成符合规范的技术博客

### 阶段2：全量测试（基础验证通过后）
修改 `pinchbench-openclaw-test.yaml`，注释掉基础任务，放开下面的全部任务注释，运行全量测试。

## 查看结果
```powershell
# 查看任务结果
uv run harbor view

# 查看具体任务的评分详情
# 结果保存在 jobs/<job-id>/trial-<task-id>/logs/verifier/
```

## 常见问题
1. **任务超时**：可以调高 `timeout_multiplier` 到 2.0 或更高
2. **模型上下文不足**：确保使用 128k 上下文的模型，比如 `claude-3-5-sonnet`
3. **LLM 法官评分异常**：检查 `OPENAI_API_KEY` 是否正确配置
