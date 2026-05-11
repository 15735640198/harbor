# Harbor 示例任务说明

本文档详细介绍了 `examples/tasks` 目录下的所有示例任务，包括每个任务的依赖项、测试方法和校验规则。

---

## 1. describe-image

**任务描述**：测试Agent对镜像元数据的访问能力

### 依赖项
- 基础镜像：Alpine Linux
- 无需额外依赖包

### 测试方法
1. 检查Agent是否能正确识别镜像的基础操作系统
2. 验证镜像元数据的访问能力

### 校验规则
- 必须返回正确的操作系统名称（Alpine）
- 能够描述镜像的基本特征

---

## 2. hello-alpine

**任务描述**：最基础的Alpine环境测试任务

### 依赖项
- 基础镜像：Alpine Linux 3.19
- 内置工具：bash、coreutils

### 测试方法
1. 创建 `/app/hello.txt` 文件，内容为 "Hello, world!"
2. 验证文件存在且内容正确

### 校验规则
- Shell测试：`test -f /app/hello.txt && grep -q "Hello, world!" /app/hello.txt`
- Python测试：验证文件存在且内容匹配预期
- 两个测试全部通过得满分

---

## 3. hello-cuda

**任务描述**：CUDA环境能力测试任务

### 依赖项
- 基础镜像：nvidia/cuda:12.3.1-runtime-ubuntu22.04
- 预装CUDA runtime环境

### 测试方法
1. 验证CUDA环境可用性
2. 检查nvcc版本信息

### 校验规则
- 必须成功执行 `nvcc --version` 命令
- 返回的CUDA版本需与镜像版本匹配
- 能够识别GPU设备（如果可用）

---

## 4. hello-healthcheck

**任务描述**：容器健康检查功能测试

### 依赖项
- 基础镜像：Alpine Linux
- 预装：curl、healthcheck工具

### 测试方法
1. 启动简单HTTP服务
2. 验证健康检查端点可用性

### 校验规则
- 服务必须能在30秒内启动完成
- `/health` 端点返回200状态码
- 健康检查连续3次通过

---

## 5. hello-mcp

**任务描述**：MCP（Model Control Protocol）服务测试

### 依赖项
- 基础镜像：Python 3.12 slim
- 预装MCP服务器相关依赖

### 测试方法
1. 启动MCP服务
2. 测试MCP协议通信能力

### 校验规则
- MCP服务在指定端口正常监听
- 能够响应基本的协议请求
- 通信过程无错误返回

---

## 6. hello-multi-step-advanced

**任务描述**：高级多步骤任务示例，展示复杂工作流

### 依赖项
- 基础镜像：Ubuntu 22.04
- 预装：git、python3、nodejs

### 测试方法
分三个步骤执行：
1. **scaffold阶段**：创建项目目录结构和基础文件
2. **implement阶段**：实现核心功能代码
3. **document阶段**：编写项目文档

### 校验规则
- 每个步骤有独立的测试验证
- 前一步骤通过才能进入下一步
- 最终生成完整的可运行项目
- 所有测试用例全部通过

---

## 7. hello-multi-step-bat

**任务描述**：Windows环境下的多步骤任务示例

### 依赖项
- 基础镜像：Windows Server Core
- 预装：PowerShell、cmd

### 测试方法
分两个步骤执行：
1. **create-file阶段**：创建 `hello.txt` 文件
2. **append-content阶段**：向文件追加内容

### 校验规则
- 使用批处理脚本进行测试
- 第一步：验证文件成功创建
- 第二步：验证内容正确追加
- 支持Windows环境下的路径格式

---

## 8. hello-multi-step-simple

**任务描述**：简单多步骤任务示例，展示基础多步工作流

### 依赖项
- 基础镜像：Alpine Linux
- 预装：bash

### 测试方法
分两个步骤执行：
1. **create-file阶段**：创建 `/app/hello.txt` 文件
2. **append-content阶段**：追加 "Hello, world!" 内容

### 校验规则
- 每个步骤独立验证
- 状态在步骤间持久化
- 最终文件内容完全符合预期

---

## 9. hello-skills

**任务描述**：Agent技能调用能力测试

### 依赖项
- 基础镜像：Python 3.12
- 预装：harbor技能运行环境

### 测试方法
1. 调用指定的Agent技能
2. 验证技能执行结果

### 校验规则
- 技能调用成功无错误
- 技能输出符合预期格式
- 能够正确响应技能参数

---

## 10. hello-skills-openclaw

**任务描述**：OpenClaw技能调用测试

### 依赖项
- 基础镜像：OpenClaw运行环境
- 预装OpenClaw相关技能包

### 测试方法
1. 调用OpenClaw专属技能
2. 验证执行结果

### 校验规则
- OpenClaw技能正常加载
- 执行结果符合预期
- 技能返回格式正确

---

## 11. hello-user

**任务描述**：用户权限和工作目录测试

### 依赖项
- 基础镜像：Ubuntu 22.04
- 预置非root用户：`appuser`

### 测试方法
1. 验证Agent以非root用户运行
2. 检查用户目录权限配置

### 校验规则
- 当前用户为 `appuser` 而非root
- 用户目录 `/home/appuser` 可读写
- 能够在用户目录下创建和修改文件

---

## 12. hello-workdir

**任务描述**：工作目录配置测试

### 依赖项
- 基础镜像：Alpine Linux
- 预设工作目录：`/app`

### 测试方法
1. 在工作目录下创建文件
2. 验证路径配置正确性

### 校验规则
- 工作目录默认为 `/app`
- 相对路径操作正确解析
- 无需指定全路径即可访问工作目录下的文件

---

## 13. hello-world

**任务描述**：最简入门任务，测试基本文件操作能力

### 依赖项
- 基础镜像：Alpine Linux
- 预装：bash、coreutils

### 测试方法
在 `/app` 目录下创建 `hello.txt` 文件，内容为 "Hello, world!"

### 校验规则
- 文件必须存在于正确路径
- 文件内容与预期完全一致
- Shell脚本和Python测试双重验证
- 全部通过得1.0分，否则0分

---

## 14. hello-world-bat

**任务描述**：Windows环境下的Hello World任务

### 依赖项
- 基础镜像：Windows Server Core
- 预装：cmd、PowerShell

### 测试方法
在 `C:\app` 目录下创建 `hello.txt` 文件，内容为 "Hello, world!"

### 校验规则
- 使用批处理脚本验证文件存在
- 内容检查通过Windows原生命令完成
- 支持Windows路径格式和换行符

---

## 15. hello-world-openclaw

**任务描述**：OpenClaw环境下的Hello World任务

### 依赖项
- 基础镜像：OpenClaw runtime
- 预装OpenClaw执行环境

### 测试方法
在 `/app` 目录下创建 `hello.txt` 文件，内容为 "Hello, world!"

### 校验规则
- 适配OpenClaw环境的特殊要求
- 文件权限和路径符合OpenClaw规范
- 与标准hello-world任务保持接口一致

---

## 16. llm-judge-example

**任务描述**：LLM作为裁判的评估示例，展示主观任务评估方法

### 依赖项
- 基础镜像：Python 3.12
- 预装：anthropic SDK、pydantic
- 需要配置ANTHROPIC_API_KEY环境变量

### 测试方法
1. Agent编写一首有趣的诗歌保存到 `/app/poem.txt`
2. 调用Claude LLM对诗歌的有趣程度进行评分

### 校验规则
- 使用结构化输出格式，评分范围0.0-1.0
- 评分由LLM根据诗歌内容自动判定
- 结果写入 `/logs/verifier/reward.json`
- 评分越高表示诗歌越有趣

---

## 17. reward-kit-example

**任务描述**：RewardKit编程评分框架使用示例，展示多维度代码评估

### 依赖项
- 基础镜像：Python 3.12
- 预装：harbor-rewardkit工具
- 内置多维度评分标准

### 测试方法
1. 实现 `textstats.py` 模块，包含 `word_count` 和 `most_common` 函数
2. 编写 `analyze.py` 脚本读取文本文件并生成统计结果

### 校验规则
使用RewardKit进行三个维度的评分：
1. **正确性维度**：单元测试通过率，占40%权重
2. **结构维度**：代码结构规范性，占30%权重
3. **质量维度**：代码质量和最佳实践，占30%权重
- 最终得分为各维度加权平均分
- 自动生成详细的评分报告

---

## 通用说明

### 任务结构标准
所有任务均遵循以下目录结构：
```
任务名称/
├── task.toml          # 任务配置文件（元数据、资源限制、超时等）
├── instruction.md     # 给Agent的任务说明
├── environment/       # Docker环境定义
│   └── Dockerfile
├── tests/             # 测试验证脚本
│   ├── test.sh        # 主测试入口
│   └── 其他测试文件
└── solution/          # 参考实现（可选）
```

### 环境变量传递
- 对于需要API密钥等敏感信息的任务，使用 `--ae` 参数传递环境变量
- 示例：`harbor run --ae ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY`

### 多步任务特性
- 多步任务使用 `steps/` 目录组织各个阶段
- 每个步骤有独立的 `instruction.md` 和测试脚本
- 步骤间状态自动持久化，前序步骤失败会终止整个任务

### 评分机制
- 所有任务评分范围为0.0-1.0，1.0表示完全通过
- 多维度评分任务会在reward.json中返回各维度得分详情
- LLM裁判任务返回AI生成的主观评分
