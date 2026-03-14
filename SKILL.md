---
name: life-index
description: "Personal life journaling system with dual-dimension indexing. Use when user says 'record journal', 'log this', 'search logs', 'generate summary', '记日志', '写日记', '搜索记录', '生成摘要'. Features: auto weather, semantic search, attachment handling."
user-invocable: true
disable-model-invocation: false
metadata: {"clawdbot":{"emoji":"📖","requires":{"bins":["python"]}}}
triggers:
  - "/life-index"
  - "记日志"
  - "写日记"
  - "记录一下"
  - "write journal"
  - "daily log"
  - "log this"
  - "record this"
---

# Life Index Agent Skill

> **完整工作流、工具参数、错误处理**: 详见 [INSTRUCTIONS.md](docs/INSTRUCTIONS.md)

---

## Triggers

| 意图 | 触发词（中英文） |
|:---:|:---|
| 记录日志 | "记日志"、"记录一下"、"写日记"、"记下来"、"log this"、"record this"、"write journal"、"daily log" |
| 搜索日志 | "查找日志"、"搜索记录"、"找一下关于...的日记"、"search journal"、"find log" |
| 编辑日志 | "修改日志"、"补充日记"、"更新记录"、"edit journal"、"update log" |
| 生成摘要 | "生成摘要"、"月度总结"、"年度总结"、"generate summary"、"monthly report" |
| 生成日报 | "生成日报"、"今日总结"、"daily report" |
| 生成周报 | "生成周报"、"本周总结"、"weekly report" |
| 生成年报 | "生成年报"、"年度回顾"、"yearly report" |

---

## When to Use

1. **记录日志**：用户说"记录一下今天..."、"记日志..."、"log this..." → `write_journal`
2. **搜索日志**：用户说"查找关于...的日志"、"去年春天的记录"、"search for..." → `search_journals`
3. **编辑日志**：用户说"修改昨天的日志"、"补充一下那篇日记"、"edit..." → `edit_journal`
4. **生成摘要**：用户说"生成月度摘要"、"查看年度总结"、"generate summary..." → `generate_abstract`
5. **定时报告**：日报/周报/月报/年报 → 参考 [SCHEDULE.md](references/schedule/SCHEDULE.md)

---

## Quick CLI Reference

```bash
# 记录日志（所有元数据字段必填，即使为空）
python -m tools.write_journal --data '{"title":"...","content":"...","date":"2026-03-14","topic":["work"],"abstract":"...","mood":[],"people":[],"project":"","tags":[],"links":[]}'

# 搜索日志
python -m tools.search_journals --query "关键词" --topic work --level 3
python -m tools.search_journals --query "学习" --semantic  # 语义搜索

# 编辑日志
python -m tools.edit_journal --journal "Journals/2026/03/life-index_2026-03-14_001.md" --set-location "Beijing"

# 生成摘要
python -m tools.generate_abstract --month 2026-03
python -m tools.generate_abstract --year 2026

# 查询天气
python -m tools.query_weather --location "Lagos,Nigeria"

# 构建索引
python -m tools.build_index           # 增量更新
python -m tools.build_index --rebuild # 全量重建
```

---

## Core Constraints

### Tool Invocation

**必须通过 `python -m tools.xxx` 模块模式调用，禁止直接 import 或手动操作文件。**

```bash
# ✅ 正确
python -m tools.write_journal --data '{...}'

# ❌ 错误
from tools.write_journal import write_journal
python tools/write_journal.py --data '{...}'
```

### Content Preservation (MUST)

**100% 保留用户原始输入**：
- 不修改段落结构
- 不改变标题层级
- 不转换列表格式
- 不添加序号标记

```markdown
# ❌ 错误
用户输入："1、完成A 2、完成B"
Agent 改成："1. 完成A\n2. 完成B"

# ✅ 正确
用户输入什么，content 字段就原封不动传递什么
```

### Guardrails

- **永不删除文件**：编辑只修改内容
- **数据隔离**：数据在 `~/Documents/Life-Index/`
- **天气处理**：详见 [WEATHER_FLOW.md](references/WEATHER_FLOW.md)

---

## Required Metadata Fields

写入日志时，必须包含所有元数据字段（即使为空值）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| title | string | ✅ | 日志标题 |
| content | string | ✅ | 日志正文（100%原样保留） |
| date | string | ✅ | ISO 8601 日期时间 |
| abstract | string | ✅ | ≤100字摘要（Agent生成） |
| topic | array | ✅ | 主题分类，必填（如["work"]） |
| mood | array | ✅ | 心情标签，必填，Agent语义提取1~3个（如["开心","专注"]） |
| tags | array | ✅ | 标签，必填，Agent语义提取关键词（可多个） |
| location | string | ❌ | 地点，默认"Chongqing, China"，Agent询问后可更改 |
| weather | string | ❌ | 天气，根据确认的地点自动查询 |
| people | array | ❌ | 相关人物，Agent语义提取，没有则留空 |
| project | string | ❌ | 关联项目，Agent语义提取，没有则留空 |
| links | array | ❌ | 相关链接 |
| attachments | array | ❌ | 附件路径（自动检测） |

**Agent 职责**：
1. **必填字段**：title, content, date, abstract, topic, mood, tags — 必须有值
2. **语义提取**：从用户内容中主动提取 mood（1~3个）、tags（关键词）、people、project
3. **默认值**：location 默认 "Chongqing, China"，Agent可主动询问用户确认更改
4. **空值处理**：people, project, links 未提取到时传空值（如 `"people": []`）
5. **摘要生成**：从 content 提取关键信息，生成 ≤100 字的 abstract

---

## Output Format

```json
{
  "success": true|false,
  "data": { ... },
  "error": { "code": "E0000", "message": "...", "recovery_strategy": "..." }
}
```

错误码详见 [ERROR_CODES.md](references/ERROR_CODES.md)。

---

## Related Documentation

| 文档 | 用途 |
|------|------|
| **[INSTRUCTIONS.md](docs/INSTRUCTIONS.md)** | Agent执行指令、完整工作流、工具参数 |
| [HANDBOOK.md](docs/HANDBOOK.md) | 项目愿景、架构设计、核心原则 |
| [API.md](docs/API.md) | 工具 API 接口详细文档 |
| [SCHEDULE.md](references/schedule/SCHEDULE.md) | 定时任务配置（日报/周报/月报） |
| [WEATHER_FLOW.md](references/WEATHER_FLOW.md) | 天气处理流程 |
| [ERROR_CODES.md](references/ERROR_CODES.md) | 错误码定义 |

---

## Examples

**记录工作日志**：
```
用户：记录一下今天完成了搜索功能优化

Agent：
1. 解析：title="搜索功能优化", topic=["work"], abstract="完成搜索功能优化工作"
2. 调用 write_journal（自动填充地点="Chongqing, China"、查询天气）
3. 检查 needs_confirmation=true
4. 展示：日志已保存。地点：Chongqing, China；天气：Sunny。是否正确？
```

**搜索历史**：
```
用户：查找去年关于重构的日志

Agent：
调用：search_journals --query "重构" --date-from 2025-01-01 --date-to 2025-12-31
返回：找到 5 篇相关日志
```

**完整工作流示例**: 详见 [INSTRUCTIONS.md](docs/INSTRUCTIONS.md#核心工作流)