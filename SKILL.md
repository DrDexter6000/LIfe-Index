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

用户输入 `/life-index` 时，直接进入 Life Index 技能模式，等待后续指令。

## 语义触发（隐式）

当用户输入包含以下意图时，自动触发对应功能：

| 意图 | 触发词示例 |
|:---:|:---|
| 记录日志 | "记日志"、"记录一下"、"写日记"、"记下来"、"写一下今天" |
| 搜索日志 | "查找日志"、"搜索记录"、"找一下关于...的日记" |
| 编辑日志 | "修改日志"、"补充日记"、"更新记录" |
| 生成摘要 | "生成摘要"、"月度总结"、"年度总结"、"查看总结" |

# When to Use

1. **记录日志**：当用户说"记录一下今天..."、"记日志"、"写日记..."、"记下来..."时，使用 write-journal
2. **搜索日志**：当用户说"查找关于...的日志"、"去年春天的记录"、"搜索项目相关的日记"时，使用 search-journals
3. **编辑日志**：当用户说"修改昨天的日志"、"补充一下那篇日记"时，使用 edit-journal
4. **查询天气**：当需要补全日志天气信息时，自动调用 query-weather
5. **生成摘要**：当用户说"生成月度摘要"、"查看年度总结"时，使用 generate-abstract

# Weather Handling Rules

## 三层天气处理机制

write-journal 工具内置完整天气处理逻辑，Agent 只需调用工具，无需额外处理：

### 第一层：用户提及为准
- 如果用户在日志内容中提及地点和天气，write-journal 会自动提取并使用
- 如果用户明确提供了 location 和 weather 字段，直接使用用户提供的值

### 第二层：自动填充（工具内部处理）
- **地点默认值**：如果用户未提供地点，自动使用 "重庆，中国"
- **地点规范化**：如果用户只提供城市名（如"重庆"），自动推断国家为"中国"
- **天气自动查询**：如果未提供天气，工具自动调用 query-weather 获取

### 第三层：写入后确认
- write-journal 返回结果中包含 `needs_confirmation: true`
- Agent 应展示 `confirmation_message` 给用户，询问地点和天气是否正确
- 如果用户需要修改，使用 edit-journal 工具更新日志文件

## 用户修改场景处理

| 用户反馈 | Agent 操作 |
|:---|:---|
| 用户补充了地点和天气 | 调用 edit-journal 更新 location 和 weather 字段 |
| 用户只补充了地点 | 调用 edit-journal 更新 location，工具会自动重新查询天气 |
| 用户只补充了城市（如"北京"） | 调用 edit-journal，工具会自动推断为"北京，中国"并查询天气 |

# Required Inputs

## write-journal

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
- **attachments** (array, optional): 附件列表，每项包含 source_path 和 description

## search-journals

- **query** (string, optional): 搜索关键词
- **topic** (string, optional): 按主题过滤
- **project** (string, optional): 按项目过滤
- **tags** (string, optional): 按标签过滤（逗号分隔）
- **date_from** (string, optional): 起始日期 (YYYY-MM-DD)
- **date_to** (string, optional): 结束日期 (YYYY-MM-DD)
- **level** (integer, optional, default: 3): 搜索层级: 1=索引, 2=元数据, 3=全文
- **semantic** (boolean, optional, default: false): 是否启用语义搜索

## edit-journal

- **journal_path** (string, required): 日志文件路径
- **updates** (object, optional): 要更新的 frontmatter 字段
- **append_content** (string, optional): 追加到正文的内容

## query-weather

- **location** (string, optional): 地点名称（如 "Lagos"）
- **lat** (number, optional): 纬度
- **lon** (number, optional): 经度
- **date** (string, optional, default: "today"): 日期 (YYYY-MM-DD)

## generate-abstract

- **month** (string, optional): 生成月度摘要，格式 YYYY-MM（如 "2026-03"）
- **year** (integer, optional): 生成年度摘要，格式 YYYY（如 2026）
- **all-months** (boolean, optional): 与 year 一起使用，批量生成全年各月摘要
- **dry-run** (boolean, optional): 预览模式，不实际写入文件

# Step-by-Step Workflow

## 记录日志流程

1. **语义解析**：提取用户输入中的关键信息（日期、地点、主题、内容）
2. **确认地点天气**：如未提供，询问地点并调用 query-weather 获取天气
3. **构建元数据**：整理 title, content, date, location, weather, mood, tags 等
4. **确认写入**：展示预览，用户确认后调用 write-journal
5. **返回结果**：告知日志保存路径和索引更新情况

## 搜索日志流程

1. **解析查询意图**：识别时间范围、主题、关键词等过滤条件
2. **选择搜索层级**：
   - 有明确 topic/project/tag → Level 1（索引层，最快）
   - 有时间/地点等元数据 → Level 2（元数据层）
   - 需要全文检索 → Level 3（内容层）
3. **执行搜索**：调用 search-journals 获取结果
4. **结果呈现**：按相关性排序，展示标题、日期、摘要

## 编辑日志流程

1. **定位日志**：根据日期或标题找到目标日志文件
2. **确认修改**：展示当前内容，明确修改范围
3. **执行编辑**：调用 edit-journal 更新 frontmatter 或正文
4. **索引同步**：如涉及 topic/project/tags 变更，自动重建索引

## 生成摘要流程

1. **确定类型**：询问用户需要月度摘要还是年度摘要
2. **确定时间**：获取目标年份/月份
3. **执行生成**：调用 generate-abstract 生成摘要文件
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
│       └── monthly_abstract.md   # 月度摘要
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

# Installation

```bash
# 通过 ClawHub 安装
clawhub install life-index

# 或通过 npx 临时使用
npx clawhub@latest install life-index

# 或通过 GitHub URL 安装
# 在 OpenClaw 对话中：请帮我安装这个 skill，GitHub 链接是：https://github.com/your-username/life-index-skill
```

# Examples

## 示例 1：记录工作日志

**用户**：记录一下今天完成了 Life Index 的搜索功能优化

**Agent**：
1. 解析：title="完成搜索功能优化", topic=["work"], project="Life-Index"
2. 确认：地点是 Lagos 吗？
3. 获取天气（自动）
4. 调用 write-journal
5. 返回：日志已保存至 Journals/2026/03/life-index_2026-03-07_001.md

## 示例 2：搜索历史日志

**用户**：查找去年关于重构的日志

**Agent**：
1. 解析：query="重构", date_from="2025-01-01", date_to="2025-12-31"
2. 调用 search-journals --query "重构" --date-from 2025-01-01 --date-to 2025-12-31
3. 返回：找到 5 篇相关日志，按日期排序展示

## 示例 3：补充日志内容

**用户**：给昨天的日志补充一下测试结果

**Agent**：
1. 定位：找到昨天的日志文件
2. 确认：追加内容"测试结果显示搜索速度提升 40%"
3. 调用 edit-journal --append-content "..."
4. 返回：日志已更新

## 示例 4：生成月度摘要

**用户**：生成上个月的摘要

**Agent**：
1. 确定时间：2026年2月
2. 调用 generate-abstract --month 2026-02
3. 返回：月度摘要已保存至 Journals/2026/02/monthly_abstract.md

## 示例 5：生成年摘要

**用户**：查看今年的年度总结

**Agent**：
1. 确定时间：2026年
2. 调用 generate-abstract --year 2026
3. 返回：年度摘要已保存至 Journals/2026/yearly_abstract.md
