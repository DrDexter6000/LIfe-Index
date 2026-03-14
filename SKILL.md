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

# Triggers

| 意图 | 触发词（中英文） |
|:---:|:---|
| 记录日志 | "记日志"、"记录一下"、"写日记"、"记下来"、"log this"、"record this"、"write journal"、"daily log" |
| 搜索日志 | "查找日志"、"搜索记录"、"找一下关于...的日记"、"search journal"、"find log" |
| 编辑日志 | "修改日志"、"补充日记"、"更新记录"、"edit journal"、"update log" |
| 生成摘要 | "生成摘要"、"月度总结"、"年度总结"、"generate summary"、"monthly report" |
| 生成日报 | "生成日报"、"今日总结"、"daily report" |
| 生成周报 | "生成周报"、"本周总结"、"weekly report" |
| 生成年报 | "生成年报"、"年度回顾"、"yearly report" |

# When to Use

1. **记录日志**：用户说"记录一下今天..."、"记日志..."、"log this..." → `write_journal.py`
2. **搜索日志**：用户说"查找关于...的日志"、"去年春天的记录"、"search for..." → `search_journals.py`
3. **编辑日志**：用户说"修改昨天的日志"、"补充一下那篇日记"、"edit..." → `edit_journal.py`
4. **生成摘要**：用户说"生成月度摘要"、"查看年度总结"、"generate summary..." → `generate_abstract.py`
5. **生成日报**：用户说"生成日报"、"今日总结"、"daily report" → 参考 [SCHEDULE.md](references/schedule/SCHEDULE.md) 日报场景
6. **生成周报**：用户说"生成周报"、"本周总结"、"weekly report" → 参考 [SCHEDULE.md](references/schedule/SCHEDULE.md) 周报场景
7. **生成年报**：用户说"生成年报"、"年度回顾"、"yearly report" → 参考 [SCHEDULE.md](references/schedule/SCHEDULE.md) 年报场景

# Tool Invocation

## ⚠️ 流程执行必读

**在执行任何操作前，请务必阅读以下工作流章节，确保正确执行。**

---

## 核心原则

**所有功能必须通过 Bash CLI 调用，禁止手动操作文件或 Python import 直接调用。**

```bash
# ✅ 正确 - 使用模块模式
python -m tools.write_journal --data '{"title":"...","content":"...","date":"2026-03-10"}'

# ❌ 错误 - 直接 import
from tools.write_journal import write_journal
```

## 工具调用示例

### write_journal

```bash
python -m tools.write_journal --data '{
  "title": "日志标题",
  "content": "用户原文（禁止预处理）",
  "date": "2026-03-10",
  "abstract": "100字内摘要（Agent生成）",
  "topic": ["work"]
}'

**工具自动处理**：默认地点、自动查询天气、自动序列号、自动更新索引。

**重要**：写入后必须检查 `needs_confirmation`，展示确认信息给用户。

### search_journals

```bash
python -m tools.search_journals --query "关键词" --topic work --level 3
```

### edit_journal

```bash
python -m tools.edit_journal --journal "Journals/2026/03/life-index_2026-03-10_001.md" --set-location "Beijing, China"
```

**注意**：`edit_journal` 不会自动查询天气，需先调用 `query_weather`。

### generate_abstract

```bash
python -m tools.generate_abstract --month 2026-03
python -m tools.generate_abstract --year 2026
```

### query_weather

```bash
python -m tools.query_weather --location "Lagos,Nigeria"
```

### build_index

```bash
python -m tools.build_index           # 增量更新
python -m tools.build_index --rebuild # 全量重建
```

### validate_data (开发工具)

```bash
python -m tools.dev.validate_data --json
```

### rebuild_indices (开发工具)

```bash
python -m tools.dev.rebuild_indices --dry-run
```

# Weather Handling

天气处理遵循三层机制，**详见 [WEATHER_FLOW.md](references/WEATHER_FLOW.md)**。

**核心要点**：
1. 用户提供 → 直接使用
2. 用户未提供 → 自动填充（默认地点 "Chongqing, China" + 查询天气）
3. 写入后 → **必须**确认地点和天气，展示 `confirmation_message`
4. API 失败 → Agent 使用网络搜索 Fallback（Agent-First 原则）

# Content Preservation

**必须 100% 保留用户原始输入**：

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

# Required Inputs

完整参数定义见 **[API.md](docs/API.md)**。

| 工具 | 必填参数 |
|------|----------|
| write_journal | title, content, date, abstract |

# Related Documentation

| 文档 | 用途 |
|------|------|
| [SCHEDULE.md](references/schedule/SCHEDULE.md) | 定时任务配置（日报/周报/月报/年报/索引维护） |
| [API.md](docs/API.md) | 工具 API 接口文档 |
| [WEATHER_FLOW.md](references/WEATHER_FLOW.md) | 天气处理流程 |
# Output Format

```json
{
  "success": true|false,
  "data": { ... },
  "error": { "code": "E0000", "message": "..." }
}
```

错误码详见 **[ERROR_CODES.md](references/ERROR_CODES.md)**。

# Workflow

## ⚠️ 记录日志（必读）

### 元数据完整性规则
**所有日志必须包含完整的元数据字段，即使值为空。**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | string | ✅ | 日志标题 |
| content | string | ✅ | 日志正文（100%原样保留） |
| date | string | ✅ | ISO 8601 日期时间 |
| location | string | ❌ | 地点（自动填充或用户提供） |
| weather | string | ❌ | 天气（自动查询或用户提供） |
| mood | array | ❌ | 心情标签（如["开心", "专注"]） |
| people | array | ❌ | 相关人物（如["张三", "李四"]） |
| tags | array | ❌ | 标签（从内容提取关键词） |
| project | string | ❌ | 关联项目（如"Life-Index"） |
| topic | array | ✅ | 主题分类（如["work", "life"]） |
| abstract | string | ✅ | ≤100字摘要（Agent生成） |
| links | array | ❌ | 相关链接（如["https://..."]） |

**Agent 职责**：
1. 从用户内容中**主动提取** mood、people、tags、project 信息
2. 即使未提取到，也要传递空值（如 `"mood": []`, `"project": ""`）
3. 确保调用 write_journal.py 时包含**所有字段**

### 工作流步骤

1. 解析用户输入（title, content, date, topic 等）
2. **提取元数据**：从 content 中识别 mood、people、tags、project
3. **生成摘要**：从 content 中提取关键信息，生成 ≤100 字的摘要
4. 调用 `write_journal.py`（**必须包含所有元数据字段**）
   - **附件自动处理**：工具自动检测 content 中的本地文件路径（如 `C:\Users\...\file.mp4`），复制到 `attachments/YYYY/MM/` 并在日志末尾添加引用
5. **检查 `needs_confirmation`**
6. 展示 `confirmation_message`，询问用户确认
7. **如果天气查询失败**：使用网络搜索 Fallback

## 搜索日志

1. 解析查询意图（时间、主题、关键词）
2. 选择搜索层级（L1 索引 / L2 元数据 / L3 全文）
3. 调用 `search_journals.py`
4. 展示结果

## 编辑日志

1. 定位目标日志文件
2. 确认修改内容
3. 调用 `edit_journal.py`
4. 如修改地点，需先调用 `query_weather.py`

# Guardrails

- **永不删除文件**：编辑只修改内容
- **数据隔离**：数据在 `~/Documents/Life-Index/`
- **内容保留**：100% 保留用户输入

# Directory Structure

```
~/Documents/Life-Index/
├── Journals/YYYY/MM/life-index_*.md
├── by-topic/主题_*.md
└── attachments/YYYY/MM/
```

# Examples

**记录工作日志**：
```
用户：记录一下今天完成了搜索功能优化

Agent：
1. 解析：title="搜索功能优化", topic=["work"]
2. 调用 write_journal.py
3. 返回：needs_confirmation=true, location="Chongqing, China", weather="Sunny"
4. 展示：日志已保存。地点：Chongqing, China；天气：Sunny。是否正确？
```

**搜索历史**：
```
用户：查找去年关于重构的日志

Agent：
调用：search_journals.py --query "重构" --date-from 2025-01-01 --date-to 2025-12-31
返回：找到 5 篇相关日志
```