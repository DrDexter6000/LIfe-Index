# Life Index 变更日志

> **本文档职责**: 决策变更历史 SSOT，记录"何时做了什么决定"

---

## [2026-03-09] 报告文件命名规范化

**决策**: 统一月报/年报文件命名，与 SCHEDULE.md 规范保持一致。

**核心实现**:
- `generate_abstract.py`: 月度报告文件名从 `monthly_abstract.md` 改为 `monthly_report_YYYY-MM.md`
- `generate_abstract.py`: 年度报告文件名从 `yearly_abstract.md` 改为 `yearly_report_YYYY.md`

**文件命名对照**:
| 类型 | 旧命名 | 新命名 |
|------|--------|--------|
| 月报 | `monthly_abstract.md` | `monthly_report_2026-03.md` |
| 年报 | `yearly_abstract.md` | `yearly_report_2026.md` |

**说明**:
- 日报、周报：不生成文件，仅推送消息（符合 SCHEDULE.md 设计）
- 月报、年报：生成文件并推送消息

**SSOT 同步**:
- 更新 [generate_abstract.py](../tools/generate_abstract.py) 修改文件命名逻辑
- 更新 [SKILL.md](../SKILL.md) 更新示例中的文件路径

---

## [2026-03-09] 附件自动检测与元数据格式修复

**决策**:
1. 实现从日志内容中自动检测本地文件路径并作为附件处理
2. 修复元数据格式与历史日志保持一致（添加缺失的 `links` 字段）

**核心实现**:
- `write_journal.py`: 新增 `extract_file_paths_from_content()` 函数，自动提取 Windows 绝对路径和 UNC 路径
- `write_journal.py`: 新增 `looks_like_file_path()` 辅助函数，通过文件扩展名验证路径有效性
- `write_journal.py`: 修改 `process_attachments()` 支持自动检测附件和显式附件的合并去重
- `write_journal.py`: 修改 `format_frontmatter()` 确保 `links: []` 字段始终输出（与历史日志格式一致）

**用户体验变更**:
- **之前**: 用户必须在 `attachments` 参数中显式提供文件路径
- **之后**: 用户只需在正文中提及文件路径（如 `C:\Users\...\file.png`），工具自动检测并处理

**Agent 行为变更**:
- Agent 无需手动提取内容中的文件路径
- Agent 无需重复传递自动检测到的附件
- 用户显式提及的附件仍可通过 `attachments` 参数传递

**SSOT 同步**:
- 更新 [SKILL.md](../SKILL.md) 添加 Attachment Auto-Detection 章节
- 更新 [write_journal.py](../tools/write_journal.py) 实现自动检测逻辑

---

## [2026-03-09] 修复内容保留与元数据格式问题

**决策**: 修复实装后发现的两类问题：正文内容被"优化"改造、元数据格式与历史日志不一致。

**问题分析**:
1. **正文内容问题**: Agent 在调用 write-journal 前对用户输入进行了预处理（添加序号、修改标题层级等），导致原始格式丢失
2. **元数据格式问题**: `date` 字段被添加了引号，与历史日志格式（无引号）不一致

**修复内容**:
- `write_journal.py`: 移除 `date` 字段的引号，保持 `date: 2026-03-09T20:12:46` 格式
- `SKILL.md`: 新增 "Content Preservation Rule" 章节，明确规定 Agent 必须 100% 保留用户原始输入格式

**SSOT 同步**:
- 更新 [SKILL.md](../SKILL.md) 添加 Content Preservation Rule
- 更新 [write_journal.py](../tools/write_journal.py) 修复 date 字段格式

---

## [2026-03-08] 天气自动填充与确认流程

**决策**: 实现三层天气处理机制，减少用户输入负担，确保日志完整性。

**核心实现**:
- `write_journal.py` 自动填充默认地点 "重庆，中国"（当用户未提供时）
- 自动调用 `query_weather.py` 获取天气（当用户未提供时）
- 支持中文城市名自动推断国家（如 "北京" → "Beijing, China"）
- 写入后返回 `needs_confirmation` 和 `confirmation_message`，引导用户确认/修改

**用户体验变更**:
- **之前**: 用户必须提供 "地点，天气"，否则日志不完整
- **之后**: 用户只需讲述内容，工具自动填充地点和天气，写入后询问确认

**示例**:
```
用户: "今天想记录一下关于 Life Index 的初心..."
Agent: 自动填充地点="重庆，中国"，天气="Slight rain (小雨)"
Agent: "日志已保存。当前记录信息：地点：重庆，中国；天气：Slight rain (小雨)。请确认以上信息是否正确？"
```

**SSOT 同步**: 更新 [SKILL.md](../SKILL.md) 添加 Weather Handling Rules 章节

---

## [2026-03-07] 摘要生成工具合并

**决策**: 将月度摘要和年度摘要生成功能合并为统一的 `generate_abstract.py` 工具。

**核心实现**:
- 新建 `tools/generate_abstract.py`，整合月度/年度摘要功能
- 支持参数：`--month YYYY-MM`、`--year YYYY`、`--all-months`、`--dry-run`
- 更新 `write_journal.py`，调用新工具生成月度摘要（修复写入顺序问题）
- 更新 `SKILL.md`，添加 generate-abstract 工作流说明

**影响范围**:
- `tools/generate_yearly_abstract.py` 标记为已合并（保留在 GitHub，排除在 ClawHub 外）
- `.gitignore` 和 `.clawhubignore` 更新排除旧工具

**SSOT 同步**: 更新 [SKILL.md](../SKILL.md) 工作流和示例

---

## [2026-03-06] 语义搜索与混合排序实现

**决策**: 实现 `--semantic` 参数，支持 BM25 + 向量相似度加权混合排序。

**核心实现**:
- `search_journals.py` 添加 `--semantic`、`--semantic-weight`、`--fts-weight` 参数
- 新增 `merge_and_rank_results_hybrid()` 函数实现混合排序
- 集成 `vector_index_simple.py` 作为语义搜索后端

**SSOT 同步**: 更新 [INSTRUCTIONS.md](./INSTRUCTIONS.md) 第 5 章搜索工具接口

---

## [2026-03-06] Topic/Project 数组匹配修复

**决策**: 修复复合查询（topic + date）失效问题，支持数组格式 topic/project 匹配。

**影响**: `tools/search_journals.py` L2 元数据过滤逻辑

---

## [2026-03-06] 搜索结果相关性排序优化

**决策**: 引入 BM25 相关性评分和分层优先级策略（L3>L2>L1）。

**影响**: `tools/lib/search_index.py`, `tools/search_journals.py`

---

## [2026-03-06] L2 元数据层过滤优化

**决策**: 当指定 `--query` 时，要求元数据（title/abstract/tags）必须包含查询关键词。

**影响**: `tools/search_journals.py`

---

## [2026-03-06] E2E 测试框架实施

**决策**: 建立端到端测试框架，完成 Phase 1-4 全部 16 个测试用例。

**测试覆盖**: 核心工作流、搜索检索、边界异常、数据一致性

**SSOT 同步**: 更新 [INSTRUCTIONS.md](./INSTRUCTIONS.md) 第 10 章

---

## [2026-03-06] RAG 语义检索与 FTS 增量索引实现

**决策**: 实现 SQLite FTS5 增量索引和 RAG 语义检索框架。

**核心组件**:
- `lib/search_index.py` - FTS5 索引管理
- `lib/semantic_search.py` - 向量索引框架
- `build_index.py` - 索引构建 CLI
- `search_journals.py --use-index` - 索引加速搜索

**SSOT 同步**: 更新 [HANDBOOK.md](./HANDBOOK.md) 第 7.2 节

---

## [2026-03-06] 向量索引 Windows 兼容性完善

**决策**: 实现双后端架构（sqlite-vec / simple_numpy），自动选择可用后端。

**影响**: `lib/semantic_search.py`, `lib/vector_index_simple.py`, `build_index.py`

---

## [2026-03-05] 极速记录+补全模式实现

**决策**: 实现"先写入后编辑"工作流，创建 `edit_journal.py` 工具。

**核心设计**:
- `write_journal.py` - 即时写入（允许 location/weather 缺失）
- `edit_journal.py` - 后期编辑 frontmatter 和正文

**SSOT 同步**: 更新 [INSTRUCTIONS.md](./INSTRUCTIONS.md) 工作流4，[HANDBOOK.md](./HANDBOOK.md) 第 7.3 节

---

## [2026-03-05] 年度摘要生成工具

**决策**: 创建 `generate_yearly_abstract.py`，Agent-first 方式触发（弃用 Windows Task Scheduler）。

---

## [2026-03-05] 月度摘要自动更新

**决策**: `write_journal.py` 集成月度摘要自动更新功能。

---

## [2026-03-05] 附件路径标准化

**决策**: 统一附件路径格式为 `../../../Attachments/YYYY/MM/`。

---

## [2026-03-05] 数据完整性修复

**决策**: 清理死链（7个）、重建索引（67个文件）。

**新增工具**: `validate_data.py`, `rebuild_indices.py`

---

## [2026-03-05] Abstracts 目录结构审查与 SSOT 修复

**决策**: 确认分层存储原则（月度→MM目录，年度→YYYY目录），修复 HANDBOOK.md 示意图。

**影响**: 更新 [HANDBOOK.md](./HANDBOOK.md) 第 4.2 节系统架构图

---

## [2026-03-05] 旧格式日志迁移

**决策**: 迁移 15 个旧格式日志到标准格式，创建 `migrate_legacy_logs.py` 工具。

---

## [2026-03-04] 路径和元数据修复

**决策**: 修正数据目录路径为用户文档目录，完善元数据字段（mood、people、abstract 等）。

---

## [2026-03-04] 定义原子工具接口

**决策**: 确立三个原子工具：write_journal、search_journals、query_weather。

**SSOT 同步**: 更新 [INSTRUCTIONS.md](./INSTRUCTIONS.md) 第 3 章工作流

---

## [2026-03-04] 确立三步确认工作流

**决策**: 日志记录标准工作流：语义解析 → 确认地点天气 → 三分支处理。

---

## [2026-03-04] 文档体系重构（SSOT 合规）

**决策**: 拆分文档为 HANDBOOK.md（架构）、INSTRUCTIONS.md（指令）、CHANGELOG.md（历史）。

---

## [2026-03-03] SRS v1.0 定稿

**决策**: 完成 Life Index v3 软件需求规格说明书。

---

## [2026-02-24] 项目重构启动

**决策**: 彻底重构项目，建立 Life Index v3 新系统。

---

**文档结束**
