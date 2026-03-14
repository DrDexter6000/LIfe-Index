# Life Index Agent 指令

> **本文档职责**: Agent 可执行指令详细参考
> **适用对象**: 具备文件操作能力的 AI Agent（Claude、OpenClaw 等）
> **版本/状态**: 详见 [README.md](./README.md)
>
> **相关文档**: [架构→HANDBOOK.md](./HANDBOOK.md) | [定时任务→SCHEDULE.md](../references/schedule/SCHEDULE.md) | [变更历史→CHANGELOG.md](./CHANGELOG.md)
---

## 前置检查

**执行任何操作前，确认以下事项：**

1. **当前任务**是否与 Life Index 直接相关？
   - ✅ 正确：记录/搜索用户日志、维护索引、生成摘要
   - ❌ 错误：优化 Agent 自身记忆系统、配置平台级功能

2. **如发现不匹配**：立即停止操作，向用户说明情况，请求澄清。

---

## 意图识别

### 记录日志意图

**触发条件**（满足任一）：
- 关键词: "/log"、"记一下"、"记录一下"、"写日记"
- 语义模式: "今天..."、"刚才..."、"我觉得..."、"我发现..."
- 任何带有回顾、反思、事件描述的陈述

### 搜索日志意图

**触发条件**（满足任一）：
- 关键词: "搜索..."、"查找..."、"帮我找..."
- 语义模式: "之前写的..."、"回顾一下..."、"关于...的日志"

### 编辑日志意图

**触发条件**：
- 关键词: "修改..."、"补充..."、"更新昨天的日志"

### 生成摘要意图

**触发条件**：
- 关键词: "月度摘要"、"年度总结"、"生成摘要"

---

## 分类体系

Topic分类、Project命名、Tags规范详见 [API.md](./API.md#分类体系)。

---

## 工具接口

工具详细参数和返回值见 [API.md](./API.md)。

### write_journal.py

写入日志，自动更新索引和月度摘要。

**关键要点**：
- 必须包含所有元数据字段（即使为空值）
- content 必须100%原样保留
- abstract 由 Agent 从 content 提取生成（≤100字） |

**调用示例**:
```bash
python tools/write_journal.py --data '{"title":"...","content":"...","date":"2026-03-07","topic":["work"],"abstract":"...","mood":[],"people":[],"project":"","tags":[],"links":[]}'
```

### search_journals.py

分层级检索日志（L1索引→L2元数据→L3全文）。

| 参数 | 说明 |
|------|------|
| `--query` | 全文搜索关键词 |
| `--topic` | 按主题过滤 |
| `--project` | 按项目过滤 |
| `--tags` | 按标签过滤（逗号分隔） |
| `--date-from` | 起始日期 (YYYY-MM-DD) |
| `--date-to` | 结束日期 (YYYY-MM-DD) |
| `--level` | 搜索层级: 1=索引, 2=元数据, 3=全文（默认3） |
| `--use-index` | 使用 FTS 索引加速 |
| `--semantic` | 启用语义搜索（混合 BM25 + 向量相似度） |
| `--limit` | 返回结果数 |

**调用示例**:
```bash
python tools/search_journals.py --topic work --project Life-Index --date-from 2026-01-01 --limit 10
```

### edit_journal.py

编辑已有日志。

| 字段 | 必填 | 说明 |
|------|------|------|
| `journal_path` | ✅ | 日志文件路径 |
| `--set-location` | ❌ | 更新地点 |
| `--set-weather` | ❌ | 更新天气 |
| `--set-topic` | ❌ | 更新主题 |
| `--append-content` | ❌ | 追加到正文的内容 |

**调用示例**:
```bash
python tools/edit_journal.py --journal "Journals/2026/03/life-index_2026-03-07_001.md" --append-content "补充内容"
```

### query_weather.py

查询天气（历史/实时）。

| 字段 | 必填 | 说明 |
|------|------|------|
| `--location` | ✅ | 地点名称（如 "Lagos,Nigeria"） |
| `--date` | ❌ | 日期 (YYYY-MM-DD，默认当天) |

**调用示例**:
```bash
python tools/query_weather.py --location "Lagos,Nigeria"
```

### generate_abstract.py

生成月度/年度摘要。

| 参数 | 说明 |
|------|------|
| `--month` | 生成月度摘要，格式 YYYY-MM |
| `--year` | 生成年度摘要，格式 YYYY |
| `--all-months` | 与 --year 一起使用，批量生成全年各月摘要 |

**调用示例**:
```bash
python tools/generate_abstract.py --month 2026-03
python tools/generate_abstract.py --year 2026
```

### build_index.py

构建 FTS 和向量索引。

| 参数 | 说明 |
|------|------|
| 默认 | 增量更新索引 |
| `--rebuild` | 全量重建索引 |
| `--stats` | 显示索引统计信息 |

---

## 核心工作流

### 工作流1: 记录日志

#### 元数据完整性规则

**所有日志必须包含完整的元数据字段，即使值为空。**

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

#### 天气处理三层机制

详见 [WEATHER_FLOW.md](../references/WEATHER_FLOW.md)

| 层级 | 场景 | 处理方式 |
|:----:|------|---------|
| 1 | 用户提供地点+天气 | 直接使用 |
| 2 | 用户未提供 | 自动填充默认地点 "Chongqing, China" + 查询天气 |
| 3 | 写入后 | **必须**确认地点和天气，展示 `confirmation_message` |
| 4 | API 失败 | Agent 使用网络搜索 Fallback（Agent-First 原则） |

**常识映射表**（地点补全）：
| 用户输入 | 补全结果 |
|---------|---------|
| Lagos | Lagos, Nigeria |
| 北京 | Beijing, China |
| Tokyo | Tokyo, Japan |
| Shanghai | Shanghai, China |
| New York | New York, USA |
| London | London, UK |

#### 工作流步骤

1. **语义解析**：从用户输入提取 title/content/date/topic
2. **提取元数据**：从 content 中识别 mood、people、tags、project
3. **生成摘要**：从 content 中提取关键信息，生成 ≤100 字的 abstract
4. **处理地点和天气**：
   - 用户提供 → 直接使用
   - 用户未提供 → 自动填充默认地点 + 查询天气
5. **调用工具**：`write_journal`（**必须包含所有元数据字段**）
   - **附件自动处理**：工具自动检测 content 中的本地文件路径，复制到 `attachments/YYYY/MM/`
6. **检查 `needs_confirmation`**
7. **展示确认信息**：询问用户确认地点和天气
8. **天气查询失败时**：使用网络搜索 Fallback

### 工作流2: 检索日志

#### 四层搜索架构

| 层级 | 名称 | 适用场景 | 性能 |
|:----:|------|---------|------|
| L1 | 索引层 (by-topic/) | 有明确 topic/project/tag | < 10ms |
| L2 | 元数据层 (frontmatter) | 有时间/地点/天气等结构化过滤 | < 50ms |
| L3 | 全文层 (FTS5) | 需要全文检索（默认） | < 50ms |
| L4 | 语义层 (向量) | 需要语义匹配 | 可选启用 |

#### 工作流步骤

1. **解析查询意图**：识别 time_range/metadata/fulltext/compound
2. **选择搜索层级**：
   - Level 1：有明确 topic/project/tag
   - Level 2：有时间/地点等元数据
   - Level 3：需要全文检索（默认）
   - Level 4：需要语义匹配（`--semantic`）
3. **执行搜索**：`search_journals`
4. **呈现结果**：展示匹配的日志列表

#### 搜索参数速查

```bash
# 基础搜索
python -m tools.search_journals --query "关键词" --level 3

# 按元数据过滤
python -m tools.search_journals --topic work --project Life-Index --date-from 2026-01-01

# 语义搜索（需安装 sentence-transformers）
python -m tools.search_journals --query "学习笔记" --semantic
```

### 工作流3: 编辑日志

#### 工作流步骤

1. **定位日志**：根据日期或标题找到目标文件
2. **确认修改**：展示当前内容，明确修改范围
3. **执行编辑**：`edit_journal`
4. **如修改地点**：需先调用 `query_weather` 获取新天气

#### 编辑参数速查

```bash
# 更新地点（需要先查询天气）
python -m tools.query_weather --location "Beijing,China"
python -m tools.edit_journal --journal "Journals/2026/03/life-index_2026-03-14_001.md" --set-location "Beijing, China" --set-weather "晴天 25°C"

# 追加内容
python -m tools.edit_journal --journal "Journals/2026/03/life-index_2026-03-14_001.md" --append-content "后续补充的内容..."

# 更新主题
python -m tools.edit_journal --journal "Journals/2026/03/life-index_2026-03-14_001.md" --set-topic "learn"
```

### 工作流4: 生成摘要

#### 工作流步骤

1. **确定类型**：月度摘要或年度摘要
2. **执行生成**：`generate_abstract`
3. **返回结果**：告知文件路径和统计信息

#### 摘要参数速查

```bash
# 月度摘要
python -m tools.generate_abstract --month 2026-03
# 输出: Journals/2026/03/monthly_report_2026-03.md

# 年度摘要
python -m tools.generate_abstract --year 2026
# 输出: Journals/2026/yearly_report_2026.md

# 批量生成全年月度摘要
python -m tools.generate_abstract --year 2026 --all-months
```

---

## 定时任务

Life Index 支持定时生成日报、周报、月报、年报，以及向量索引自动维护。

详见：[SCHEDULE.md](../references/schedule/SCHEDULE.md)
---

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| 文件不存在 | 返回明确的错误信息，建议检查路径 |
| 网络失败 | 天气查询失败时允许日志继续写入（天气字段留空） |
| 权限不足 | 提示用户检查目录权限 |
| 格式错误 | 返回具体的验证错误信息 |
| 附件复制失败 | 记录原始路径，在正文中标注 |
| 索引更新失败 | 主流程继续，记录警告待后续修复 |

---

## 禁止事项

❌ **不要一次性问多个问题**
```
错误: "地点在哪？天气如何？心情怎么样？"
正确: "地点和天气是？"（单次确认）
```

❌ **不要假设用户知道系统内部概念**
```
错误: "已更新 by-topic 索引"
正确: "已帮您归类到工作相关"
```

❌ **不要在工具调用失败后静默忽略**
```
错误: （天气查询失败，直接跳过）
正确: "天气查询暂时不可用，请告诉我今天的天气"
```

---

## 目录结构

```
~/Documents/Life-Index/           # 用户数据目录
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

---

**文档结束**