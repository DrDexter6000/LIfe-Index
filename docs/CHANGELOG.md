# Life Index 变更日志

> **本文档职责**: 决策变更历史 SSOT，记录"何时做了什么决定"

---

## [2026-03-13] 代码质量修复：安全性、可靠性、代码清理

**决策**: 基于 CTO 技术评审，修复 P0/P1 级问题，遵循 Agent-First 原则避免过度工程化。

**核心变更**:

1. **安全性修复 (P0)**
   - `lib/config.py:383-388`: 路径遍历保护修复，检测到不安全路径时返回 `None` 而非继续返回
   - `write_journal/core.py:109-133`: 序列号竞态修复，添加 3 次重试循环处理并发写入冲突

2. **可靠性优化 (P1)**
   - `lib/search_index.py:43`, `lib/metadata_cache.py:41`: SQLite 启用 WAL 模式提升并发性能

3. **异常处理规范化 (P1)**
   - 修复 13 处裸 `except Exception` 为具体异常类型（`OSError`, `IOError`, `sqlite3.Error` 等）
   - 涉及文件：`search_index.py`, `l1_index.py`, `semantic.py`, `l3_content.py`, `write_journal/core.py`, `search_journals/core.py`

4. **代码清理 (P2)**
   - 删除 `lib/config.py` 中重复的 `return {}` 和重复的条件检查
   - 删除重复的模块导入语句

5. **文档修复**
   - `AGENTS.md`: 删除重复的模块结构代码块和重复的定时任务规范段落

**不做清单** (Agent-First 原则排除):
- ❌ logging 模块 — Agent 能理解 print + JSON 输出
- ❌ SQLite 幂等性去重 — 违背单层透明原则，Agent 可"先查后写"
- ❌ OpenTelemetry/监控 — 单用户本地工具，无需分布式可观测性

**技术债务评级**: B+ → A- (安全性修复后)

---

## [2026-03-13] 代码质量修复：SSOT合规、事务保护、L2性能优化

**决策**: 基于CTO技术评审报告，修复P0级问题，提升代码质量和架构合规性。

**核心变更**:

1. **SSOT原则执行**
   - 统一使用 `lib/frontmatter` 作为frontmatter解析的单一事实来源
   - 修复 `search_journals/utils.py` 重复实现问题
   - 废弃 `write_journal/frontmatter.parse_frontmatter`，添加废弃警告

2. **事务保护机制**
   - 重构 `write_journal/core.py`，添加基于临时文件的事务保护
   - 确保文件写入和索引更新的原子性
   - 失败时自动回滚，避免数据不一致

3. **L2搜索性能优化**
   - 新建 `lib/metadata_cache.py` 模块（396行）
   - 重构 `search_journals/l2_metadata.py` 使用SQLite元数据缓存
   - 实现文件签名检测（mtime+size）判断缓存有效性
   - 支持增量更新，避免重复解析
   - 性能提升预估：50-100x（1000篇日志场景）

4. **异常处理规范化**
   - 修复25处裸 `except Exception` 为具体异常类型
   - 涉及文件：`build_index.py`, `query_weather.py`, `generate_abstract.py`, `config.py`, `frontmatter.py` 等

5. **代码清理**
   - 删除 `config.py` 中重复的函数定义
   - 修复 `pyproject.toml` 重复配置问题
   - 修复 `build_index.py` 语法错误

6. **测试增强**
   - 新建 `test_metadata_cache.py` 单元测试（11个测试用例）
   - 总测试数从48个提升到59个
   - 所有测试100%通过

**技术债务**: C+ → B+ 评级提升

**SSOT 同步**:
- `docs/API.md` - 更新搜索模块说明（如需要）
- `docs/HANDBOOK.md` - 架构章节已反映最新设计
- `AGENTS.md` - 工具结构说明保持准确

---

---

> **本文档职责**: 决策变更历史 SSOT，记录"何时做了什么决定"

---

---

## [2026-03-13] Schedule 文档重写：基于 OpenClaw 官方文档的定时任务配置指南

**决策**: 完全重写 references/schedule/SCHEDULE.md，基于 OpenClaw 官方文档和社区最佳实践，提供真实可用的定时任务配置模板。

**核心变更**:
1. **查阅官方文档**
   - OpenClaw 官方 Cron Jobs 文档 (openclawlab.com)
   - Stack Junkie 社区指南
   - 多个中文社区资源

2. **编写 6 个完整任务模板**
   - 日报 (0 22 * * *) - 200 tokens
   - 周报 (10 22 * * 0) - 500 tokens
   - 月报 (30 18 28-31 * *) - 1000 tokens
   - 年报 (15 19 31 12 *) - 3000 tokens
   - 每日索引维护 (50 23 * * *)
   - 每月索引重建 (30 3 1 * *)

3. **5 步 Agent-Native 结构**
   - Step 1: 理解任务（为什么需要定时任务）
   - Step 2: OpenClaw 参考模板（6个任务的 CLI + JSON 配置）
   - Step 3: 自我系统分析（版本、路径、时区检查）
   - Step 4: 判断与决策（决策流程图）
   - Step 5: 执行设置（创建、验证、故障排查）

4. **时区确认环节**
   - 移除硬编码 `Asia/Shanghai`
   - 添加 `[YOUR_TIMEZONE]` 占位符
   - 提供时区检测命令和常见时区列表
   - 说明 UTC 作为默认选项

5. **完整的故障排查指南**
   - 5 个常见问题及解决方案
   - 引用官方 troubleshooting 文档

**外部参考链接**:
- [OpenClaw Cron Jobs 官方文档](https://openclawlab.com/en/docs/automation/cron-jobs/)
- [Cron vs Heartbeat 对比](https://openclawlab.com/en/docs/automation/cron-vs-heartbeat/)
- [Stack Junkie: 8 个自动化模板](https://www.stack-junkie.com/blog/openclaw-cron-jobs-automation-guide)
- [Cron 表达式验证工具](https://crontab.guru/)

**SSOT 同步**:
- 更新 `references/schedule/SCHEDULE.md`（600+ 行完整指南）
- 保留 `references/schedule/scenarios/*.md`（6 个场景详细指南）
- 删除 VS Code 生成的多余文件

---


## [2026-03-12] SSOT 重构：统一 frontmatter 处理，消除代码重复

**决策**: 创建 `lib/frontmatter.py` 作为 YAML 解析/格式化的单一事实来源，消除多工具间的代码重复，删除冗余工具。

**核心变更**:
1. **新建共享库**: `tools/lib/frontmatter.py`
   - 统一 YAML frontmatter 解析/格式化逻辑（SSOT）
   - 提供 `parse_frontmatter()`, `parse_journal_file()`, `format_frontmatter()` 等标准函数
   - 提供 `validate_metadata()` 元数据验证功能
   - 支持字段顺序标准化、类型自动转换

2. **删除重复工具**: ~~`tools/check_metadata.py`~~
   - 功能完全被 `validate_data.py` 覆盖
   - 减少维护负担，简化工具集（9个 → 8个）

3. **重构既有工具**，迁移至 `lib/frontmatter`:
   - `edit_journal.py`: 移除本地 YAML 解析实现，使用 `lib/frontmatter`
   - `validate_data.py`: 移除 `_simple_yaml_parse()`，使用 `lib/frontmatter`
   - `rebuild_indices.py`: 移除 `_simple_yaml_parse()`，使用 `lib/frontmatter`

4. **更新单元测试**:
   - `tests/unit/test_write_journal.py`: 修复导入路径（函数已移至子模块）
   - `tests/unit/test_search_journals.py`: 修复导入路径（使用 `lib/frontmatter`）
   - 新增 `tests/unit/test_frontmatter.py`: 为新的 SSOT 模块提供完整测试覆盖（16个测试用例）

5. **更新 SSOT 文档**:
   - `AGENTS.md`: 更新模块结构图，添加 `lib/frontmatter.py` 说明
   - 更新"修改日志格式"开发指南，引用 `lib/frontmatter.py`

**测试覆盖更新**:
- 单元测试总数：48个（新增16个，原有32个修复通过）
- E2E测试：保持现有 YAML 测试用例（不受代码重构影响）
- 测试验证：所有测试通过，重构未破坏现有功能

**代码重复消除统计**:
| 重复代码 | 原位置 | 现位置 | 节省行数 |
|----------|--------|--------|----------|
| YAML 解析器 | edit_journal.py | lib/frontmatter.py | ~80行 |
| YAML 解析器 | validate_data.py | lib/frontmatter.py | ~120行 |
| YAML 解析器 | rebuild_indices.py | lib/frontmatter.py | ~80行 |
| **合计** | | | **~280行** |

**设计原则符合度**:
- ✅ **SSOT**: frontmatter 逻辑集中到单一模块
- ✅ **DRY**: 消除 3 处重复实现
- ✅ **极简主义**: 删除冗余工具
- ✅ **向后兼容**: 所有 CLI 接口保持不变

**SSOT 同步**:
- 更新 `AGENTS.md` 模块结构说明
- 更新 `docs/CHANGELOG.md` 添加变更记录

---

## [2026-03-12] 模块深度拆分与代码重构

**决策**: 进一步细化拆分 write_journal 和 search_journals 模块，提升代码可维护性和单一职责原则。

**核心变更**:
1. **write_journal 模块拆分**: 将 core.py (952行) 拆分为6个子模块
   - `utils.py`: 通用工具函数（get_year_month, generate_filename, get_next_sequence, convert_path_for_platform）
   - `frontmatter.py`: YAML frontmatter格式化（format_frontmatter, format_content, parse_frontmatter）
   - `attachments.py`: 附件处理逻辑（extract_file_paths_from_content, looks_like_file_path, process_attachments）
   - `weather.py`: 天气查询相关（query_weather_for_location, normalize_location）
   - `index_updater.py`: 索引更新逻辑（update_topic_index, update_project_index, update_tag_indices, update_monthly_abstract）
   - `core.py`: 核心协调逻辑（write_journal主函数，~192行）

2. **search_journals 模块拆分**: 将 core.py (906行) 拆分为7个子模块
   - `utils.py`: 通用工具函数（parse_frontmatter）
   - `l1_index.py`: 一级索引搜索（scan_all_indices, search_l1_index）
   - `l2_metadata.py`: 二级元数据搜索（search_l2_metadata）
   - `l3_content.py`: 三级内容搜索（search_l3_content）
   - `semantic.py`: 语义搜索相关（search_semantic, enrich_semantic_result）
   - `ranking.py`: 结果排序算法（merge_and_rank_results, merge_and_rank_results_hybrid）
   - `core.py`: 核心协调逻辑（hierarchical_search主函数，~233行）

3. **新增模块执行入口**: 添加 `__main__.py` 支持 `python -m` 方式运行

**文件变更**:
- 修改: `tools/write_journal/core.py` (952行 → 192行)
- 修改: `tools/search_journals/core.py` (906行 → 233行)
- 修改: `AGENTS.md` 更新模块结构说明
- 新增: `tools/write_journal/__main__.py`
- 新增: `tools/write_journal/utils.py`
- 新增: `tools/write_journal/frontmatter.py`
- 新增: `tools/write_journal/attachments.py`
- 新增: `tools/write_journal/weather.py`
- 新增: `tools/write_journal/index_updater.py`
- 新增: `tools/search_journals/__main__.py`
- 新增: `tools/search_journals/utils.py`
- 新增: `tools/search_journals/l1_index.py`
- 新增: `tools/search_journals/l2_metadata.py`
- 新增: `tools/search_journals/l3_content.py`
- 新增: `tools/search_journals/semantic.py`
- 新增: `tools/search_journals/ranking.py`

**SSOT 同步**:
- 更新 [AGENTS.md](../AGENTS.md) 模块结构说明（2026-03-12更新）
- 更新 [docs/CHANGELOG.md](./CHANGELOG.md) 添加变更记录

**验证结果**:
- ✅ write_journal/core.py: 952行 → 192行（减少80%）
- ✅ search_journals/core.py: 906行 → 233行（减少74%）
- ✅ 所有子模块可以独立导入
- ✅ CLI入口正常工作
- ✅ mypy检查无新增错误

---

## [2026-03-11] 代码质量提升与模块化重构

## [2026-03-11] 代码质量提升与模块化重构

**决策**: 修复mypy类型错误，完成核心模块的初步拆分，提升代码质量和可维护性。

**核心变更**:
1. **类型错误修复**: 修复了145+个mypy类型错误，添加完整类型注解
   - `tools/lib/errors.py`: 修复`to_json()`和`create_error_response()`的类型注解
   - `tools/check_metadata.py`: 添加完整类型注解
   - `tools/validate_data.py`: 修复`sequences_by_date`类型注解
   - `tools/generate_abstract.py`: 添加`parsed_value: Any`等类型注解
   - `tools/edit_journal.py`: 修复`frontmatter`和`result`类型注解
   - `tools/query_weather.py`: 添加返回类型注解
   - `tools/rebuild_indices.py`: 修复`Optional[Path]`返回类型

2. **模块拆分**: 将大文件拆分为模块化结构
   - `tools/write_journal.py` (993行) → `write_journal/__init__.py` + `write_journal/core.py`
   - `tools/search_journals.py` (920行) → `search_journals/__init__.py` + `search_journals/core.py`

3. **导入修复**: 修复了模块导入路径问题
   - 修复`write_journal/__init__.py`的循环导入问题
   - 修复`search_journals/core.py`的`lib.config`导入路径

**文件变更**:
- 修改: `tools/build_index.py`, `tools/edit_journal.py`, `tools/generate_abstract.py`
- 修改: `tools/lib/errors.py`, `tools/lib/search_index.py`
- 修改: `tools/query_weather.py`, `tools/validate_data.py`, `tools/rebuild_indices.py`
- 新增目录: `tools/write_journal/`, `tools/search_journals/`
- 删除: `tools/write_journal.py`, `tools/search_journals.py` (已拆分)

**SSOT 同步**:
- 更新 [AGENTS.md](../AGENTS.md) 添加模块结构说明
- 更新 [docs/API.md](./API.md) 反映新的模块路径

---

## [2026-03-11] 定时任务文档体系重构

> **本文档职责**: 决策变更历史 SSOT，记录"何时做了什么决定"

---

## [2026-03-11] 定时任务文档体系重构

**决策**: 重构 SCHEDULE.md，采用渐进式披露 + 树形结构，优化 Agent 可读性。

**核心变更**:
1. **STOP 点简化**: 删除用户确认环节，改为 `前置检查 + 后置记录`
2. **推送渠道明确**: 日报/周报推送到主会话 + IM 渠道
3. **索引任务重新设计**: 每日索引维护（检查+修复+向量增量）、每月索引维护（全量检查+重建+向量全量）
4. **无数据处理**: 保留元数据占位，报告后询问用户是否补充
5. **文档架构重构**: SCHEDULE.md 移动到 `references/schedule/`
6. **templates 融合**: 删除 templates 目录，输出格式整合到 scenarios 文档中（单一来源）
7. **新闻链接要求**: 周报/月报/年报的国际热点每条新闻后附带来源链接

**最终文档结构**:
```
references/schedule/
├── SCHEDULE.md           ← Router（权威文档）
└── scenarios/            ← 场景文档（含输出格式）
    ├── daily-report.md
    ├── weekly-report.md
    ├── monthly-report.md
    ├── yearly-report.md
    ├── index-update.md
    └── index-rebuild.md
```

**关键发现**: `write_journal.py` 在写入日志时已自动更新 by-topic 索引，因此每日索引任务应为"检查+修复"而非"更新"。

**SSOT 同步**:
- 更新 [AGENTS.md](../AGENTS.md) SCHEDULE.md 路径引用
- 更新 [README.md](../README.md) SCHEDULE.md 路径引用
- 更新 [INSTRUCTIONS.md](./INSTRUCTIONS.md) SCHEDULE.md 路径引用
- 更新 [docs/README.md](./docs/README.md) 添加 SCHEDULE.md 导航

---

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
