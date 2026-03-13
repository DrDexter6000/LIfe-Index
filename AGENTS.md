# AGENTS.md - Life Index 项目开发指南

> 本文档为 Life Index 项目开发、为 AI 编码代理（如：OpenCode）提供项目上下文，帮助理解代码库结构、命令和约定。

## 项目概述

**Life Index** 是一个为 OpenClaw 设计的 Agent Skill（技能包），提供个人生活日志记录能力。用户通过自然语言与 Agent 交互，Agent 调用 Python 原子工具完成日志的记录、搜索、编辑和摘要生成。

**核心理念**:
- **Agent-first**：发挥 Agent 自然语言理解和生成能力，仅在需要原子性/准确性时开发专用工具
- **本地优先**：所有数据存储在 `~/Documents/Life-Index/`
- **纯文本格式**：Markdown + YAML Frontmatter，永不过时
- **跨平台**：支持 Windows/Linux/macOS

---

## Agent-First 开发原则

> 本节定义 Agent Skill 开发的核心原则，对标 [Agent Skills 规范](https://agentskills.io/specification)。

### 1. 能力边界

Agent 具备以下原生能力，**禁止开发重复工具**：

| Agent 原生能力 | 说明 | 禁止行为 |
|---------------|------|----------|
| 自然语言理解 | 解析用户意图、提取元数据 | 开发"意图解析器"脚本 |
| 自然语言生成 | 生成摘要、润色文本 | 开发"文本生成器"脚本 |
| 定时任务 (Cron) | 内置调度能力 | 使用 OS 级别定时任务（Windows Task Scheduler / crontab） |
| 文件操作 | 读写、搜索、编辑文件 | 除非需要原子性/事务性 |
| 模式匹配 | 识别日期、标签、格式 | 开发正则提取工具 |

### 2. 工具开发准则

**开发专用工具的条件**（必须满足至少一项）：

1. **原子性要求**：操作必须全部成功或全部失败（如写入日志 + 更新索引）
2. **准确性要求**：需要精确计算或验证（如文件名序列号、路径安全检查）
3. **重复性要求**：高频调用的确定性操作（如天气查询、索引构建）

**禁止开发**：
- Agent 可通过自然语言完成的任务
- 可用现有 CLI 工具替代的脚本
- 仅做简单字符串处理的工具

### 3. 指令设计原则

- **简练**：每条指令控制在 1-3 句
- **准确**：使用精确术语，避免歧义
- **结构化**：使用表格、列表、代码块增强可读性
- **可验证**：提供成功/失败的判断标准

```markdown
# ✅ 好的指令
调用 write_journal.py，参数 date 为当天日期，content 为用户原文。

# ❌ 差的指令
首先你需要理解用户想要记录什么内容，然后思考一下日期格式，
接着可能需要查询天气，最后把数据写入文件系统...
```

### 4. 定时任务规范

**必须使用 Agent 内置 Cron 能力**，禁止 OS 级别定时任务。

| 任务类型 | Agent Cron | OS 定时任务 |
|---------|-----------|-------------|
| 日报/周报/月报 | ✅ 使用 | ❌ 禁止 |
| 索引更新 | ✅ 使用 | ❌ 禁止 |
| 数据清理 | ✅ 使用 | ❌ 禁止 |

定时任务配置详见 [SCHEDULE.md](references/schedule/SCHEDULE.md)。

## 构建与运行命令

### 依赖安装

```bash
# 必需依赖
# Python 3.11+ (核心运行环境)

# 可选依赖（语义搜索）
pip install -r tools/requirements.txt
# 或手动安装
pip install sentence-transformers>=2.2.0
```

### 核心工具命令

所有工具位于 `tools/` 目录，通过 Bash 调用。详见 [API.md](docs/API.md) 完整接口文档。

**模块结构**（2026-03-13更新）:
```
tools/
├── write_journal/              # 写入日志模块
│   ├── __init__.py            # CLI入口
│   ├── __main__.py            # 模块执行入口
│   ├── core.py                # 核心协调逻辑（~220行，含事务保护）
│   ├── utils.py               # 通用工具函数
│   ├── frontmatter.py         # YAML frontmatter格式化（工具专用）
│   ├── attachments.py         # 附件处理逻辑
│   ├── weather.py             # 天气查询相关
│   └── index_updater.py       # 索引更新逻辑
├── search_journals/            # 搜索日志模块
│   ├── __init__.py            # CLI入口
│   ├── __main__.py            # 模块执行入口
│   ├── core.py                # 核心协调逻辑（~230行）
│   ├── utils.py               # 通用工具函数（SSOT：使用lib/frontmatter）
│   ├── l1_index.py            # 一级索引搜索（by-topic索引）
│   ├── l2_metadata.py         # 二级元数据搜索（带SQLite缓存，性能提升50-100x）
│   ├── l3_content.py          # 三级内容搜索（全文搜索）
│   ├── semantic.py            # 语义搜索相关
│   └── ranking.py             # 结果排序算法
├── edit_journal.py            # 编辑日志
├── generate_abstract.py       # 生成摘要
├── build_index.py             # 构建索引
├── query_weather.py           # 查询天气
├── validate_data.py           # 数据完整性校验（开发工具）
├── rebuild_indices.py         # 索引重建（开发工具）
└── lib/                       # 共享库
    ├── config.py              # 配置
    ├── errors.py              # 错误码
    ├── frontmatter.py         # YAML frontmatter统一解析/格式化（SSOT）
    ├── metadata_cache.py      # 元数据缓存（L2搜索性能优化）
    ├── search_index.py        # 搜索索引
    ├── semantic_search.py     # 语义搜索
    └── vector_index_simple.py # 向量索引
```

```bash
# 写入日志
python -m tools.write_journal --data '{"title":"...","content":"...","date":"2026-03-07","topic":"work"}'

# 搜索日志
python -m tools.search_journals --query "关键词" --level 3
python -m tools.search_journals --topic work --project Life-Index --limit 10

# 语义搜索（需安装 sentence-transformers）
python -m tools.search_journals --query "学习笔记" --semantic

# 编辑日志
python tools/edit_journal.py --journal "Journals/2026/03/life-index_2026-03-07_001.md" --set-weather "晴天"

# 生成摘要
python tools/generate_abstract.py --month 2026-03
python tools/generate_abstract.py --year 2026

# 构建索引
python tools/build_index.py           # 增量更新
python tools/build_index.py --rebuild # 全量重建

# 查询天气
python tools/query_weather.py --location "Lagos,Nigeria"
```

### 测试命令

本项目采用自然语言描述 + Agent 执行的 E2E 测试方案，无 pytest 等测试框架：

```bash
# E2E 测试由 Agent 执行，读取 YAML 测试用例
# 测试文件位置: tests/e2e/*.yaml
# 测试报告输出: tests/reports/e2e-report-{timestamp}.md
```

测试流程（当用户说"执行 E2E 测试"）：
1. 读取 `tests/e2e/phase1-core-workflow.yaml` 等测试文件
2. 按 priority 和 id 顺序执行测试用例
3. 记录各步骤耗时和结果
4. 生成报告到 `tests/reports/`

---

## 代码风格指南

### Python 代码规范

**文件结构**:
```python
#!/usr/bin/env python3
"""
模块说明文档字符串
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 常量定义
CONSTANT_NAME = "value"

def function_name(param: type) -> return_type:
    """函数文档字符串"""
    pass

if __name__ == "__main__":
    main()
```

**命名约定**:
- 函数/变量: `snake_case`
- 常量: `UPPER_SNAKE_CASE`
- 类: `PascalCase`
- 私有函数: `_leading_underscore`

**类型注解**: 必须使用类型注解
```python
def process_data(data: Dict[str, Any], items: List[str]) -> Optional[str]:
    ...
```

**路径处理**: 统一使用 `pathlib.Path`
```python
from pathlib import Path
file_path = Path(__file__).parent / "data" / "file.txt"
```

**编码**: 所有文件使用 UTF-8 编码
```python
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()
```

### JSON 输出格式

所有工具返回标准 JSON 格式：
```json
{
  "success": true,
  "data": { ... },
  "error": "错误信息（如有）"
}
```

### 错误处理

- 不使用裸 `except`，捕获具体异常
- 错误信息通过 JSON 返回，不抛出未捕获异常
- 网络失败（如天气查询）允许主流程继续

---

## 日志文件格式

### 目录结构

```
~/Documents/Life-Index/
├── Journals/                    # 日志主目录
│   └── YYYY/MM/                 # 按年月组织
│       ├── life-index_YYYY-MM-DD_NNN.md
│       └── monthly_abstract.md  # 月度摘要
├── by-topic/                    # 主题索引
│   ├── 主题_work.md
│   ├── 项目_Life-Index.md
│   └── 标签_亲子.md
└── attachments/                 # 附件存储
    └── YYYY/MM/
```

### Markdown 格式

```yaml
---
title: "日志标题"
date: 2026-03-07T14:30:00
location: "Lagos, Nigeria"
weather: "晴天 28°C/22°C"
mood: ["专注", "充实"]
people: ["团团"]
tags: ["重构", "优化"]
project: "LifeIndex"
topic: ["work", "create"]
abstract: "100字内摘要"
attachments: ["file.mp4"]
---

# 日志标题

正文内容...
```

### Topic 分类（必填）

| Topic | 含义 |
|-------|------|
| `work` | 工作/职业 |
| `learn` | 学习/成长 |
| `health` | 健康/身体 |
| `relation` | 关系/社交 |
| `think` | 思考/反思 |
| `create` | 创作/产出 |
| `life` | 生活/日常 |

---

## 关键约束与禁止事项

### 工具调用规则

**必须通过 Bash CLI 调用工具，禁止 Python import 直接调用**：
```bash
# ✅ 正确
python tools/write_journal.py --data '{...}'

# ❌ 错误
from tools.write_journal import write_journal
```

### 内容保留原则

- 用户原始输入的 `content` 必须 100% 原样传递
- 禁止修改段落结构、Markdown 标题、列表格式
- 禁止"优化"或改造用户输入

### 数据隔离

- 用户数据: `~/Documents/Life-Index/`
- 项目代码: `D:\Loster AI\Projects\life-index\`
- 两者物理隔离，不可混淆

---

## 相关文档

| 文档 | 内容 |
|------|------|
| `SKILL.md` | Agent 技能定义、触发词、工具接口 |
| `docs/HANDBOOK.md` | 项目愿景、架构设计、核心原则 |
| `docs/INSTRUCTIONS.md` | Agent 执行指令、工作流步骤 |
| `docs/API.md` | 工具 API 接口文档 |
| `references/schedule/SCHEDULE.md` | 定时任务配置（日报/周报/月报） |
| `references/` | 参考文档（天气流程、错误码） |

---

## 常见开发任务

### 添加新工具

1. 在 `tools/` 目录创建 Python 文件
2. 实现 CLI 接口（argparse）
3. 返回标准 JSON 格式
4. 在 `SKILL.md` 中添加工具说明

### 修改日志格式

1. 更新 `tools/write_journal/frontmatter.py` 中的 `format_frontmatter()`
2. 同步更新 `tools/lib/frontmatter.py` 中的统一解析逻辑
3. 同步更新 `tools/lib/config.py` 中的模板
4. 更新 `docs/HANDBOOK.md` 文档

### 添加 E2E 测试

1. 在 `tests/e2e/` 创建或修改 YAML 文件
2. 按格式添加测试用例
3. 更新 `tests/e2e/README.md` 说明


---

## SSOT 文档维护原则


> 本项目遵循单一事实来源（SSOT）原则，所有关键文档职责清晰、独立、互相引用。
### 文档职责

| 文档 | 职责 | 维护时机 |
|------|------|----------|
| `AGENTS.md` | 项目上下文、开发约定 | 项目结构变更时 |
| `SKILL.md` | Agent 技能定义、触发词、工具接口 | 工具接口变更时 |
| `docs/HANDBOOK.md` | 项目愿景、架构设计、核心原则 | 架构决策时 |
| `docs/INSTRUCTIONS.md` | Agent 执行指令、工作流步骤 | 工作流变更时 |
| `docs/CHANGELOG.md` | 决策变更历史 | 每次重大变更时 |

### Agent 维护责任

当执行以下操作时，**必须**同步更新 SSOT 文档：

1. **修改工作流逻辑** → 更新 `docs/INSTRUCTIONS.md`
2. **调整工具接口** → 更新 `SKILL.md` + `docs/CHANGELOG.md`
3. **变更架构/原则** → 更新 `docs/HANDBOOK.md` + `docs/CHANGELOG.md`
4. **完成里程碑** → 更新 `docs/CHANGELOG.md`

---

## 跨平台兼容性

> 本项目面向开源社群，必须支持 Windows/Linux/macOS。

### 路径处理规范

**必须使用 `pathlib.Path`**，禁止字符串拼接路径：

```python
# ✅ 正确 - 跨平台兼容
from pathlib import Path
data_dir = Path.home() / "Documents" / "Life-Index"
config_file = Path(__file__).parent / "config.json"

# ❌ 错误 - 平台特定
config_file = __file__.replace('\\', '/') + "/config.json"
```

### 用户数据目录

| 平台 | 用户数据目录 |
|------|-------------|
| Windows | `C:\Users\{username}\Documents\Life-Index\` |
| macOS | `~/Documents/Life-Index/` |
| Linux | `~/Documents/Life-Index/` |

**获取方式**：`Path.home() / "Documents" / "Life-Index"`

### 编码规范

- 所有文件必须使用 **UTF-8 编码**
- 读写文件时显式指定 `encoding='utf-8'`
- 避免使用平台特定编码（如 Windows 的 GBK）

### 换行符处理

- Git 配置 `core.autocrlf=input`（提交时转换为 LF）
- 代码中统一使用 `\n`，避免 `\r\n`

---

## 最佳实践对标

> 当对实施方案不确定时，参考以下最佳实践。

### Agent Skills 规范

本项目遵循 [Agent Skills 规范](https://agentskills.io/specification)：

- 技能名称：小写字母数字和连字符，最多 64 字符
- 描述：最多 1024 字符，包含"when to use"触发信息
- 格式：`SKILL.md` + YAML frontmatter

### 参考资源

| 资源 | 用途 |
|------|------|
| [Agent Skills 规范](https://agentskills.io/specification) | 技能定义标准 |
| [Anthropic Skills 仓库](https://github.com/anthropics/skills) | 官方技能示例 |
| [Awesome Claude Skills](https://github.com/ComposioHQ/awesome-claude-skills) | 社区技能列表 |
| [Claude Skills Hub](https://www.claudeskill.site/zh/skills) | 技能市场 |

### 不确定时的处理流程

1. **搜索同类案例**：在 GitHub 搜索 "agent-skill"、"claude-skill" 主题
2. **参考官方示例**：查看 Anthropic 官方技能仓库的实现模式
3. **咨询社区**：在相关社区提问或搜索已有讨论
4. **记录决策**：将最终方案和原因记录到 `docs/CHANGELOG.md`

---

## 设计底线

```
宁可功能简单，不可系统复杂
宁可人工维护，不可自动化陷阱
宁可牺牲性能，不可牺牲可靠性
```