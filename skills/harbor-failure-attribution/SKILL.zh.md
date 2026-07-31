---
name: harbor-failure-attribution
description: 为 Harbor OpenClaw 的 job 或 trial 文件夹编写标准化的失败归因报告。当给定一个包含 result.json、config.json、agent 轨迹、trial 日志、verifier 输出或先前归因笔记的 Harbor job 文件夹路径时使用本 skill,目的是按统一结构创建或刷新 FAILURE_ATTRIBUTION.md。当用户希望对成功或高分的运行进行改进分析、残余风险评估,或对剩余分数损失进行归因时,也可使用本 skill。
---

# Harbor 失败归因

在一个 Harbor OpenClaw 的 trial 文件夹内编写 `FAILURE_ATTRIBUTION.md`。将输入视为单个 job/trial 目录,例如 `jobs/.../<trial_name>` 或 `archived-jobs/.../<trial_name>`。

## 工作流

1. 确认输入路径是单个 trial 文件夹,而不是包含多个 trial 的父级 job 文件夹。一个合法的文件夹通常包含 `result.json`、`config.json`、`trial.log` 和 `agent/trajectory.json`。
2. 运行证据收集器:

```bash
python skills/harbor-failure-attribution/scripts/collect_job_context.py <job-folder>
```

3. 阅读收集器指出的文件。务必检查 `result.json`、`trial.log`,以及在存在时至少检查一个 agent 轨迹来源:
   - `agent/trajectory.json`
   - `agent/openclaw-output.txt`
   - `agent/tar_blocks/action_actions.txt`
   - `agent/tar_blocks/results_actions.txt`
   - `agent/openclaw-session.jsonl`
4. 如果文件夹中已存在名为 `attribution.md`、`failure-attribution.md` 或 `failure_attribution.md` 的先前归因文档,将它们作为笔记阅读,但最终报告必须按下方的标准化结构编写。
5. 如果任务源文件在本地可用,检查 `instruction.md`、verifier 脚本以及相关任务夹具。如果不可用,则从 `result.json`、verifier 指标、日志和轨迹中的第一条用户指令推断预期行为,并说明任务源不可用的情况。
6. 编写或替换 `<job-folder>/FAILURE_ATTRIBUTION.md`。

不要止步于数值化的 reward。使用来自日志、指标和 agent 动作的具体证据,对失败阶段和失败机制进行归因。如果运行成功,仍需分析可避免的低效、脆弱行为、不必要的工具调用、偏低的子分数、缺失的验证,以及健壮性风险。

## 报告结构

使用以下完全一致的顶层章节及顺序。

```markdown
# Failure Attribution: <trial_name>

## 1. 结果概览
## 2. 任务与评分契约
## 3. 已审阅的证据
## 4. 执行时间线
## 5. 得分与失败面
## 6. 根因归因
## 7. 次要因素
## 8. 哪些做对了
## 9. 改进计划
## 10. 待解决问题
```

### 1. 结果概览

包含:
- trial 名称、来源基准、任务名称/路径、agent 名称/版本/模型。
- 最终 reward 及关键子分数。若不存在 reward,写 `Reward: unavailable`。
- trial 状态:`success`、`partial`、`hard failure`、`timeout`、`setup failure`、`verifier failure` 或 `unscored`。
- 一句简洁的定论,点明主要归因。

### 2. 任务与评分契约

解释 agent 需要产出或完成什么。在任务源文件可用时优先使用它们;否则使用轨迹提示、verifier 指标名、`verifier/reward.json` 和 `result.json`。

包含:
- 所需的输出路径、命令、工具调用、外部服务或安全行为。
- 成功是如何衡量的。
- 来自指令中的任何显式约束。

### 3. 已审阅的证据

列出实际检查过的具体文件。当缺失证据本身有意义时也应纳入,例如缺失的 verifier 日志、缺失的输出产物、缺失的轨迹或缺失的 reward。

此处只陈述事实,不要在此处进行归因论证。

### 4. 执行时间线

按时间顺序以要点形式总结运行过程:
- 启动设置与 agent 启动。
- 主要的 agent 动作和工具调用。
- 关键观察/错误。
- 最终的 agent 消息或终止条件。
- verifier 的执行(如果它运行了)。

在可用时使用时间戳或步骤编号。对于冗长的轨迹,将重复动作分组归纳。

### 5. 得分与失败面

精确描述哪些指标通过、哪些失败。

针对每个重要的失败指标或缺失产物,包含:
- 指标名称和数值。
- 预期行为。
- 观测到的行为。
- 支持该观察的证据文件。

如果 reward 很高,聚焦于剩余的分数损失和隐藏的质量风险。如果运行未被评分,解释是哪个阶段阻碍了评分。

### 6. 根因归因

给出一个主要归因及简短理由。在适用时使用以下标签:
- `agent-planning`:错误的计划、遗漏的需求、糟糕的优先级安排。
- `agent-execution`:意图正确但命令、文件、编辑或工具使用错误。
- `agent-recovery`:出错后未能调整、过早停止、不必要地向用户求助。
- `agent-verification`:未检查输出、未运行校验、未对照需求进行验证。
- `tool-use`:误用或误解可用工具。
- `environment-setup`:在真正进入任务工作之前出现的依赖、安装脚本、夹具、凭据、网络或容器问题。
- `benchmark-design`:模糊的提示、不可能的需求、错误的 verifier、缺失的夹具,或提示与环境不匹配。
- `verifier-issue`:verifier 失败、漏报 reward、判定错误产物,或缺少所需诊断信息。
- `safety-policy`:不安全的顺从、未能警示、过度拒绝,或遗漏安全处理。
- `model-capability`:在工具/环境已具备后,大概率是知识、推理、多模态、长上下文或指令遵循方面的能力限制。

说明归因的置信度为 `high`(高)、`medium`(中)或 `low`(低)。当直接原因与深层原因都重要时,将两者分开陈述。

### 7. 次要因素

列出放大了失败但非主要原因的次要因素。示例:
- 缺失的安装日志。
- 模糊的输出路径。
- 未锁定的依赖。
- 冗长且无检查点的轨迹。
- 对认证条件的假设。
- 偏弱的部分得分行为。
- agent 在遇到阻碍后未能生成部分报告。

如果没有有意义的次要因素,写 `None identified`(未发现)。

### 8. 哪些做对了

始终包含此节,即使是零分的运行。记录任何有用的行为:
- 正确的初始理解。
- 部分通过的指标。
- 有用的诊断命令。
- 恰当的拒绝或警示。
- 产物格式正确但内容错误。

对于 agent 从未运行的安装失败,写明没有任何 agent 行为可被认可,并指出测试框架中有哪些行为是起作用的。

### 9. 改进计划

在可能时按责任方分开给出建议:
- Agent 行为:提示词、工具策略、错误恢复、自我验证。
- 基准/任务:指令清晰度、环境、夹具、verifier 诊断。
- 框架/日志:保留安装阶段的 stdout/stderr、产物快照、轨迹完整性。

建议要具体且可验证。包含"什么改变会改变本次运行结果"。

### 10. 待解决问题

列出无法从归档的 job 文件夹中确定的事实。示例:
- 缺失的安装阶段 stderr。
- 未知的预期夹具内容。
- 某次依赖失败是否为偶发。
- 任务源是否与复制后的产物存在差异。

如果都没有,写 `None`。

## 写作规则

- 使用有证据支撑的语言。优先使用"轨迹显示……"而非臆测。
- 报告保持简洁,通常 700 至 1200 字。
- 不要粘贴大段日志或完整轨迹摘录。只引用足以确立事实的短行。
- 不要将环境/安装失败计为模型失败,除非 agent 曾有过实际介入并恢复的机会。
- 不要在未解释 verifier 路径为何失败的情况下,将 verifier 失败计为任务失败。
- 保留不确定性。在证据不完整时使用"可能"、"或许"及置信度标签。
- 切勿只写"任务失败,因为 reward 为 0";要解释因果链条。
- 对于成功的运行,标题仍为 `Failure Attribution`,但将报告定位为残余归因与改进分析。
