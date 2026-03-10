---
name: life-index
description: "个人日志管理系统。当用户说'/life-index'、'记日志'、'写日记'、'write journal'、'daily log'时立即使用。自动记录日期、天气、心情标签，支持搜索历史日志和生成月度摘要。"
license: Apache-2.0
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
---

# Triggers

## 命令触发（显式）

用户输入 `/life-index` 时，直接进入 Life Index 技能模式。

## 语义触发（隐式）

当用户输入包含以下意图时，自动触发对应功能：

| 意图 | 触发词示例 |
|:---:|:---|
| 记录日志 | "记日志"、"记录一下"、"写日记"、"记下来"、"写一下今天" |
| 搜索日志 | "查找日志"、"搜索记录"、"找一下关于...的日记" |
| 编辑日志 | "修改日志"、"补充日记"、"更新记录" |
| 生成摘要 | "生成摘要"、"月度总结"、"年度总结"、"查看总结" |

# When to Use

1. **记录日志**：当用户说"记录一下今天..."、"记日志"、"写日记..."、"记下来..."时，使用 `tools/write_journal.py`
2. **搜索日志**：当用户说"查找关于...的日志"、"去年春天的记录"、"搜索项目相关的日记"时，使用 `tools/search_journals.py`
3. **编辑日志**：当用户说"修改昨天的日志"、"补充一下那篇日记"时，使用 `tools/edit_journal.py`
4. **生成摘要**：当用户说"生成月度摘要"、"查看年度总结"时，使用 `tools/generate_abstract.py`

# Tool Invocation Guide

## 核心原则

**所有功能必须通过 Bash 调用 Python 工具实现，禁止手动操作文件。**

| 禁止行为 | 正确做法 |
|:---|:---|
| 使用 `Write` 工具直接创建日志文件 | 调用 `python tools/write_journal.py` |
| **通过 Python import 直接调用工具函数** | **必须通过 Bash CLI 调用** |
| 手动构建 frontmatter 和 content | 传递 JSON 数据给工具处理 |
| 手动编号文件名（如 `_001.md`） | 工具自动检测并分配序列号 |
| 手动查询天气 API | 工具内置自动天气查询 |
| 手动复制附件文件 | 工具自动检测并处理附件 |

**为什么必须通过 Bash CLI 调用？**
- CLI 接口保证参数格式化和校验一致性
- Python import 绕过工具的格式化逻辑（如 date 字段引号问题）
- Bash 调用返回标准 JSON，便于 Agent 解析和确认

## 工具调用方式

所有工具位于 `tools/` 目录，通过 **Bash** 调用：

### tools/write_journal.py

```bash
python tools/write_journal.py --data '{"title":"...","content":"...","date":"2026-03-09"}'
```

**关键参数**：
- `content`: 用户原始输入，**禁止预处理**，原封不动传递
- `date`: ISO 8601 格式（如 `2026-03-09`）
- `location`: 可选，如未提供工具自动使用默认值
- `weather`: 可选，如未提供工具自动查询

**工具自动处理**：
- 自动分配序列号（`_001`, `_002`...）
- 自动查询天气（如未提供）
- 自动从 content 提取文件路径作为附件
- 自动复制附件到 `~/Documents/Life-Index/Attachments/`
- 自动更新主题/项目/标签索引
- 自动更新月度摘要

### tools/search_journals.py

```bash
python tools/search_journals.py --query "关键词" --topic "work" --level 3
```

### tools/edit_journal.py

```bash
python tools/edit_journal.py --journal "Journals/2026/03/life-index_2026-03-09_001.md" --set-weather "晴天"
```

### tools/generate_abstract.py

```bash
# 月度摘要
python tools/generate_abstract.py --month 2026-03

# 年度摘要
python tools/generate_abstract.py --year 2026
```

# Weather Handling Rules

## 三层天气处理机制

`tools/write_journal.py` 内置完整天气处理逻辑，Agent 只需调用工具，无需额外处理：

### 第一层：用户提及为准
- 如果用户明确提供了 location 和 weather 字段，直接使用用户提供的值

### 第二层：自动填充（工具内部处理）
- **地点默认值**：如果用户未提供地点，自动使用 "重庆，中国"
- **地点规范化**：如果用户只提供城市名（如"重庆"），自动推断国家名（如"中国"）
- **天气自动查询**：如果未提供天气，工具内部自动调用 `tools/query_weather.py` 获取

### 第三层：写入后确认（强制）

`tools/write_journal.py` 返回 JSON 后，Agent **必须执行**：

1. **检查 `needs_confirmation` 字段**
2. **如果为 `true`**：
   - **必须**展示 `confirmation_message` 给用户
   - **必须**询问："地点和天气是否正确？"
   - 等待用户回复
3. **如果用户需要修改**：
   - 调用 `tools/edit_journal.py` 更新 location/weather

**禁止行为**：
- 看到 `success: true` 就直接结束
- 忽略 `needs_confirmation` 字段
- 不展示确认信息就结束对话

## 用户修改场景处理

**重要**：`tools/edit_journal.py` **不会自动查询天气**，Agent 需要手动调用 `tools/query_weather.py`。

| 用户反馈 | Agent 操作 |
|:---|:---|
| 用户补充了地点和天气 | 调用 `tools/edit_journal.py --set-location "..." --set-weather "..."` |
| 用户只补充了地点 | 1. 调用 `tools/query_weather.py --location "..."` 获取天气<br>2. 调用 `tools/edit_journal.py --set-location "..." --set-weather "..."` |
| 用户只补充了城市（如"北京"） | 1. 推断为"北京，中国"<br>2. 调用 `tools/query_weather.py --location "Beijing, China"`<br>3. 调用 `tools/edit_journal.py --set-location "..." --set-weather "..."` |

**错误示例**（不要这样做）：
```
# 只传 location，期望工具自动查询天气
python tools/edit_journal.py --set-location "Lagos"
# ❌ 结果：weather 字段不会更新
```

**正确示例**：
```bash
# Step 1: 查询天气
python tools/query_weather.py --location "Lagos, Nigeria"

# Step 2: 同时更新地点和天气
python tools/edit_journal.py --journal "..." --set-location "Lagos, Nigeria" --set-weather "阵雨 33.3°C/28.5°C"
```

# Content Preservation Rule

## 正文内容保留原则（关键）

**必须 100% 保留用户原始输入格式，禁止任何"优化"或改造：**

1. **段落结构**：不得修改用户的段落划分和空行
2. **Markdown 标题**：保留用户使用的 `#` `##` `###` 等标题层级
3. **列表格式**：保留用户原始的列表标记（`1.` `2.` `3.` 或 `-` `*`）
4. **序号标记**：保留用户使用的 `1、` `2、` `3、` 等中文序号
5. **缩进和空格**：保留用户内容中的缩进和特殊空格
6. **直接传递**：将用户输入的原始文本直接作为 `content` 字段值，不做任何预处理

**错误示例**（不要这样做）：
- 用户输入：`"1、完成A任务 2、完成B任务"` → Agent 改成 `"1. 完成A任务\n2. 完成B任务"` ❌
- 用户输入：`"## 今日计划\n\n内容"` → Agent 去掉标题只保留 `"内容"` ❌

**正确示例**：
- 用户输入什么，`content` 字段就原封不动传递什么 ✓

# Required Inputs

## tools/write_journal.py

- **title** (string, required): 日志标题（≤20字）
- **content** (string, required): 日志正文内容
- **date** (string, required): 日期（ISO 8601格式，如 2026-03-07）
- **location** (string, optional): 地点（如 "Lagos, Nigeria"）
- **weather** (string, optional): 天气描述
- **mood** (array, optional): 心情标签数组（如 ["专注", "充实"]）
- **people** (array, optional): 相关人物数组
- **topic** (array, optional): 主题分类数组（如 ["work", "life"]）
- **project** (string, optional): 关联项目
- **tags** (array, optional): 标签数组
- **abstract** (string, optional): 100字内摘要
- **links** (array, optional): 相关链接数组
- **attachments** (array, optional): 附件列表，每项包含 source_path 和 description

## Attachment Auto-Detection

**附件自动检测规则**：

`tools/write_journal.py` 会自动从 `content` 字段中提取本地文件路径并作为附件处理：

1. **自动检测范围**：
   - Windows 绝对路径：`C:\Users\...\file.txt` 或 `C:/Users/.../file.txt`
   - 网络路径：`\\server\share\file.txt` 或 `//server/share/file.txt`

2. **处理流程**：
   - 工具自动扫描 content 中的文件路径
   - 验证文件是否存在
   - 自动复制到 `~/Documents/Life-Index/Attachments/YYYY/MM/` 目录
   - 在 frontmatter 的 `attachments` 字段记录相对路径
   - 在正文末尾添加 Attachments 章节

3. **Agent 职责**：
   - **无需手动提取**：Agent 不需要在调用工具前手动提取文件路径
   - **无需重复传递**：自动检测到的附件不需要再通过 `attachments` 参数传递
   - **可选显式传递**：如果用户明确提到"附件是..."，可以显式传入 `attachments` 参数

4. **跨平台路径映射**：
   - 如果用户在 Windows 环境记录日志，但在 Linux/macOS 环境运行 OpenClaw
   - 可在 `tools/lib/config.py` 中配置 `PATH_MAPPINGS`
   - 示例：`{"C:\\Users\\17865\\Downloads": "/home/dexter/Downloads"}`
   - 工具会自动将 Windows 路径转换为当前平台可访问的路径

5. **示例**：
   ```
   用户：今天完成了设计稿，文件在 C:\Users\17865\Downloads\design_v2.png

   Agent：直接调用 tools/write_journal.py，content 包含原文
   → 工具自动检测并复制 design_v2.png 作为附件
   ```

## tools/search_journals.py

- **query** (string, optional): 搜索关键词（支持 `--query` 或 `--keywords`）
- **topic** (string, optional): 按主题过滤
- **project** (string, optional): 按项目过滤
- **tags** (string, optional): 按标签过滤（逗号分隔）
- **date_from** (string, optional): 起始日期 (YYYY-MM-DD)
- **date_to** (string, optional): 结束日期 (YYYY-MM-DD)
- **location** (string, optional): 按地点过滤
- **weather** (string, optional): 按天气过滤
- **mood** (string, optional): 按心情过滤（逗号分隔多个）
- **people** (string, optional): 按人物过滤（逗号分隔多个）
- **level** (integer, optional, default: 3): 搜索层级: 1=索引, 2=元数据, 3=全文
- **use-index** (flag, optional): 使用 FTS 索引加速全文搜索（需预先运行 build_index.py）
- **semantic** (flag, optional): 启用语义搜索（混合 BM25 + 向量相似度排序）
- **semantic-weight** (float, optional, default: 0.4): 语义搜索权重（0-1，需配合 `--semantic`）
- **fts-weight** (float, optional, default: 0.6): FTS 搜索权重（0-1，需配合 `--semantic`）
- **limit** (integer, optional): 返回结果数量限制

## tools/edit_journal.py

- **journal** (string, required): 日志文件路径（相对或绝对路径）
- **set-title** (string, optional): 设置标题
- **set-date** (string, optional): 设置日期
- **set-location** (string, optional): 设置地点
- **set-weather** (string, optional): 设置天气
- **set-mood** (string, optional): 设置心情（逗号分隔多个）
- **set-people** (string, optional): 设置人物（逗号分隔多个）
- **set-tags** (string, optional): 设置标签（逗号分隔多个）
- **set-project** (string, optional): 设置项目
- **set-topic** (string, optional): 设置主题（逗号分隔多个）
- **set-abstract** (string, optional): 设置摘要
- **append-content** (string, optional): 追加内容到正文末尾
- **replace-content** (string, optional): 替换整个正文内容（保留 frontmatter）
- **dry-run** (flag, optional): 模拟运行，不实际写入文件

## tools/query_weather.py（内部工具，无需直接调用）

- **location** (string, optional): 地点名称（如 "Lagos"）
- **lat** (number, optional): 纬度
- **lon** (number, optional): 经度
- **date** (string, optional, default: "today"): 日期 (YYYY-MM-DD)

## tools/generate_abstract.py

- **month** (string, optional): 生成月度摘要，格式 YYYY-MM（如 "2026-03"）
- **year** (integer, optional): 生成年度摘要，格式 YYYY（如 2026）
- **all-months** (boolean, optional): 与 year 一起使用，批量生成全年各月摘要
- **dry-run** (boolean, optional): 预览模式，不实际写入文件

# Step-by-Step Workflow

## 记录日志流程

1. **语义解析**：提取用户输入中的关键信息（日期、地点、主题、内容）
2. **构建元数据**：整理 title, content, date, mood, tags 等（location/weather 由工具自动处理）
3. **调用工具**：`python tools/write_journal.py --data '{...}'`
4. **检查返回值**：
   - 解析 JSON 返回结果
   - 检查 `needs_confirmation` 字段
   - **必须**展示 `confirmation_message` 给用户
5. **等待用户确认**：询问地点/天气是否正确，如有修改需求则调用 `tools/edit_journal.py`

## 搜索日志流程

1. **解析查询意图**：识别时间范围、主题、关键词等过滤条件
2. **选择搜索层级**：
   - 有明确 topic/project/tag → Level 1（索引层，最快）
   - 有时间/地点等元数据 → Level 2（元数据层）
   - 需要全文检索 → Level 3（内容层）
3. **执行搜索**：`python tools/search_journals.py ...`
4. **结果呈现**：按相关性排序，展示标题、日期、摘要

## 编辑日志流程

1. **定位日志**：根据日期或标题找到目标日志文件
2. **确认修改**：展示当前内容，明确修改范围
3. **执行编辑**：`python tools/edit_journal.py ...`
4. **索引同步**：如涉及 topic/project/tags 变更，自动重建索引

## 生成摘要流程

1. **确定类型**：询问用户需要月度摘要还是年度摘要
2. **确定时间**：获取目标年份/月份
3. **执行生成**：`python tools/generate_abstract.py --month 2026-03` 或 `--year 2026`
4. **返回结果**：告知摘要文件路径和统计信息

# Output Format

所有工具返回 JSON 格式：

```json
{
  "success": true/false,
  "data": { ... },
  "error": "错误信息（如有）"
}
```

# Guardrails

- **永不删除文件**：编辑操作只修改内容，不删除日志文件
- **数据隔离**：所有数据存储在用户目录 `~/Documents/Life-Index/`，不污染 Skill 目录
- **最小权限**：仅请求必要的网络（天气 API）和文件系统权限
- **输入验证**：日期格式必须为 ISO 8601，路径必须经过安全检查
- **敏感信息**：不在日志中存储密码、密钥等敏感信息

# Error Handling

- **文件不存在**：返回明确的错误信息，建议检查路径
- **网络失败**：天气查询失败时允许日志继续写入（天气字段留空）
- **权限不足**：提示用户检查目录权限
- **格式错误**：返回具体的验证错误信息

# Directory Structure

```
~/Documents/Life-Index/           # 用户数据目录（运行时创建）
├── Journals/                     # 日志文件存储
│   └── YYYY/MM/                  # 按年月分层
│       ├── life-index_YYYY-MM-DD_XXX.md
│       └── monthly_report_YYYY-MM.md   # 月度报告
├── by-topic/                     # 主题索引
│   ├── 主题_work.md
│   ├── 项目_Life-Index.md
│   └── 标签_重构.md
└── attachments/                  # 附件存储
    └── YYYY/MM/
```

# Prerequisites

## 必需依赖

- **Python 3.11+**：核心工具运行环境

## 可选依赖

- **sentence-transformers**：用于语义搜索功能
  - 安装命令：`pip install sentence-transformers`
  - 或使用项目提供的 requirements.txt：`pip install -r tools/requirements.txt`

> **注意**：如未安装 sentence-transformers，语义搜索功能将自动跳过，全文搜索（FTS5）仍可正常使用。

# Examples

## 示例 1：记录工作日志

**用户**：记录一下今天完成了 Life Index 的搜索功能优化

**Agent**：
1. 解析：title="完成搜索功能优化", topic=["work"], project="Life-Index"
2. 调用：`python tools/write_journal.py --data '{...}'`
3. 工具自动填充地点/天气，返回确认信息
4. 返回：日志已保存至 Journals/2026/03/life-index_2026-03-07_001.md

## 示例 2：搜索历史日志

**用户**：查找去年关于重构的日志

**Agent**：
1. 解析：query="重构", date_from="2025-01-01", date_to="2025-12-31"
2. 调用：`python tools/search_journals.py --query "重构" --date-from 2025-01-01 --date-to 2025-12-31`
3. 返回：找到 5 篇相关日志，按日期排序展示

## 示例 3：补充日志内容

**用户**：给昨天的日志补充一下测试结果

**Agent**：
1. 定位：找到昨天的日志文件
2. 确认：追加内容"测试结果显示搜索速度提升 40%"
3. 调用：`python tools/edit_journal.py --journal "..." --append-content "..."`
4. 返回：日志已更新

## 示例 4：生成月度摘要

**用户**：生成上个月的摘要

**Agent**：
1. 确定时间：2026年2月
2. 调用：`python tools/generate_abstract.py --month 2026-02`
3. 返回：月度报告已保存至 Journals/2026/02/monthly_report_2026-02.md

## 示例 5：生成年摘要

**用户**：查看今年的年度总结

**Agent**：
1. 确定时间：2026年
2. 调用：`python tools/generate_abstract.py --year 2026`
3. 返回：年度报告已保存至 Journals/2026/yearly_report_2026.md
