# Life Index Agent 指令

> **本文档职责**: Agent 可执行指令详细参考
> **适用对象**: 具备文件操作能力的 AI Agent（Claude、OpenClaw 等）
> **版本/状态**: 详见 [README.md](./README.md)
>
> **相关文档**: [架构→HANDBOOK.md](./HANDBOOK.md) | [定时任务→SCHEDULE.md](./SCHEDULE.md) | [变更历史→CHANGELOG.md](./CHANGELOG.md)

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

### Topic（必填，预定义7类）

| Topic | 含义 | 示例场景 |
|-------|------|---------|
| `work` | 工作/职业 | 项目开发、会议、任务完成 |
| `learn` | 学习/成长 | 读书笔记、课程学习、技能提升 |
| `health` | 健康/身体 | 运动、体检、疾病记录 |
| `relation` | 关系/社交 | 家人互动、朋友聚会 |
| `think` | 思考/反思 | 人生感悟、决策分析 |
| `create` | 创作/产出 | 写文章、设计稿、作品 |
| `life` | 生活/日常 | 购物、娱乐、日常琐事 |

### Project（选填）

动态项目名称，驼峰命名，如 `Life-Index`、`WebGame`。

### Tags（选填）

自由标签，如 `#重构`、`#会议`、`#灵感`。

---

## 工具接口

### write_journal.py

写入日志，自动更新索引和月度摘要。

| 字段 | 必填 | 说明 |
|------|------|------|
| `title` | ✅ | 日志标题（≤20字） |
| `content` | ✅ | 日志正文内容 |
| `date` | ✅ | 日期（YYYY-MM-DD，默认当天） |
| `topic` | ✅ | 主题分类（预定义7类，必填） |
| `location` | ❌ | 地点（如 "Lagos, Nigeria"） |
| `weather` | ❌ | 天气描述 |
| `mood` | ❌ | 心情标签数组 |
| `people` | ❌ | 相关人物数组 |
| `project` | ❌ | 关联项目 |
| `tags` | ❌ | 标签数组 |
| `abstract` | ❌ | 100字内摘要（**Agent生成**，从content提取关键信息） |
| `attachments` | ❌ | 附件列表，每项包含 source_path 和 description |

**调用示例**:
```bash
python tools/write_journal.py --data '{"title":"...","content":"...","date":"2026-03-07","topic":"work"}'
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

1. **语义解析**：从用户输入提取 content/mood/topic/project
2. **确认地点和天气**：如未提供，询问用户
3. **分支处理**：
   - 用户提供完整地址+天气 → 直接使用
   - 仅提供地点 → 常识补全国家 → 调用 query_weather
   - 均未提供 → 默认 Lagos, Nigeria → 调用 query_weather
4. **调用工具**：write_journal.py
5. **向用户确认**

**常识映射表**：
| 用户输入 | 补全结果 |
|---------|---------|
| Lagos | Lagos, Nigeria |
| 北京 | Beijing, China |
| Tokyo | Tokyo, Japan |
| Shanghai | Shanghai, China |
| New York | New York, USA |
| London | London, UK |

### 工作流2: 检索日志

1. **解析查询意图**：识别 time_range/metadata/fulltext/compound
2. **选择搜索层级**：
   - Level 1：有明确 topic/project/tag
   - Level 2：有时间/地点等元数据
   - Level 3：需要全文检索（默认）
3. **执行搜索**：search_journals.py
4. **呈现结果**

### 工作流3: 编辑日志

1. **定位日志**：根据日期或标题找到目标文件
2. **确认修改**：展示当前内容，明确修改范围
3. **执行编辑**：edit_journal.py

### 工作流4: 生成摘要

1. **确定类型**：月度摘要或年度摘要
2. **执行生成**：generate_abstract.py
3. **返回结果**：告知文件路径和统计信息

---

## 定时任务

Life Index 支持定时生成日报、周报、月报、年报，以及向量索引自动维护。

详见：[SCHEDULE.md](./SCHEDULE.md)

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