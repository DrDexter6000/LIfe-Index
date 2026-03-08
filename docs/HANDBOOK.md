# Life Index Project Handbook

> **本文档职责**: 项目架构规范 SSOT，描述"是什么"和"为什么"
> **目标读者**: 人类（开发者、用户、协作者）
> **版本/状态**: 详见 [README.md](./README.md)
>
> **允许写入**: 设计原则、架构决策、工具职责定义、目录结构规范、术语定义
> **禁止写入**: 具体工作流步骤（去 AGENT.md）、变更历史（去 CHANGELOG.md）、临时开发状态（去 dev-progress.md）
>
> **相关文档**: [工作流→AGENT.md](./AGENT.md) | [变更历史→CHANGELOG.md](./CHANGELOG.md) | [当前任务→dev-progress.md](./dev-progress.md) | [里程碑→Roadmap](./Development-Roadmap-v1.md)

---

## ⚠️ 系统边界声明（必读）

**Life Index 是赋能 Agent 协助用户记录日志的工具，而非 Agent 自身的记忆系统。**

| 维度 | Life Index | Agent 核心记忆系统 |
|------|-----------|-------------------|
| **数据归属** | 用户的个人日志 | Agent 的平台级配置 |
| **存储位置** | `D:\Loster AI\Projects\life-index` | `C:\Users\<user>\AppData\Roaming\LobsterAI` |
| **操作对象** | 用户的生活记录 | Agent 的会话管理、技能配置 |
| **修改权限** | 仅响应用户指令时修改 | 由平台或显式配置变更 |

**Agent 执行准则**：操作本项目文件前，必须确认当前任务与 Life Index 直接相关。优化 Agent 自身记忆系统的任务，应作用于平台配置目录，而非本项目。

---

## 1. 初心与愿景

### 1.1 我们要解决什么问题

个人生活记录的三大痛点：
- **门槛高**: 传统工具需要学习成本，难以坚持
- **不可靠**: 云服务依赖、格式封闭、数据丢失风险
- **难回顾**: 记录后无法有效检索和利用

### 1.2 我们的解决方案

**Life Index** - 一个 Agent-first 的个人日志系统：
- 用自然语言记录，零学习成本
- 100% 本地存储，绝对数据主权
- 结构化元数据 + 智能索引，高效检索

### 1.3 设计底线

```
宁可功能简单，不可系统复杂
宁可人工维护，不可自动化陷阱
宁可牺牲性能，不可牺牲可靠性
```

---

## 2. 核心原则

### 2.1 Agent-first

- 能由 Agent 直接完成的操作，不开发专用工具
- 专用工具仅在需要**原子性**、**高可靠性**或**复杂计算**时引入
- Agent 使用通用文件操作工具直接管理数据

详见: [AGENT.md](./AGENT.md#核心工作流)

### 2.2 数据主权

- 100% 本地存储，用户拥有绝对数字主权
- 数据格式为人可读（Markdown + YAML），不依赖特定软件
- 目录结构清晰，便于人工浏览和维护

### 2.3 单层透明

```
用户 ↔ Agent ↔ 文件系统
```

禁止引入中间层（数据库、服务进程、API 网关等）。

### 2.4 SSOT（单一事实来源）

| 信息类型 | 唯一来源 | 说明 |
|---------|---------|------|
| 项目愿景与本手册 | HANDBOOK.md | 本文档 |
| Agent 执行指令 | AGENT.md | 工具调用、工作流步骤 |
| 决策变更历史 | CHANGELOG.md | 按日期记录的重大决策 |
| 开发计划 | Roadmap.md | Phase 划分与里程碑 |

---

## 3. 系统边界

### 3.1 我们做什么

- ✅ 自然语言日志记录
- ✅ 结构化元数据提取
- ✅ 多维度索引维护（时间、主题、项目、标签）
- ✅ 分层级日志检索
- ✅ 附件管理

### 3.2 我们不做什么

- ❌ 云端同步（用户可自行用云盘备份）
- ❌ 多人协作（当前单用户设计）
- ❌ 富文本编辑（纯 Markdown）
- ❌ 实时分析仪表盘（定期摘要替代）

### 3.3 可选组件（可删除而不影响核心）

| 组件 | 类型 | 删除影响 |
|------|------|----------|
| 月度/年度摘要 | 可选 | 搜索变慢，但可遍历目录；可重建 |
| by-topic 索引 | 可选 | 主题搜索失效，时间搜索仍可用；可重建 |
| 定时任务 | 可选 | 摘要不自动更新，可手动执行 |
| 天气查询 | 可选 | 需用户手动输入天气 |

---

## 4. 概念架构

### 4.1 数据流

```
┌─────────┐     自然语言      ┌─────────┐     结构化数据     ┌─────────────┐
│   用户   │ ─────────────────▶ │  Agent  │ ─────────────────▶ │  write_journal │
└─────────┘                    └─────────┘                    │    工具      │
                                                              └──────┬──────┘
                                                                     │
                              ┌──────────────────────────────────────┘
                              ▼
                    ┌───────────────────┐
                    │   journals/       │
                    │   attachments/    │
                    │   by-topic/       │
                    └───────────────────┘
```

### 4.2 模块关系

```
Life Index 系统
├── 核心数据层（不可删除）
│   ├── journals/          # 日志文件
│   │   └── YYYY/          # 年份目录
│   │       ├── yearly_abstract.md   # 年度摘要（位于年份目录）
│   │       └── MM/        # 月份目录
│   │           ├── monthly_abstract.md  # 月度摘要（位于月份目录）
│   │           └── life-index_*.md      # 日志文件
│   └── attachments/       # 附件
│
├── 索引层（可重建）
│   └── by-topic/          # 主题/项目/标签索引
│
└── 工具层（原子操作）
    ├── write_journal      # 写入日志 + 维护索引
    ├── search_journals    # 分层级检索
    └── query_weather      # 天气查询
```

### 4.3 三层分类模型

| 层级 | 名称 | 数量 | 说明 |
|-----|------|------|------|
| L1 | Topic（主题） | 5-8个 | 知识维度，预定义，长期稳定 |
| L2 | Project（项目） | <10个活跃 | 目标维度，动态管理 |
| L3 | Tag（标签） | 无限制 | 特征维度，灵活使用 |

详见: [AGENT.md](./AGENT.md#分类体系)

---

## 5. 目录结构规范

```
C:\Users\{username}\Documents\Life-Index\
│
├── journals\                    # 日志文件主目录
│   └── YYYY\                    # 年份目录
│       ├── yearly_abstract.md    # 年度元数据摘要
│       └── MM\                  # 月份目录
│           ├── monthly_abstract.md   # 月度元数据摘要
│           └── life-index_YYYY-MM-DD_NNN.md   # 日志文件
│
├── attachments\                 # 附件存储目录
│   └── YYYY\MM\                 # 按年月组织
│       └── [原始文件名]          # 保持原名的附件文件
│
└── by-topic\                    # 主题索引目录
    ├── 主题_[topic-id].md        # 各主题的日志索引
    ├── 项目_[project-name].md    # 各项目的日志索引
    └── 标签_[tag-name].md        # 各标签的日志索引
```

### 5.1 文件命名规范

| 文件类型 | 命名格式 | 示例 |
|----------|----------|------|
| 日志文件 | `life-index_YYYY-MM-DD_NNN.md` | `life-index_2026-03-03_001.md` |
| 月度摘要 | `monthly_abstract.md` | （固定名） |
| 年度摘要 | `yearly_abstract.md` | （固定名） |
| 主题索引 | `主题_[id].md` | `主题_work.md` |
| 项目索引 | `项目_[name].md` | `项目_LobsterAI.md` |
| 标签索引 | `标签_[name].md` | `标签_meeting.md` |

### 5.2 路径规范

**强制使用相对路径**，确保跨平台兼容性：

| 场景 | 相对路径写法 |
|------|-------------|
| 日志引用附件 | `../../../Attachments/YYYY/MM/file.jpg` |
| 索引引用日志 | `../../Journals/YYYY/MM/life-index_...` |
| 年度摘要引用月度 | `./MM/monthly_abstract.md` |

**向量索引存储**: `.vector_index/journals_fts.db` (SQLite + sqlite-vec)

**路径分隔符**: 统一使用正斜杠 `/`。

### 5.3 月度/年度摘要格式规范

#### 月度摘要 (`monthly_abstract.md`)

**位置**: `journals/YYYY/MM/monthly_abstract.md`

**标准格式**:
```markdown
# YYYY年M月 日志摘要

> 生成时间: ISO-8601时间戳
> 日志总数: N

## 按日期索引

### YYYY-MM-DD

| 序号 | 标题 | 时间 | 地点 | 人物 | 标签 | 项目 | 主题 | 文件路径 |
|------|------|------|------|------|------|------|------|----------|
| 001 | 标题 | HH:MM | 地点 | 人物 | 标签 | 项目 | 主题 | life-index_YYYY-MM-DD_001.md |
| 002 | ... | ... | ... | ... | ... | ... | ... | ... |

### YYYY-MM-DD（下一天）
...

## 按标签统计

- 标签1: N篇
- 标签2: N篇

## 按项目统计

- 项目1: N篇
- 项目2: N篇

## 按主题统计

- 主题1: N篇
- 主题2: N篇
```

#### 年度摘要 (`yearly_abstract.md`)

**位置**: `journals/YYYY/yearly_abstract.md`

**生成方式**: 读取各月的 `monthly_abstract.md`，汇总元数据视图

**内容结构**:
- 年度概览（总日志数、覆盖月份）
- 按月份的快速导航链接
- 按主题的年度汇总
- 按项目的年度汇总
- 高频标签云

---

## 6. 原子工具概述

为提升效率，以下功能封装为原子工具：

### 6.1 write_journal

- **职责**: 创建日志文件并维护所有衍生索引
- **输入**: 结构化数据（内容、元数据、附件列表）
- **输出**: 成功状态、文件路径、更新的索引列表
- **内部行为**: 生成文件名 → 复制附件 → 渲染 frontmatter → 写入文件 → 更新月度/年度/by-topic 索引

详见: [AGENT.md](./AGENT.md#工具一write_journal)

### 6.2 search_journals

- **职责**: 分层级检索日志
- **输入**: 查询类型、过滤条件、关键词、时间范围
- **输出**: 匹配结果列表、聚合统计、性能指标
- **策略**: L1索引层 → L2元数据层 → L3内容层（按需启用）

详见: [AGENT.md](./AGENT.md#工具二search_journals)

#### 分层搜索架构的设计 rationale

**为什么需要三层搜索？**

| 层级 | 适用数据规模 | 核心作用 | 当前状态 |
|------|-------------|---------|---------|
| **L1 索引层** | 1000+ 篇日志 | 通过 topic/project/tag 快速缩小范围 | 轻度使用 |
| **L2 元数据层** | 100-1000 篇 | 按日期/地点/天气等结构化字段过滤 | 日常使用 |
| **L3 内容层** | 任何规模 | 全文关键词搜索（FTS/向量索引） | **主要使用** |

**设计考量**（面向开源和长期使用）：

1. **渐进式性能**: 小数据量时 L3 足够快（<20ms），大数据量时 L1/L2 预过滤避免全量扫描
2. **可靠性分层**: 索引损坏时可降级（L1/L2 失效 → 直接 L3 扫描）
3. **导航与搜索分离**: 目录结构（by-topic/）服务于人工浏览，不强制作为搜索入口

**当前实践**（数据量 < 100 篇）：
- 默认直接使用 L3 FTS 搜索（`--use-index`）
- L1/L2 作为过滤条件显式启用（`--topic work --date-from 2026-01-01`）
- 性能已达标，三层架构为未来预留扩展空间

### 6.3 query_weather

- **职责**: 查询指定日期和地点的天气
- **输入**: 地点（城市, 国家）、日期
- **输出**: 天气描述、温度、标准化代码
- **数据源**: 历史数据（过去）或实时 API（当天）

### 6.4 edit_journal

- **职责**: 编辑已有日志的 frontmatter 和正文
- **输入**: 日志路径、要修改的字段（--set-*）、追加/替换内容
- **输出**: 成功状态、修改摘要
- **用途**: 极速记录后的补全模式

详见: [AGENT.md](./AGENT.md#工作流4极速记录补全模式推荐默认)

### 6.5 build_index

- **职责**: 构建 FTS5 和向量索引
- **输入**: --rebuild（全量重建）或增量更新
- **输出**: 索引统计、处理日志数
- **用途**: 加速 L3 搜索，支持语义检索

### 6.6 validate_data

- **职责**: 数据完整性校验
- **检查项**: 元数据合规、死链检测、附件验证、交叉引用
- **输出**: 错误/警告报告

### 6.7 rebuild_indices

- **职责**: 重建所有主题/项目/标签索引
- **用途**: 数据修复、索引重建

### 6.8 generate_abstract

- **职责**: 生成月度/年度摘要
- **输入**: `--month YYYY-MM` 或 `--year YYYY`
- **输出**: `Journals/YYYY/MM/monthly_abstract.md` 或 `Journals/YYYY/yearly_abstract.md`

---

**工具接口详细定义**: 以代码 `--help` 输出为准。AGENT.md 提供工作流层面的使用示例。

详见: [AGENT.md](./AGENT.md#工具三query_weather)

---

## 7. 未来增强（Roadmap）

### 7.1 附件哈希去重（Planned）

**背景**: 用户可能多次上传相同照片/视频，造成存储浪费。

**方案**: 为每个附件计算 SHA-256 哈希，作为唯一标识。

```yaml
# frontmatter 中的 attachments 字段
attachments:
  - filename: "IMG_20260304.jpg"
    hash: "sha256:a1b2c3d4..."  # 文件内容哈希
    size: 2048576
    description: "尿片侠的视频截图"
```

**应用场景**:
| 场景 | 哈希用途 |
|------|---------|
| **去重存储** | 相同哈希的附件只存一份，节省空间 |
| **完整性校验** | 验证附件未被意外修改或损坏 |
| **快速检索** | 通过哈希查找相同内容的不同日志引用 |
| **同步冲突解决** | 多设备同步时判断文件是否相同 |

**实现位置**: `write_journal.py` 的 `process_attachments()` 函数中计算并记录哈希。

**优先级**: P2（优化类），不影响核心功能。

### 7.2 语义检索增强 (RAG) - 已实现

**状态**: ✅ 已交付（2026-03-06）

#### 实现概览

| 组件 | 文件 | 状态 |
|------|------|------|
| FTS 全文索引 | `lib/search_index.py` | ✅ 可用 |
| 向量语义索引 | `lib/semantic_search.py` | 🚧 框架就绪，待 sqlite-vec 稳定 |
| 索引构建工具 | `build_index.py` | ✅ 可用 |
| 搜索集成 | `search_journals.py --use-index` | ✅ 可用 |

#### 使用方式

```bash
# 每日增量更新（Agent 定时任务 02:00）
python tools/build_index.py

# 每月全量重建（Agent 定时任务 每月1日 03:00）
python tools/build_index.py --rebuild

# 使用 FTS 索引加速搜索
python tools/search_journals.py --query "重构" --use-index

# 查看索引统计
python tools/build_index.py --stats
```

#### 技术架构

**四层搜索体系**:
```
L1: 索引层 (by-topic/)     → 文件系统扫描，< 10ms
L2: 元数据层 (frontmatter) → 文件系统扫描，< 50ms
L3: 全文层 (FTS5)          → SQLite 索引，< 50ms（与数量无关）⭐ NEW
L4: 语义层 (向量)           → sqlite-vec，待启用
```

**混合排序公式**:
```
final_score = w1×fts_score + w2×vec_score + w3×time_decay
```

**存储预估**:
- 嵌入模型: ~80MB（首次自动下载）
- FTS 索引: ~200KB/100篇日志
- 向量索引: ~500KB/100篇日志

#### 跨平台兼容性

**双后端架构**（自动选择）:
| 后端 | 适用平台 | 技术 | 状态 |
|------|---------|------|------|
| sqlite-vec | Linux/macOS/Windows(有DLL) | sqlite-vec 扩展 | 首选 |
| simple_numpy | 所有平台（Windows友好） | numpy + pickle | 降级 |

**自动选择逻辑**:
```python
if sqlite_vec_available():
    use_sqlite_vec_backend()   # 高性能 C 扩展
else:
    use_simple_numpy_backend()  # 纯 Python 实现
```

Windows 用户无需手动安装 sqlite-vec DLL，系统会自动使用 numpy 后端。

#### 设计约束（保持不变）

- **默认启用**: 开箱即用，零额外配置
- **零外部依赖**: 无云服务，全本地运行
- **非阻塞写入**: 索引构建不延迟日志记录
- **可靠性优先**: 索引损坏可重建，搜索可降级到文件系统扫描

### 7.3 日志编辑与补全（已实现）

**工具**: `edit_journal.py`

**设计原则**: 支持"先写入后编辑"的极速记录模式，location/weather 等字段可在后期补全。

**功能特性**:
| 特性 | 说明 |
|------|------|
| Frontmatter 编辑 | `--set-location`, `--set-weather`, `--set-topic` 等 |
| 正文追加/替换 | `--append-content`, `--replace-content` |
| 索引自动同步 | topic/project/tag 变更时自动重建索引 |
| 预览模式 | `--dry-run` 预览修改结果 |

**使用场景**:
```bash
# 场景1: 补充地点和天气
python tools/edit_journal.py --journal "Journals/2026/03/life-index_..." \
  --set-location "Beijing, China" --set-weather "多云"

# 场景2: 追加内容
python tools/edit_journal.py --journal "..." \
  --append-content "下午还讨论了部署方案。"

# 场景3: 修改分类（触发索引重建）
python tools/edit_journal.py --journal "..." --set-topic "learn"
```

### 7.4 生产就绪功能（P1 - 近期）

| 功能 | 价值 | 技术风险 | 实现思路 |
|------|------|---------|---------|
| **定时月度摘要** | 自动归档回顾 | 低 | Agent定时任务调用 `generate_abstract.py --month YYYY-MM` |
| **数据完整性校验** | 检测文件损坏 | 低 | `validate_data.py` 已交付 |
| **附件哈希去重** | 避免重复存储 | 低 | 写入前计算哈希，重复则引用现有文件 |

### 7.5 体验优化（P2 - 中期）

| 功能 | 价值 | 技术风险 | 实现思路 |
|------|------|---------|---------|
| ~~增量搜索索引~~ | ✅ **已完成** | - | SQLite FTS5 + sqlite-vec，已实现 |
| **自然语言查询** | "去年春天的照片" → 结构化查询 | 高 | 需要 LLM 解析时间表达式和意图 |
| **Obsidian 导出** | 一次性导出兼容格式 | 低 | `export_to_obsidian.py` 脚本，非实时同步 |

### 7.6 明确不做（保持克制）

| 功能 | 不做原因 |
|------|---------|
| 云端同步 | 违背数据主权原则 |
| 多人协作 | 单用户设计边界 |
| 富文本编辑器 | 增加复杂度，Markdown 足够 |
| 移动端 App | 维护成本高，可用响应式网页替代 |
| 实时双向 Obsidian 同步 | 增加中间层，违背单层透明原则 |

---

## 8. 开发历程

### 8.1 重大决策时间线

| 日期 | 决策 | 原因 | 详情 |
|------|------|------|------|
| 2026-02-24 | 项目重构启动 | v2过度工程化导致失效 | [CHANGELOG.md](./CHANGELOG.md#2026-02-24) |
| 2026-03-03 | SRS定稿 | 明确需求边界 | [CHANGELOG.md](./CHANGELOG.md#2026-03-03) |
| 2026-03-04 | 确立三步确认工作流 | 测试发现效率问题 | [CHANGELOG.md](./CHANGELOG.md#2026-03-04) |
| 2026-03-04 | 定义原子工具接口 | 提升写入效率 | [CHANGELOG.md](./CHANGELOG.md#2026-03-04-1) |

### 8.2 当前阶段

**Phase 5: 体验优化**（已完成）

关键任务:
- [x] RAG/FTS 索引实现
- [x] E2E 测试框架完成
- [x] 天气自动填充与确认流程

详见: [Development-Roadmap-v1.md](./Development-Roadmap-v1.md)

---

## 9. 术语表

| 术语 | 定义 |
|------|------|
| **Agent** | 具备文件操作能力的 AI 助手，系统核心执行者 |
| **Frontmatter** | Markdown 文件头部的 YAML 元数据块 |
| **Abstract** | 摘要文件，按月或按年汇总日志元数据 |
| **Topic** | 主题分类，知识维度（work/learn/health/relation/think/create/life） |
| **Project** | 项目分类，目标维度，有明确边界和成果 |
| **Tag** | 标签，特征维度，灵活标记 |
| **原子工具** | 封装确定性操作的函数式接口，供 Agent 调用 |
| **SSOT** | Single Source of Truth，单一事实来源原则 |

---

## 10. 参考链接

- [AGENT.md](./AGENT.md) - Agent 执行指令
- [CHANGELOG.md](./CHANGELOG.md) - 决策变更日志
- [Development-Roadmap-v1.md](./Development-Roadmap-v1.md) - 开发路线图
- [.reference/principles-v3-redesign.md](./.reference/principles-v3-redesign.md) - v3 设计原则（历史）

---

## 11. SSOT 文档维护责任

### 11.1 核心原则

本文档（HANDBOOK.md）、AGENT.md、CHANGELOG.md 构成 Life Index 的**单一事实来源（SSOT）**体系。任何项目变更必须同步更新到对应文档。

### 11.2 Agent 维护义务

当 Agent 执行以下操作时，**必须**检查并更新 SSOT 文档：

| 操作类型 | 需更新的文档 | 检查方式 |
|---------|-------------|---------|
| 修改工作流逻辑 | AGENT.md | 对比当前步骤与文档描述 |
| 调整工具接口 | AGENT.md + CHANGELOG.md | 检查接口定义章节 |
| 变更项目原则/架构 | HANDBOOK.md + CHANGELOG.md | 检查核心原则章节 |
| 完成里程碑任务 | Development-Roadmap-v1.md | 检查 Phase 进度 |

**检查触发条件**:
- 用户明确说"更新文档"
- 对话涉及"流程调整"、"接口变更"、"新决策"
- SSOT 文件最后修改时间超过 24 小时且对话涉及相关内容

**更新流程**:
1. 读取相关 SSOT 文档的最新内容
2. 识别需要更新的章节
3. 应用变更（保持格式一致）
4. 在 CHANGELOG.md 记录本次文档更新
5. 向用户确认更新完成

### 11.3 人类维护义务

作为项目所有者，你有权：
- 直接编辑任何 SSOT 文档
- 要求 Agent 审查特定文档的时效性
- 批准或拒绝 Agent 提出的文档更新

---

**文档结束**
