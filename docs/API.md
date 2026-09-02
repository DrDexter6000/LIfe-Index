# Life Index API 规范

> **本文档职责**: 工具接口规范 SSOT，所有工具的参数、返回值、错误码定义
> **目标读者**: Agent、开发者
> **SSOT 引用**: SKILL.md 与公开 Agent 入口文档应引用本文档，不重复定义参数
> **平台边界权威**: `CHARTER.md §1.10` 独占 C1–C7 闭合 Core 准入域；`docs/ARCHITECTURE.md` 的 `PLATFORM-SSOT:PUBLIC-COMMAND-CLASSIFICATION` 命名块独占 31 条 public route 的精确分类。Distribution/Host Operations 即使与 Core 同包分发也属于 non-Core；`weather` 是 #166 跟踪的 Legacy External Adapter。本 API 不复制域目录或命令分类表。

---

## 通用规范

### 模块消费稳定契约（CHARTER §1.10）

Life Index CLI 向 L3/L4 模块提供**确定性、稳定、可组合的基础能力**。模块消费者可依赖以下四维契约：

| 维度 | 说明 | 稳定性承诺 |
|------|------|-----------|
| **JSON Shape** | 返回结构的顶层字段名称与类型；错误返回统一包含 `success` / `error`，成功返回采用工具自定义顶层字段 + `error: null` | 稳定：字段名称与顶层结构不变，不假设统一 `data` wrapper |
| **字段语义** | 每个字段的精确含义与枚举值 | 稳定：语义不变，允许新增字段 |
| **错误码** | `E{module}{type}` 分类与 `recovery_strategy` 语义 | 稳定：已有错误码不退化，允许新增 |
| **关键 SLO** | 核心延迟与质量指标 | 稳定：不恶化 ≥3%（退化 ≥3% 需附 RFC） |

**关键 SLO 基准**（CHARTER §4.5）：

| 指标 | 目标 | 基线 |
|------|------|------|
| `search` p95 延迟 | ≤ 500ms | ~20ms (keyword-only) |
| `smart-search` 默认路径 p95 | ≤ 8s | 降级模式 ≤ 500ms |
| 公开合成 Core recall assertion | 必须执行且通过 | 仓库内合成 fixture |
| 本地 / 私有 eval | advisory | 仅存于公开制品之外的 operator evidence |

> 公开阻断只依赖可复现的合成 Core assertion。本地 / 私有 eval 的语料事实与
> 测量结果不进入公开权威，缺失时显式 skip，存在时也仅作为 advisory evidence。

**模块消费约束**：
- 模块应通过 CLI JSON-in/JSON-out 或 `tools.*` 公开 API 消费 L2 基元
- 模块不得假设 CLI core 内部实现细节（如 SQLite 表结构、索引文件格式、jieba 配置）
- 模块不得绕过 CLI 直接读写 `~/Documents/Life-Index/` 下的用户数据文件
- 模块-local 过程状态（cursor、checkpoint、中间产物）应存放在模块自己的物理目录，不进入用户数据目录

面向未来高级模块的开发者契约以本文档与 `docs/ARCHITECTURE.md` 的公开契约为准；历史 RFC 文件不属于活跃公开文档面。

### 调用方式

所有工具通过 Bash CLI 调用，返回 JSON 格式：

```bash
python -m tools.{tool_name} --data '{json_data}'
```

### 验证模式数据目录守卫

自动化验证或 smoke test 可设置 `LIFE_INDEX_VALIDATION_MODE=1`。在该模式下，CLI
会在命令分发前拒绝使用默认用户数据目录：如果 `LIFE_INDEX_DATA_DIR` 未设置，
或解析到平台默认的 `~/Documents/Life-Index`，命令会以非零状态退出并提示设置
隔离沙箱目录。未设置 `LIFE_INDEX_VALIDATION_MODE` 时，真实用户默认路径行为不变。

```bash
export LIFE_INDEX_VALIDATION_MODE=1
export LIFE_INDEX_DATA_DIR="/path/to/sandbox/Life-Index"
python -m tools health
```

### 通用返回约定

当前源码的**错误返回**遵循统一结构：

```json
{
  "success": false,
  "error": {
    "code": "E0000",
    "message": "错误信息",
    "details": { ... },
    "recovery_strategy": "ask_user|skip_optional|continue|continue_empty|fail|retry"
  }
}
```

恢复结果还明确报告证据等级：

```json
{
  "success": true,
  "files_restored": 42,
  "errors": [],
  "restore_mode": "manifest_verified",
  "recovery_manifest_verified": true,
  "warnings": []
}
```

当前源码的**成功返回**没有统一 `data` wrapper；通常采用工具自定义的顶层字段：

```json
{
  "success": true,
  "...tool_specific_fields": "...",
  "error": null
}
```

> 若未来要统一成功返回格式，应先修改源码，再回写本文档。

### 错误码分类

| 模块 | 代码范围 | 说明 |
|------|----------|------|
| 通用 | E00xx | 输入错误、权限错误 |
| 文件 | E01xx | 文件不存在、路径错误 |
| 写入 | E02xx | 写入失败、格式错误 |
| 搜索 | E03xx | 索引错误、查询错误 |
| 天气 | E04xx | API 失败、超时 |
| 编辑 | E05xx | 日志不存在、冲突 |
| 索引 | E06xx | 构建失败、损坏 |
| Web | E07xx | Web GUI / URL 下载 / LLM 提供方 / 地理定位相关错误 |
| 迁移 | E08xx | **Reserved / 未实现** — Schema 迁移错误码已预留，但当前 runtime 不发射结构化 E08xx 码 |

### Closed Host-Agent tool channel and optional MCP projection

`tools.host_agent_channel.registry.CAPABILITY_REGISTRY` is the single closed
authority for the initial Host-Agent tool channel.  Transports generate from
that registry; they must not add methods, schemas, write authority, filesystem
access, shell access, LLM/provider behavior, planning, or orchestration.

| Method ID | Operation class | MCP `readOnlyHint` | Bounded physical effect |
|---|---|---|---|
| `health` | `read` | `true` | None |
| `journal.get` | `read` | `true` | None; exactly one of `path` or `id` is required |
| `search` | `read` | `false` | May refresh only `.index`, a rebuildable derived tree |

The dispatcher validates structured parameters before Core and invokes the same
canonical application functions used by the direct CLI.  It preserves the
existing domain envelopes and direct CLI remains a supported canonical path.
`search` does not mutate journals, frontmatter, attachments, entity graph,
metadata cache, or search metrics through this channel.
The optional MCP projection derives its tool annotations from the same
registry. `health` and `journal.get` declare `readOnlyHint=true`. `search` remains a logical `read`, but its MCP `readOnlyHint=false` honestly
reflects that its only allowed effect is a refresh of rebuildable `.index` derived state. Every method declares `destructiveHint=false` and `openWorldHint=false`;
`idempotentHint` remains registry-specific.
The validation-only tool-call trace remains available as external control
evidence for direct dispatcher validation; it is not an MCP capability effect.
The generic MCP projection explicitly disables trace emission even when
`LIFE_INDEX_VALIDATION_MODE=1` and `LIFE_INDEX_TOOL_CALL_LOG` are set. For
direct dispatcher validation, a configured trace target that resolves into or
overlaps the data directory is rejected before it can create source state.

`tools.mcp_projection` is a generic, removable stdio transport projection of
this registry.  It is optional: install its exact extra with
`python -m pip install "life-index[mcp]"` (`mcp==1.27.2`), then run:

```bash
python -m tools.mcp_projection
```

It introduces no new environment variable and continues to use the existing
`LIFE_INDEX_DATA_DIR` data-boundary behavior.  `tools/mcp_discovery` remains a
separate static discovery stub; it is not the projection registry.  There is
no D5 hand-written newline JSON-RPC server: stdio lifecycle is owned by the
optional official SDK.

## v1.1.1 Observability Contract

> **适用版本**: v1.1.1+
> **范围**: Phase A (Sub-PRD-1) — provenance envelope、step diagnostics、cache version governance

Phase A 为 JSON 输出生成命令引入三层可观测性契约，全部 additive，不破坏 v1.1.0 客户端兼容。

### Provenance Envelope

六个生成 JSON 的命令在输出顶层附加 `schema_version` 与 `provenance` 字段：

| 命令 | `generator` 值 | 备注 |
|------|---------------|------|
| `search` | `search` | 取代旧 `schema_version: "m16.search.v0"` |
| `index` | `index` | 取代旧 `schema_version: "m16.index.v0"`（若存在） |
| `eval` | `eval` | 新增 |
| `entity` | `entity` | 取代旧 `schema_version: "m16.entity.v0"` |
| `maintenance` | `maintenance` | 取代旧 `schema_version: "m16.maintenance.v0"` |
| `trajectory` | `trajectory` | 取代旧 `schema_version: "m26.trajectory.v0"` |

**顶层字段**：

```json
{
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:abc...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "search|index|eval|entity|maintenance|trajectory",
    "params_hash": "sha256:def...",
    "fixture_version": null
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定为 `"v1.1.1"` |
| `provenance.source_hash` | string | 输入数据稳定 SHA-256（journal + entity_graph + 配置） |
| `provenance.tool_version` | string | Life Index package 版本（来自 `pyproject.toml`） |
| `provenance.generated_at` | string | ISO 8601 UTC 时间戳 |
| `provenance.generator` | string enum | 生成该输出的命令标识 |
| `provenance.params_hash` | string | 命令参数集稳定 SHA-256（时间相关 flag 除外） |
| `provenance.fixture_version` | string \| null | 仅 `eval` 使用，标识 eval baseline fixture 版本 |

**兼容策略**: v1.1.0 客户端可安全忽略未知顶层字段；字段语义 additive-only。

### Step Diagnostics (`--explain`)

`search --explain`、`smart-search --explain`、`index --explain` 在输出顶层附加 `diagnostics` 字段：

```json
{
  "diagnostics": {
    "input_count": 1234,
    "filter_drops": {},
    "cache_hits": 800,
    "cache_misses": 400,
    "latency_ms": {
      "total": 45
    },
    "fallback_path": null
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `input_count` | int | 输入候选总数 |
| `filter_drops` | object | 过滤丢弃统计（当前保留为空对象占位） |
| `cache_hits` | int | 缓存命中数 |
| `cache_misses` | int | 缓存未命中数 |
| `latency_ms` | object | 各阶段耗时（键因命令而异） |
| `fallback_path` | string \| null | 降级路径标识，如 `"semantic"` |

**边界**: `diagnostics` 仅 `--explain` 请求时出现；不 `--explain` 时不存在。`latency_ms` 子键集合可能扩展，消费者应容忍未知键。

### Cache Version Governance

新增文件 `.life-index/cache/_version.json`：

```json
{
  "schema_version": "v1.1.1",
  "tool_version": "1.1.1",
  "created_at": "2026-05-23T10:00:00+00:00",
  "source_hash": "sha256:...",
  "invalidation_history": []
}
```

**CLI 入口**：

| 命令 | 行为 | 副作用 |
|------|------|--------|
| `index --cache-dry-run` | 评估当前 cache 是否需要重建，返回 `would_rebuild` / `reasons` | **零写入** |
| `health --cache-audit --json` | 返回 cache 版本只读审计状态 | **零写入** |

**失效策略**: `source_hash` mismatch 或 `schema_version` mismatch → 建议全量重建；cache 为派生产物，重建无损，不做 migration。

### Phase B Intermediate Contracts

> **适用版本**: v1.1.1+
> **范围**: Sub-PRD-3 (QueryPlan / SearchPlan / IndexManifest / EntityExpansion) + Sub-PRD-4 (Entity Graph alias metadata / boost_decay placeholder)

四个内部中间结构从 v1.1.1 起携带显式 `schema_version`，使下游消费者可前向兼容地识别字段语义。全部为 additive，不改变现有管道行为。

#### QueryPlan

`QueryPlan` 描述 smart-search planner 对查询的分解策略。

```json
{
  "schema_version": "v1.1.1",
  "raw_query": "我和女儿之间有哪些珍贵的回忆？",
  "expanded_query": "我和女儿之间有哪些珍贵的回忆？",
  "sub_queries": [],
  "strategy": "keyword_only",
  "fallback_decision": false,
  "semantic_fallback_query": null
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定为 `"v1.1.1"` |
| `raw_query` | string | 原始查询文本 |
| `expanded_query` | string \| null | 实体/别名扩展后的查询 |
| `sub_queries` | string[] | 分解后的子查询（空列表表示未分解） |
| `strategy` | string | 信号组合策略；当前运行时发出 `"keyword_only"` 或确定性多关键词策略。旧 semantic strategy 值不再由工具生成 |
| `fallback_decision` | bool | 是否选择了降级路径 |
| `semantic_fallback_query` | string \| null | Deprecated legacy 字段；当前恒为 `null` |

#### SearchPlan

`SearchPlan` 描述 L2 确定性预处理对查询的结构化理解，作为 `search` 返回值中的 `search_plan` 字段出现。

```json
{
  "schema_version": "v1.1.1",
  "raw_query": "我和女儿之间有哪些珍贵的回忆？",
  "normalized_query": "我和女儿之间有哪些珍贵的回忆",
  "intent_type": "recall",
  "query_mode": "natural_language",
  "keywords": ["女儿", "珍贵", "回忆"],
  "date_range": null,
  "topic_hints": ["family"],
  "entity_hints_used": [],
  "expanded_query": "我和女儿之间有哪些珍贵的回忆？",
  "pipelines": {"keyword": true, "semantic": false}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定为 `"v1.1.1"`（由输出层注入） |
| `raw_query` | string | 原始查询文本 |
| `normalized_query` | string | 标准化后查询（去标点、trim、全角转半角） |
| `intent_type` | string | `recall` / `count` / `compare` / `summarize` / `unknown` |
| `query_mode` | string | `keyword` / `natural_language` / `mixed` |
| `keywords` | string[] | 提取的关键词列表 |
| `date_range` | object \| null | 解析出的时间范围：`{since, until, source}` |
| `topic_hints` | string[] | 推断的主题映射 |
| `entity_hints_used` | array | 使用的实体 hint 列表 |
| `expanded_query` | string | 扩展后的查询文本 |
| `pipelines` | object | 启用的管道：`{keyword: bool, semantic: bool}` |

#### IndexManifest

`IndexManifest` 记录最后一次成功索引构建的快照，存储于索引目录的 `index_manifest.json`。

```json
{
  "fts_count": 100,
  "vector_count": 0,
  "file_count": 100,
  "fts_checksum": "abc123",
  "vector_checksum": "",
  "build_timestamp": "2026-05-23T00:00:00Z",
  "build_version": "1.1.1",
  "partial": false,
  "schema_version": "v1.1.1"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `fts_count` | int | FTS 索引文档数 |
| `vector_count` | int | Legacy compatibility 字段；当前恒为 `0` |
| `file_count` | int | 实际文件数 |
| `fts_checksum` | string | FTS 数据库 MD5 校验和 |
| `vector_checksum` | string | Legacy compatibility 字段；当前恒为空字符串 |
| `build_timestamp` | string | 构建时间（ISO 8601） |
| `build_version` | string | 构建时 Life Index 版本 |
| `partial` | bool | FTS 构建是否未完整成功；向量索引不参与判定 |
| `schema_version` | string | 固定为 `"v1.1.1"` |

#### EntityExpansion

`EntityExpansion` 携带查询实体解析阶段产生的 entity hints，作为中间结构供搜索管道消费。

```json
{
  "schema_version": "v1.1.1",
  "entity_hints": [
    {
      "matched_term": "示例别名",
      "entity_id": "EXAMPLE-PERSON-001",
      "primary_name": "示例人物",
      "entity_type": "actor",
      "expansion_terms": ["示例人物", "示例别名"],
      "reason": "alias_match"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定为 `"v1.1.1"` |
| `entity_hints` | array | 实体命中 hint 列表，每项含 `matched_term` / `entity_id` / `primary_name` / `entity_type` / `expansion_terms` / `reason` |

#### Entity Graph Alias Metadata (B4.1)

`entity_graph.yaml` 中的 `aliases` 字段从 v1.1.1 起支持两种写法，向下兼容：

**旧写法（字符串列表）** —— 加载时自动补默认元数据：

```yaml
aliases:
  - 示例别名
  - 示例称呼
```

**新写法（带元数据对象列表）** —— 显式声明来源与置信度：

```yaml
aliases:
  - name: 示例别名
    source: journal
    confidence: 0.95
    created_at: "2026-05-23T10:00:00+00:00"
  - name: 示例称呼
    source: manual
    confidence: 1.0
```

加载后每项别名均产生 `alias_metadata`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | `journal` / `wikilink` / `manual` / `system` |
| `confidence` | float | 0.0–1.0 |
| `created_at` | string | ISO 8601 时间戳 |

旧文件无 `source` 时默认 `system`，无 `confidence` 时默认 `1.0`，无 `created_at` 时默认加载时间。

#### Entity Graph Relationship Metadata (v1.2 additive)

`entity_graph.yaml` 中的 `relationships[]` 仍以 `target` 与 `relation` 为必填字段。v1.2
起支持边级可选元数据，旧裸边不强迁；加载时补默认值：

```yaml
relationships:
  - target: person-bob
    relation: friend_of
    evidence:
      - Journals/2026/07/life-index_2026-07-01_001.md
    source: review
    created_at: "2026-07-04T00:00:00+00:00"
    status: confirmed
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `target` | string | 目标实体 ID（必填） |
| `relation` | string | 关系类型（必填） |
| `evidence` | string[] | 支撑该关系的 journal rel_path 列表；旧边默认 `[]` |
| `source` | enum | `seed` / `review` / `user` / `agent` / `system`；旧边默认 `system` |
| `created_at` | string | ISO 8601 时间戳；旧边默认加载时间 |
| `status` | enum | `confirmed` / `candidate`；旧边默认 `confirmed` |
| `start` / `end` | string | 可选时间边界，不强制 |
| `weight` | number | 兼容既有可选权重 |
| `supporting_journal_ids` | string[] | 兼容既有支撑日志字段 |

`entity --review --action merge_as_alias` 会把被吸收实体的完整记录保存在目标实体的 `merged_entities[]`
墓碑中；`entity --unmerge --id MERGED_ID --target-id TARGET_ID` 用该墓碑完整复原。

#### boost_decay Echo-Only Placeholder (B4.2)

`entity --audit` 和 `entity --stats` 输出包含 `boost_decay` 字段，作为 v1.2.0 Cycle 2 校准的 schema 占位：

```json
{
  "boost_decay": {
    "formula": "1 / (1 + k * (n - 1)^2)",
    "k": 0.001,
    "note": "Placeholder constant. To be calibrated via eval gate in v1.2.0 Cycle 2."
  }
}
```

**重要**: `boost_decay` 当前仅为 echo-only 元数据，**不接入**搜索排序/BM25/RRF/校准逻辑。任何搜索排名文件不得引用 `boost_decay`。

## 错误码格式

格式：`E{module}{type}`

- **Module** (2位): 模块标识
- **Type** (2位): 错误类型

## 恢复策略

| 策略 | 说明 | Agent 行为 |
|------|------|-----------|
| `ask_user` | 需要用户干预 | 向用户展示错误并询问 |
| `skip_optional` | 可跳过的可选功能 | 跳过该功能，继续执行 |
| `continue` | 主结果/工作流可在降级状态继续 | 保留主结果并执行该错误的具体修复；若 `journal_commit` 已完成，只修复失败副作用，绝不重试 journal write |
| `continue_empty` | 无结果但可继续 | 返回空结果，不报错 |
| `fail` | 不可恢复 | 停止操作，报告错误 |
| `retry` | 可重试 | 自动重试一次，若仍失败则 `ask_user` |

## 错误码列表

### 通用错误 (E00xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0000 | 未知错误 | fail |
| E0001 | 无效输入 | ask_user |
| E0002 | 权限不足 | fail |
| E0003 | 配置错误 | fail |
| E0005 | 文件锁获取超时 | retry |
| E0006 | 文件锁获取失败 | retry |

### 文件模块 (E01xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0100 | 文件不存在 | ask_user |
| E0101 | 文件已存在 | ask_user |
| E0102 | 文件损坏 | fail |
| E0103 | 路径无效 | fail |
| E0104 | 路径遍历检测 | fail |
| E0105 | 目录不存在 | ask_user |

### 写入模块 (E02xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0200 | 写入失败 | fail |
| E0201 | 序列号错误 | fail |
| E0202 | Frontmatter 无效 | fail |
| E0203 | 内容为空 | ask_user |
| E0204 | 日期格式无效 | ask_user |
| E0205 | 附件复制失败 | continue |

### 搜索模块 (E03xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0300 | 索引不存在 | continue |
| E0301 | 搜索失败 | fail |
| E0302 | 查询为空 | ask_user |
| E0303 | 无结果 | continue_empty |

### 天气模块 (E04xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0400 | 天气 API 失败 | skip_optional |
| E0401 | 天气 API 超时 | skip_optional |
| E0402 | 地点未找到 | ask_user |
| E0403 | 天气解析错误 | skip_optional |

### 编辑模块 (E05xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0500 | 日志不存在 | ask_user |
| E0501 | 编辑冲突 | ask_user |
| E0502 | 字段不识别 | ask_user |
| E0503 | 无变更指定 | ask_user |
| E0504 | 修改地点时缺少天气 | ask_user |

### 索引模块 (E06xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0600 | 索引构建失败 | fail |
| E0601 | 索引损坏 | fail |
| E0602 | 向量存储错误 | continue |
| E0603 | FTS 索引错误 | continue |

### Web 模块 (E07xx)

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0700 | Web GUI 通用错误 | ask_user |
| E0701 | URL 附件下载失败 | skip_optional |
| E0702 | URL 文件类型被拒绝 | ask_user |
| E0703 | 所有 LLM 提供方不可用 | skip_optional |
| E0704 | LLM 元数据提取失败 | skip_optional |
| E0705 | 浏览器地理定位失败 | skip_optional |
| E0706 | Nominatim 反向地理编码失败 | skip_optional |
| E0707 | Web GUI 依赖未安装 | fail |

## JSON 返回示例

```json
{
  "success": false,
  "error": {
    "code": "E0400",
    "message": "天气 API 请求失败",
    "details": {
      "location": "Lagos, Nigeria",
      "reason": "connection_timeout"
    },
    "recovery_strategy": "skip_optional",
    "suggestion": "请手动输入天气信息，或稍后重试"
  }
}
```

---

## write_journal

### 端点

```bash
life-index write --data '<json>'
python -m tools.write_journal --data '<json>'
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| title | string | ❌ | 自动生成/调用方补齐 | 日志标题（≤20字） |
| content | string | ⚠️ workflow 通常要求 | - | 日志正文（原样保留） |
| date | string | ❌ | today | 日期（ISO 8601: YYYY-MM-DD）；省略时使用本地今天日期并记录 `field_sources.date="auto"` |
| location | string | ❌ | 默认地点兜底 | 结构化地点；trim 后非空即为权威值，仅空白或缺失时使用配置默认地点 |
| weather | string | ❌ | 自动查询/手动兜底 | 结构化天气；trim 后非空即为权威值，仅空白或缺失时按已解析地点自动查询 |
| mood | array | ❌ | [] | 心情标签 |
| people | array | ❌ | [] | 相关人物 |
| topic | array | ❌ | 调用方补齐 | 主题分类（7类之一）；LLM 提炼需显式 opt-in |
| project | string | ❌ | "" | 关联项目 |
| tags | array | ❌ | [] | 标签 |
| summary | string | ❌ | 调用方补齐 | 摘要（≤100字，**Agent生成**）；`abstract` 为向后兼容别名 |
| links | array | ❌ | [] | 相关链接 |
| related_entries | array | ❌ | [] | 关联日志相对路径（如 `Journals/2026/03/xxx.md`） |
| attachments | array | ❌ | [] | 附件列表；输入阶段支持本地路径自动检测，也支持显式对象输入；写入后以 frontmatter `attachments` 作为唯一 SSOT |

### 附件对象格式

#### 输入阶段（调用 `write_journal` 时）

```json
{
  "source_path": "C:/Users/xxx/file.png",
  "description": "附件说明",
  "content_type": "image/png",
  "size": 12345
}
```

或：

```json
{
  "source_url": "https://example.com/file.png",
  "description": "附件说明",
  "content_type": "image/png",
  "size": 12345
}
```

> `content_type` / `size` 在输入阶段均为可选；如果调用方未提供，系统会在本地文件复制或 URL 下载阶段尽力自动推断。

#### 写入后 stored attachment 对象（frontmatter `attachments`）

```json
{
  "filename": "file.png",
  "rel_path": "../../../attachments/2026/03/file.png",
  "description": "附件说明",
  "original_name": "file.png",
  "auto_detected": false,
  "source_url": "https://example.com/file.png",
  "content_type": "image/png",
  "size": 12345
}
```

> 对于本地附件，`source_url` 通常为 `null` / 缺省；对于 legacy journals，读取侧应允许 `content_type` 与 `size` 缺省，并按文件扩展名做兼容推断。

### 附件输入契约说明

- 聊天 / Agent 场景下，Life Index **保留自动从 `content` 中识别本地文件路径** 的能力
- 因此类似下面的输入仍然有效：

```text
/life-index 记日志：今天……
附件路径：C:\Users\me\Desktop\photo.png
```

- 也支持显式 `attachments` 对象输入
- 显式 `attachments` 对象既支持本地文件：`source_path`，也支持远程文件：`source_url`
- 当提供 `source_url` 时，系统会先下载远程文件，再按 Life Index 附件归档流程写入 frontmatter `attachments`
- **不要求**额外魔法词或强制 DSL 语法
- 推荐表达方式是把附件路径单独成段，以提升 Agent 解析稳定性，但这只是推荐，不是强制要求

### 附件存储契约说明

- 新 journal 写入时，附件信息仅写入 frontmatter `attachments`
- 不再自动向正文追加 `## Attachments` / `## 附件` 区块
- 读取侧应兼容：
  - legacy string attachment entries
  - structured attachment objects

### 返回值

```json
{
  "success": true,
  "write_outcome": "success_degraded",
  "journal_path": "C:/Users/.../Documents/Life-Index/Journals/2026/03/life-index_2026-03-10_001.md",
  "updated_indices": ["C:/Users/.../Documents/Life-Index/by-topic/主题_work.md"],
  "index_status": "degraded",
  "side_effects_status": "degraded",
  "side_effects": [
    {"name": "attachments", "phase": "pre_commit", "status": "complete", "blocking": true},
    {"name": "journal_stage", "phase": "pre_commit", "status": "complete", "blocking": true},
    {"name": "journal_commit", "phase": "commit", "status": "complete", "blocking": true},
    {"name": "monthly_abstract", "phase": "post_commit", "status": "complete", "blocking": false},
    {"name": "legacy_indices", "phase": "post_commit", "status": "complete", "blocking": false},
    {"name": "metadata_relations", "phase": "post_commit", "status": "complete", "blocking": false},
    {"name": "mark_pending", "phase": "post_commit", "status": "queued", "blocking": false},
    {"name": "index_b", "phase": "post_commit", "status": "complete", "blocking": false},
    {"name": "entity_candidates", "phase": "post_commit", "status": "complete", "blocking": false},
    {"name": "confirmation_snapshot", "phase": "post_commit", "status": "complete", "blocking": false}
  ],
  "attachments_processed": [...],
  "attachments_detected_count": 1,
  "attachments_processed_count": 1,
  "attachments_failed_count": 0,
  "index_b_updated": {
    "success": true,
    "updated": true,
    "artifact": "index-b"
  },
  "location_used": "Beijing, China",
  "location_auto_filled": false,
  "weather_used": "Sunny 25°C",
  "weather_auto_filled": true,
  "needs_confirmation": true,
  "confirmation": {
    "location": "Beijing, China",
    "weather": "Sunny 25°C",
    "related_candidates": [],
    "journal_path": "C:/Users/.../Documents/Life-Index/Journals/2026/03/life-index_2026-03-10_001.md",
    "supports_related_entry_approval": true
  },
  "related_candidates": [],
  "new_entities_detected": [],
  "entity_candidates": [
    {
      "text": "示例别名",
      "source": "content",
      "kind": "person",
      "matched_entity_id": "EXAMPLE-PERSON-001",
      "matched_primary_name": "示例人物",
      "suggested_action": "confirm_match",
      "risk_level": "low"
    }
  ],
  "confirmation_message": "日志已保存至：C:/Users/.../Documents/Life-Index/Journals/...",
  "error": null,
  "metrics": {"total_ms": 142.5}
}
```

### Round 7 新增返回字段

- `entity_candidates`：write-time candidate layer 输出。来自 frontmatter + 正文中的实体候选匹配；只作为候选，不直接写回 `entity_graph.yaml`
- `entity_candidates[].matched_primary_name`：当 `matched_entity_id` 非空时提供确定性显示名；未匹配时为空字符串，调用方不得从 ID 猜测人名
- `new_entities_detected`：向后兼容字段；语义比 `entity_candidates` 更粗糙，后续调用方应优先消费 `entity_candidates`

### 当前源码校验语义

- `write_journal()` 会在缺少 `date` 时使用本地今天日期；显式传入 `date` 时保持原值
- `prepare_journal_metadata()` 和直接 `write_journal()` 路径都会为自动日期记录 `field_sources.date="auto"`
- `content` 在产品 / workflow 语义上通常应提供，但并非这里定义的同级硬校验项
- `title` / `topic` / `abstract` 更准确地说是 **Agent / Web workflow 负责补齐**，不是 `write_journal()` 当前源码的硬必填

### Structured Input Authority

- Host Agent 必须把自然语言意图翻译成结构化 CLI 参数；GUI 的设备采集值与用户编辑值也必须通过同一组结构化参数传给 Core
- trim 后非空的结构化 `location` / `weather` 是权威值；只有空字符串、纯空白或缺失字段才分别允许配置地点默认值或基于已解析地点的天气查询
- Core 不解析正文中的 `地点` / `位置` / `location` / `天气` / `weather` marker 行来覆盖或补充字段；这些行始终作为普通正文逐字保留

### 写入与确认语义

- `needs_confirmation` 应视为当前写入协议中的正常后续步骤，而不是可忽略的偶发分支
- 任何 `success: true` 的写入结果都必须进入地点确认环节；Agent / Web 不得自行判断“这次可以不问”
- Host Agent / GUI 已提交的非空结构化地点和天气优先级最高；默认地点与自动天气查询只处理对应的缺失字段
- `location_auto_filled` 用于解释地点来源，不再作为是否执行确认环节的决策条件
- 如果用户要求修正地点/天气，后续应进入 correction flow，而不是把原写入描述为失败
- `confirmation` 是 machine-readable 的确认载荷；`confirmation_message` 是面向人类的展示文本
- `confirmation.supports_related_entry_approval: true` 表示调用方可在确认阶段直接批准候选 `related_candidates` 并写回 `related_entries`
- `related_candidates[*].rel_path` 是候选日志的稳定关联键；`candidate_id` 是写入响应内的展示/兼容 ID，不应在丢失写入时确认快照后重新计算使用

### 写入结果解读（Agent / Web 调用方）

| 字段 | 值 | 含义 | 调用方行为 |
|:---|:---:|:---|:---|
| `success` | true/false | 日志是否成功写入 | false → 告知用户写入失败 |
| `needs_confirmation` | true/false | 是否需要用户确认地点/天气 | true → 展示确认信息，等待用户回复 |
| `index_status` | complete/degraded/not_started | 索引更新状态 | degraded → 告知用户“已保存，但搜索可能暂时找不到” |
| `side_effects_status` | complete/degraded/not_started | 附件/摘要等副作用状态 | degraded → 告知用户“已保存，但部分信息未更新” |
| `side_effects` | array | 唯一执行记录序列；每项含 `name/phase/status/blocking`，失败项另含 `error/recovery_strategy` | 以 `journal_commit` 判断核心日志是否已 durable；只修复失败步骤，不重复写 journal |
| `weather_auto_filled` | true/false | 天气是否自动填充 | true → 在确认信息中标注“自动获取” |
| `attachments_detected_count` | int | 从正文自动检测到的本地附件路径数量 | 向用户反馈检测结果 |
| `attachments_processed_count` | int | 成功归档的附件数量 | 向用户反馈成功归档数量 |
| `attachments_failed_count` | int | 检测到但处理失败的附件数量 | >0 时提示用户检查失败附件 |

`attachments_processed` 保留成功项与失败诊断；journal frontmatter 的 `attachments`
只保存已发布且具有有效 `rel_path` 的成功项，绝不引用缺失字节。附件发布采用原子
create-only 语义；事务不会覆盖同名目标。补偿只删除仍可证明由本事务创建的文件，
staging 清理失败则以具体残留路径报告 `failed`。

**降级状态处理示例**：

```json
{
  "success": true,
  "index_status": "degraded"
}
```

`side_effects[*].status` 只允许 `complete / queued / skipped / failed / compensated`。
`queued` 只表示 pending queue 已原子落盘；搜索 preflight 尚需消费它，因此 freshness 仍为 degraded。
`compensated` 表示 pre-commit 操作曾发生但已完成补偿，journal 未提交，可在解决原始错误后重试。
`write --auto-index` 在 journal 已提交时追加 `auto_index/post_commit` 记录，并从完整
记录序列重新投影兼容摘要；未提交 journal 时不会运行 auto-index。
Dry-run 记录 `write_preview=complete`，但不伪造 `journal_commit`；其 `index_status` 仍为 `not_started`。

建议调用方表述：

> 日志已保存，但索引更新遇到问题，新日志可能暂时无法被搜索到。

### confirm 子命令

```bash
life-index confirm --journal "Journals/2026/03/life-index_2026-03-10_001.md" --location "Beijing, China" --weather "Sunny 25°C" --approve-related "Journals/2026/03/other.md"
python -m tools.write_journal confirm --journal "Journals/2026/03/life-index_2026-03-10_001.md" --location "Beijing, China" --weather "Sunny 25°C" --approve-related "Journals/2026/03/other.md"
```

- `confirm` 会调用 `apply_confirmation_updates()`
- 可同时修正 `location` / `weather`
- 可通过重复 `--approve-related` 参数批准多个候选关联日志并写回
- 可通过重复 `--approve-related-id` / `--reject-related-id` 传入候选 ID；新调用方应优先传 `--approve-related` / `--reject-related` 的 `rel_path`
- 数字候选 ID 会优先按写入时保存的确认快照解析；旧日志没有快照时，必须传回原始 `candidate_context`，不要用重新 suggest 后的候选列表替代
- 可通过重复 `--reject-related` 参数显式标记拒绝的候选关联日志
- 内部统一委托到 `edit_journal`，不另起一套写入逻辑
- 确认会原地更新指定 canonical journal，不会创建第二篇 canonical journal；既有 `edit_journal` 修订快照与派生索引副作用仍按其契约执行

### confirm 返回值

```json
{
  "success": true,
  "confirm_status": "complete",
  "journal_path": "Journals/2026/03/life-index_2026-03-10_001.md",
  "applied_fields": ["location", "weather", "related_entries"],
  "ignored_fields": [],
  "approved_related_entries": ["Journals/2026/03/other.md"],
  "requested_related_entries": ["Journals/2026/03/other.md"],
  "approved_candidate_ids": [1],
  "rejected_related_entries": ["Journals/2026/03/skip.md"],
  "rejected_candidate_ids": [2],
  "approval_summary": {
    "approved": [
      {
        "candidate_id": 1,
        "rel_path": "Journals/2026/03/other.md",
        "title": "Other"
      }
    ],
    "rejected": [
      {
        "candidate_id": 2,
        "rel_path": "Journals/2026/03/skip.md",
        "title": "Skip"
      }
    ]
  },
  "relation_summary": {
    "source_entry": {
      "rel_path": "Journals/2026/03/life-index_2026-03-10_001.md",
      "related_entries": ["Journals/2026/03/other.md"],
      "backlinked_by": []
    },
    "approved_related_context": [
      {
        "rel_path": "Journals/2026/03/other.md",
        "backlinked_by": ["Journals/2026/03/life-index_2026-03-10_001.md"]
      }
    ]
  },
  "changes": {},
  "error": null
}
```

- `confirm_status`：确认执行语义状态。`complete` = 全部请求字段都已写回；`partial` = 仅部分字段生效；`noop` = 请求已处理但没有实际变化；`failed` = 确认失败
- `applied_fields`：这次确认中实际发生写回的字段
- `ignored_fields`：本次请求里提供了，但最终未发生变化的字段（例如与原值相同）
- `approved_related_entries`：本次真正写回成功的关联日志
- `requested_related_entries`：调用方请求批准写回的关联日志列表
- `approved_candidate_ids`：本次被成功解析并批准的候选 ID；用于兼容和展示，稳定写回结果以 `approved_related_entries` 为准
- `rejected_related_entries`：本次显式拒绝的候选关联日志列表
- `rejected_candidate_ids`：本次被成功解析并拒绝的候选 ID；用于兼容和展示，稳定拒绝结果以 `rejected_related_entries` 为准
- `approval_summary`：为 GUI/service 准备的批准/拒绝摘要；每项都包含 `candidate_id/rel_path/title`
- `relation_summary`：确认完成后的新鲜关联关系摘要，避免调用方再额外跑一次 search 才知道 `related_entries/backlinked_by` 当前状态
- `relation_summary.source_entry.backlinked_by`：有哪些日志当前指向本条日志
- `relation_summary.approved_related_context[*].backlinked_by`：每个本次批准关联日志当前被哪些日志反向链接
- `changes`：来自底层 `edit_journal` 的变更明细，结构类似 `{"location": {"old": "旧值", "new": "新值"}}`
- `error`：失败时为结构化错误对象，格式与 `tools/lib/errors.py` 中的 `LifeIndexError.to_json()` 一致（含 `code/message/details/recovery_strategy/suggestion`）
- 参数命名映射：CLI 使用 `--approve-related` / `--approve-related-id` / `--reject-related` / `--reject-related-id`，schema 使用 `approve_related` / `approve_related_id` / `reject_related` / `reject_related_id`，底层 helper 使用 `approved_related_entries` / `approved_related_candidate_ids` / `rejected_related_entries` / `rejected_related_candidate_ids`

### 附件检测与处理语义

- `attachments_detected_count`：从最终 `content` 中自动检测到的本地附件路径数量
- `attachments_processed_count`：成功归档到 Life Index `attachments/` 目录的附件数量
- `attachments_failed_count`：检测到但处理失败的附件数量
- Agent / Web 成功反馈必须显式消费这些字段，不得把附件处理结果留给模型自行猜测

### 写入成功 / 降级 / 修复语义

- `side_effects` 中 `journal_commit.status == "complete"` 是核心 journal 已 durable saved 的唯一执行事实；`journal_path` 保持为兼容字段
- `needs_confirmation: true` 表示“写入成功但仍需确认/修正”，**不等于写入失败**
- journal commit 后的索引、摘要、metadata、pending、Index B 或候选池失败，应报告为“已保存，但仍有后续修复或可见性问题”；执行对应 `recovery_strategy`，只修复失败步骤，绝不得重试 journal write 或重复调用 write 创建同一篇日志
- Agent 必须保留这三种区别：
  1. 写入失败
  2. 写入成功，但仍需 confirmation / correction
  3. 写入成功，但 side effects / index visibility 不完整

### write_outcome 值定义

`write_outcome` 是兼容顶层摘要；它与 `index_status`、`side_effects_status` 都由同一 `side_effects` 执行记录序列投影。Agent 可用摘要做分支，但恢复时必须读取失败记录。

| 值 | 含义 | Agent 应做什么 |
|---|---|---|
| `success` | 全部完成 | 告知用户成功 |
| `success_pending_confirmation` | 日志已保存，地点/天气待确认 | 展示 `confirmation_message` 并等待用户回复 |
| `success_degraded` | 日志已保存，但索引/附件等后续操作部分失败 | 告知用户已保存但存在降级，建议后续修复 |
| `failed` | 写入失败 | 查看 `error` 字段的 `recovery_strategy` 决定下一步 |

推导规则（`derive_write_statuses()`）：
1. `journal_commit` 未 `complete` → `success: false`、`failed`、两个状态均 `not_started`
2. durable commit 后任一相关记录为 `failed / queued / compensated` → `success_degraded`（降级真相优先于 confirmation 摘要）
3. 无降级且 `needs_confirmation == true` → `success_pending_confirmation`
4. 以上均否 → `success`

### Tool hard-required vs workflow-required

- `docs/API.md` 描述的是 **tool contract / 运行时硬契约**
- 某些字段（如 `title` / `abstract` / `topic` / `mood` / `tags`）在产品 workflow 中通常应由 Agent 或 Web 层补齐
- 但这不自动等同于 `write_journal()` 当前源码层面的硬校验必填
- 如两者需要同时表述，应优先区分：
  1. **tool hard-required**（工具自身拒绝缺失）
  2. **workflow-required**（调用方在进入工具前应补齐）

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0001 | 必填参数缺失 | ask_user |
| E0203 | content 为空 | ask_user |
| E0204 | 日期格式无效 | ask_user |
| E0205 | 附件复制失败 | continue |
| E0400 | 天气 API 失败 | skip_optional |

---

## attachment

### 端点

```bash
life-index attachment --info <path>
life-index attachment --export <path>
life-index attachment media <path> [--variant thumbnail|preview|original] [--max-px N] [--output PATH|-]
python -m tools attachment --info <path>
python -m tools attachment --export <path>
python -m tools attachment media <path> [--variant thumbnail|preview|original] [--max-px N] [--output PATH|-]
python -m tools.attachment media <path> [--variant thumbnail|preview|original] [--max-px N] [--output PATH|-]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--info` | string | 与 `--export` 二选一 | - | 返回附件元数据，不包含字节内容 |
| `--export` | string | 与 `--info` 二选一 | - | 返回附件元数据与 base64 编码字节内容 |

`<path>` 必须指向 Life Index `attachments/` 内的附件引用。支持三类输入：

- `2026/05/photo.png`
- `attachments/2026/05/photo.png`
- frontmatter 中保存的历史相对形式：`../../../attachments/2026/05/photo.png`

绝对路径、空路径、NUL 字节、以及会逃逸出 `attachments/` 根目录的路径遍历输入必须被拒绝。

### Media raw/file-export contract

`attachment media` 是面向 GUI/backend 与 host agent 的 raw bytes 媒体契约。
它不替代 `--export`；旧 `--export` 继续返回 JSON/base64。新契约用于
thumbnail/preview/original 的 file-export 或 stdout streaming，避免把新媒体主路径
建立在 base64 JSON 上。

```bash
life-index attachment media attachments/2026/05/photo.png --variant thumbnail --output thumb.png
life-index attachment media attachments/2026/05/photo.png --variant preview --max-px 1400 --output preview.png
life-index attachment media attachments/2026/05/video.mp4 --variant original --range bytes=0-1023 --output -
```

参数：

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| positional `<path>` | string | ✅ | - | 附件引用，规则同 `--info` / `--export` |
| `--variant` | enum | ❌ | `original` | `thumbnail`、`preview` 或 `original` |
| `--max-px` | int | ❌ | thumbnail=160；preview=1400 | thumbnail/preview 最大宽高；`original` 忽略 |
| `--output` | path 或 `-` | ❌ | `-` | 输出文件；`-` 表示 raw bytes 写 stdout |
| `--metadata-output` | path | ❌ | - | stdout streaming 时把 JSON metadata 写入此文件 |
| `--range` | string | ❌ | - | 仅 `original` 支持单段 byte range，如 `bytes=0-1023` |
| `--chunk-size` | int | ❌ | 1048576 | stdout/file streaming chunk 大小 |

当 `--output` 是文件路径时，命令把 bytes 写入该文件，并在 stdout 返回 metadata：

```json
{
  "success": true,
  "schema_version": "m17.attachment-media.v1",
  "data": {
    "rel_path": "attachments/2026/05/photo.png",
    "filename": "photo.png",
    "variant": "preview",
    "max_px": 1400,
    "content_type": "image/png",
    "size": 34567,
    "sha256": "hex-encoded-output-sha256",
    "source": {
      "size": 1234567,
      "sha256": "hex-encoded-source-sha256",
      "mtime_ns": 1790000000000000000
    },
    "cache": {
      "eligible": true,
      "hit": false,
      "key": "deterministic-cache-key",
      "implementation": "v1"
    },
    "stream": {
      "status_code": 200,
      "range": null
    },
    "headers": {
      "Content-Type": "image/png",
      "Content-Length": "34567",
      "ETag": "\"sha256-hex-encoded-source-sha256\"",
      "Cache-Control": "private, max-age=3600",
      "Content-Disposition": "attachment; filename=\"photo.png\"; filename*=UTF-8''photo.png"
    },
    "output": "preview.png"
  },
  "error": null
}
```

When `--output -` is used, stdout is raw bytes only. Use `--metadata-output`
to receive the same JSON metadata as a sidecar file. GUI/backend consumers
should forward `headers` into their own HTTP response and stream stdout/file
bytes without directly reading the Life Index data directory.

`original` supports range streaming. A satisfiable range reports
`stream.status_code = 206` and includes `Content-Range`; invalid ranges fail
with `ATTACHMENT_RANGE_INVALID`.

`thumbnail` and `preview` are deterministic image derivatives. They are cached
under the Life Index cache directory, never in `Journals/` or the attachment
source directory. The cache key includes the attachment reference, source
content hash, source size/mtime, variant, max-px, output format, and
implementation version, so source changes invalidate cached derivatives.

### 返回值

`--info`：

```json
{
  "success": true,
  "schema_version": "m16.attachment.v0",
  "data": {
    "rel_path": "attachments/2026/05/photo.png",
    "filename": "photo.png",
    "content_type": "image/png",
    "size": 12345
  },
  "error": null
}
```

`--export` 在 `--info` 字段基础上增加：

```json
{
  "sha256": "hex-encoded-sha256",
  "content_base64": "..."
}
```

### 错误行为

错误以 JSON 输出到 stdout，并以非零状态码退出：

```json
{
  "success": false,
  "schema_version": "m16.attachment.v0",
  "data": null,
  "error": {
    "code": "ATTACHMENT_NOT_FOUND",
    "message": "Attachment file was not found."
  }
}
```

当前错误码：

| code | 说明 |
|------|------|
| `ATTACHMENT_PATH_INVALID` | 路径为空、绝对路径、包含 NUL、路径遍历，或解析后不在 `attachments/` 根目录内 |
| `ATTACHMENT_NOT_FOUND` | 附件文件不存在 |
| `ATTACHMENT_NOT_FILE` | 附件引用不是文件 |
| `ATTACHMENT_READ_FAILED` | 读取附件时发生 OS 错误 |
| `ATTACHMENT_UNSUPPORTED_MEDIA` | 请求 thumbnail/preview 但附件不是支持的图片媒体 |
| `ATTACHMENT_DECODE_FAILED` | 图片媒体解码失败 |
| `ATTACHMENT_RANGE_INVALID` | byte range 语法无效、越界，或用于非 `original` variant |
| `ATTACHMENT_DATA_DIR_INVALID` | validation mode 或数据目录边界拒绝当前数据目录 |
| `ATTACHMENT_MEDIA_INVALID` | media 参数无效，例如 `--max-px <= 0` 或 `--chunk-size <= 0` |

### schema_version Policy

`attachment --info` and `attachment --export` emit top-level
`schema_version = "m16.attachment.v0"`. `attachment media` emits
`schema_version = "m17.attachment-media.v1"`. Top-level fields and `data` field
names are stable; additive metadata fields may be added without a version bump.
A version bump will accompany any backward-incompatible payload change.

---

## journal

### 端点

```bash
life-index journal get --path <rel-path>
life-index journal get --id <journal-id>
life-index journal batch-get --path <rel-path> [--path <rel-path> ...]
life-index journal list --recent [--limit <n>] [--offset <n>]
python -m tools journal get --path <rel-path>
python -m tools journal batch-get --path <rel-path> --path <rel-path>
python -m tools journal list --recent
```

`journal` 是面向 GUI / 高级模块消费者的只读 journal 读取契约。它不修改
`Journals/`、索引、附件或 entity graph。

### 参数

#### `journal get`

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--path` | string | 与 `--id` 二选一 | - | journal 相对路径，必须形如 `Journals/YYYY/MM/life-index_YYYY-MM-DD_NNN.md` |
| `--id` | string | 与 `--path` 二选一 | - | v0 journal id；当前等同于 `rel_path` |
| `--json` | flag | 否 | false | 兼容参数；当前输出始终为 JSON |

#### `journal batch-get`

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--path` | string[] | 与 `--id` 至少一项 | - | journal 相对路径，可重复；每项必须匹配 `journal get` 路径规则 |
| `--id` | string[] | 与 `--path` 至少一项 | - | v0 journal id，可重复；当前等同于 `rel_path` |
| `--json` | flag | 否 | false | 兼容参数；当前输出始终为 JSON |

#### `journal list --recent`

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--recent` | flag | 是 | - | 按日期 + 序号倒序返回真实 journal 文件 |
| `--limit` | int | 否 | 20 | 返回条数；`0` 表示不限制当前页大小 |
| `--offset` | int | 否 | 0 | 分页偏移量 |
| `--json` | flag | 否 | false | 兼容参数；当前输出始终为 JSON |

### 路径与身份语义

- `rel_path` 是相对 `LIFE_INDEX_DATA_DIR` 的稳定路径，使用 `/` 分隔符。
- v0 `id` 等同于 `rel_path`。未来若引入 durable id，会通过新的
  `schema_version` 或 additive 字段迁移，消费者不应自行猜测新 id。
- `--path` / `--id` 拒绝空路径、绝对路径、NUL 字节、路径遍历，以及不匹配
  `Journals/YYYY/MM/life-index_YYYY-MM-DD_NNN.md` 的输入。
- `journal list --recent` 只扫描 `Journals/YYYY/MM/life-index_*.md`，不会返回
  `INDEX.md`、topic/year/month 派生索引或其他非 journal 文件。

### `journal get` 返回值

```json
{
  "success": true,
  "schema_version": "m16.journal.v0",
  "data": {
    "id": "Journals/2026/05/life-index_2026-05-28_001.md",
    "rel_path": "Journals/2026/05/life-index_2026-05-28_001.md",
    "journal_route_path": "2026/05/life-index_2026-05-28_001.md",
    "metadata": {
      "title": "示例日志",
      "date": "2026-05-28",
      "attachments": []
    },
    "content": "# 示例日志\n\n正文内容",
    "attachments": [],
    "word_count": 3
  },
  "error": null
}
```

字段语义：

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.id` | string | v0 journal id，当前等同于 `rel_path` |
| `data.rel_path` | string | 相对 `LIFE_INDEX_DATA_DIR` 的 journal 路径 |
| `data.journal_route_path` | string | 去掉 `Journals/` 前缀后的路由友好路径 |
| `data.metadata` | object | frontmatter 解析结果 |
| `data.content` | string | journal 正文，不含 frontmatter |
| `data.attachments` | array | 从 frontmatter `attachments` 规范化后的附件元数据 |
| `data.word_count` | int | 基于正文的轻量计数：CJK 字符按字符计，非 CJK 字母数字连续片段按词计；纯非 CJK 文本保持空白分词口径 |

附件项字段与 `attachment` 读取侧一致，当前包含
`raw_path`、`path`、`name`、`description`、`source_url`、`content_type`、`size`。

### `journal batch-get` 返回值

`batch-get` 是 `journal get` 的有界批量形态，用于 agent 在确定性窄化后减少
多次 CLI 往返。它复用同一套路径校验与读取语义，不做排序、筛选或事实判断。

```json
{
  "success": true,
  "schema_version": "m16.journal.v0",
  "data": {
    "items": [
      {
        "id": "Journals/2026/05/life-index_2026-05-28_001.md",
        "rel_path": "Journals/2026/05/life-index_2026-05-28_001.md",
        "journal_route_path": "2026/05/life-index_2026-05-28_001.md",
        "metadata": {"title": "示例日志", "date": "2026-05-28"},
        "content": "# 示例日志\n\n正文内容",
        "attachments": [],
        "word_count": 3
      }
    ],
    "total_requested": 1,
    "total_found": 1,
    "max_items": 50
  },
  "error": null
}
```

### `journal list --recent` 返回值

```json
{
  "success": true,
  "schema_version": "m16.journal.v0",
  "data": {
    "items": [
      {
        "id": "Journals/2026/05/life-index_2026-05-28_001.md",
        "rel_path": "Journals/2026/05/life-index_2026-05-28_001.md",
        "journal_route_path": "2026/05/life-index_2026-05-28_001.md",
        "title": "示例日志",
        "date": "2026-05-28",
        "metadata": {},
        "attachments": [],
        "word_count": 3
      }
    ],
    "total_matches": 1,
    "total_found": 1,
    "limit": 20,
    "offset": 0,
    "has_more": false,
    "sort": "date_desc"
  },
  "error": null
}
```

列表项不返回 `content`，用于目录、最近日志列表和后续 `journal get` 导航。
`total_matches` 是分页前匹配总数，`total_found` 是本次返回条数。

### 错误行为

错误以 JSON 输出到 stdout，并以非零状态码退出：

```json
{
  "success": false,
  "schema_version": "m16.journal.v0",
  "data": null,
  "error": {
    "code": "JOURNAL_NOT_FOUND",
    "message": "Journal file was not found."
  }
}
```

当前错误码：

| code | 说明 |
|------|------|
| `JOURNAL_PATH_INVALID` | journal 引用为空、绝对路径、包含 NUL、路径遍历，或不匹配 journal 路径格式 |
| `JOURNAL_NOT_FOUND` | journal 文件不存在 |
| `JOURNAL_ARGUMENT_INVALID` | `list` 参数无效，例如负数 `--limit` / `--offset` |
| `JOURNAL_BATCH_TOO_LARGE` | `batch-get` 请求超过单次批量读取上限 |
| `JOURNAL_READ_FAILED` | 读取 journal 时发生 OS 错误 |

### schema_version Policy

`journal` emits top-level `schema_version = "m16.journal.v0"`.
Top-level fields and `data` field names are stable; additive metadata fields may
be added without a version bump. A version bump will accompany any
backward-incompatible payload change.

---

## index-tree

### 端点

```bash
life-index index-tree materialize --from 2026-03 --to 2026-06 --json
life-index index-tree materialize --from 2026-03 --to 2026-06 --incremental --json
life-index index-tree freshness --from 2026-03 --to 2026-06 --json
life-index index-tree ensure --from 2026-03 --to 2026-06 --json
life-index index-tree discover --from 2026-03 --to 2026-06 --facet location --facet project --json
life-index index-tree navigate --from 2026-03 --to 2026-06 --filter "location=London, United Kingdom" --filter "project=Life Index" --json
life-index index-tree navigate --entity-neighbors "Alice" --entity-relation works_on --json
python -m tools index-tree navigate --from 2026-03 --to 2026-06 --filter "project=Life Index" --json
```

`index-tree` 是 Index Tree Evidence Navigation 公共契约。Canonical navigation
主路径是 Index B 物化、freshness guard、facet 值发现、结构化导航和显式 entity-neighbor 遍历，供 host
agent 做有界候选集规划和读取。`nodes`、`lens`、`shadow` 是 debug-only legacy
诊断接口：保留兼容和内部排障，不作为 host-agent retrieval/navigation playbook，不应出现在
agent 面向的主流程示例中。

`nodes`、`lens`、`shadow` 不会写入或修改 journal、index、cache、attachment 或任何
durable data。`materialize` 只写 `.life-index/index-b/` 下可重建的导航文档和
`manifest.json` 哈希清单，不写 journal、attachment 或 durable truth source。
`freshness` 只读并比较 journal 内容哈希；`ensure` 在 Index B 缺失或陈旧时尝试刷新，
并在成功刷新后报告刷新后的 `freshness`。刷新失败则返回 journal fallback pointers。`discover` 只枚举调用方请求的 facet 值菜单；
`navigate` 只执行调用方给定的结构化谓词，不会从自然语言推断 facet、实体或关系。Journal 仍是唯一
truth source；index、lens、shadow report、Index B docs 和 manifest 都是可重建派生产物。

### 通用返回 Envelope

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.nodes",
  "generated_at": "2026-05-31T00:00:00Z",
  "data": {},
  "errors": []
}
```

错误时：

```json
{
  "success": false,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.lens",
  "generated_at": "2026-05-31T00:00:00Z",
  "data": null,
  "errors": [
    {
      "code": "INDEX_TREE_INVALID_SIGNAL",
      "message": "signal must be one of ['topic', 'people', 'project'], got 'mood'",
      "details": {"signal": "mood", "allowed": ["topic", "people", "project"]}
    }
  ]
}
```

### Debug-only legacy diagnostics

以下接口保留用于兼容、内部诊断和回归测试。Host-agent 查询流程应使用
`ensure`、`discover`、`navigate`；不要把 `nodes`、`lens`、`shadow` 当作事实检索、
facet 导航或 ranking API。

```bash
life-index index-tree nodes --level all --json
life-index index-tree nodes --level month --json
life-index index-tree lens --signal topic --json
life-index index-tree lens --signal people --json
life-index index-tree lens --signal project --json
life-index index-tree shadow --query "Alpha" --json
python -m tools index-tree nodes --level month --json
```

### `nodes`

`nodes` 是 debug-only legacy 诊断接口。它输出 root/year/month 节点摘要、
freshness、entry refs 和可导航 frontmatter 信号。所有路径均为相对
`LIFE_INDEX_DATA_DIR` 的 POSIX-style 路径；不得出现绝对路径。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.nodes",
  "data": {
    "truth_source": "journals",
    "level": "month",
    "nodes": [
      {
        "node_id": "month:2026-03",
        "level": "month",
        "relative_path": "Journals/2026/03/index_2026-03.md",
        "entry_count": 1,
        "freshness": "fresh",
        "entry_refs": [
          {
            "relative_path": "Journals/2026/03/life-index_2026-03-14_001.md",
            "signals": {"topic": ["work"]},
            "node_ref": {
              "type": "month",
              "node_id": "month:2026-03",
              "id": "Journals/2026/03",
              "path": "Journals/2026/03/index_2026-03.md"
            }
          }
        ],
        "signal_coverage": {
          "topic": {"entries_in_scope": 1, "present": 1, "parseable": 1}
        }
      }
    ]
  },
  "errors": []
}
```

### `lens`

`lens` 是 debug-only legacy 诊断接口。它输出 `topic`、`people`、`project`
三类 allowlisted frontmatter signal 的跨时间派生视图。它是 diagnostic aid，不是
事实裁决、host-agent 导航主路径或 persona/relationship judgment。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.lens",
  "data": {
    "truth_source": "journals",
    "privacy_level": "same_as_journals",
    "signal": "topic",
    "coverage": {"entries_in_scope": 2, "present": 2, "parseable": 2},
    "items": [
      {
        "value": "work",
        "count": 1,
        "node_refs": [{"type": "month", "node_id": "month:2026-03"}],
        "evidence_paths": ["Journals/2026/03/life-index_2026-03-14_001.md"],
        "freshness": ["fresh"]
      }
    ]
  },
  "errors": []
}
```

### `shadow`

`shadow` 是 debug-only legacy 诊断接口。它输出 Search Shadow Mode 诊断。它只报告
candidate narrowing、baseline subset 检查、stale/missing index disable reason 和
dropped-path evidence；不会改变 `search` 或 `smart-search` 默认 ranking / order /
output semantics，也不是 ranking API。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.shadow",
  "data": {
    "query": "Alpha",
    "enabled": true,
    "diagnostic_only": true,
    "baseline_paths": ["Journals/2026/03/life-index_2026-03-14_001.md"],
    "shadow_candidate_paths": ["Journals/2026/03/life-index_2026-03-14_001.md"],
    "recall_preserved": true,
    "dropped_paths": [],
    "default_search_mutated": false,
    "default_smart_search_mutated": false
  },
  "errors": []
}
```

### `materialize`

`materialize` 为指定月份范围写入确定性 Index B facet 导航文档。输出目录固定为
`.life-index/index-b/`，以 root/year/month 三层组织。文档包含
weather/location/topic/project/tag/people facet 的计数，以及指向下层导航文档或 journal
条目的相对路径。它同时写入 `manifest.json`，记录每个 root/year/month scope 的
journal 内容哈希和文档哈希。它不做 LLM 摘要，不改变 search / smart-search ranking。
带 `--incremental` 时，只重写陈旧 scope 及其受影响祖先，不重写仍 fresh 的 sibling
月份文档。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.materialize",
  "data": {
    "truth_source": "journals",
    "artifact": "index-b",
    "schema_version": "m31.index_tree.index_b.v0",
    "output_dir": ".life-index/index-b",
    "date_from": "2026-03",
    "date_to": "2026-06",
    "entry_count": 42,
    "year_count": 1,
    "month_count": 4,
    "facets": ["weather", "location", "topic", "project", "tag", "people"],
    "written_docs": [
      ".life-index/index-b/INDEX.md",
      ".life-index/index-b/Journals/2026/index.md",
      ".life-index/index-b/Journals/2026/03/index.md",
      ".life-index/index-b/manifest.json"
    ],
    "skipped_fresh_docs": [],
    "incremental": false,
    "freshness_before": {
      "fresh": false,
      "stale_scopes": ["root", "year:2026", "month:2026-03"],
      "fresh_scopes": [],
      "removed_scopes": [],
      "manifest_present": false
    },
    "dry_run": false
  },
  "errors": []
}
```

### `freshness`

`freshness` 只读当前 journals 和 `.life-index/index-b/manifest.json`，重算每个
root/year/month scope 的 source hash。任何 journal 内容哈希、生成文档哈希、范围或
scope 缺失不匹配都会标为 stale。它不写入任何文件。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.freshness",
  "data": {
    "truth_source": "journals",
    "artifact": "index-b",
    "schema_version": "m31.index_tree.index_b.manifest.v0",
    "date_from": "2026-03",
    "date_to": "2026-06",
    "entry_count": 42,
    "year_count": 1,
    "month_count": 4,
    "fresh": false,
    "stale_scopes": ["root", "year:2026", "month:2026-03"],
    "fresh_scopes": ["month:2026-04", "month:2026-05", "month:2026-06"],
    "removed_scopes": [],
    "reasons": {"month:2026-03": "source_hash_mismatch"},
    "manifest_present": true
  },
  "errors": []
}
```

### `ensure`

`ensure` 是 consumer-friendly guard。它先执行 freshness check；若 Index B 陈旧或缺失，
则尝试 `materialize --incremental`。刷新成功时返回 `source: "index-b"`，
`freshness_before` 保存刷新前状态，`freshness` 保存刷新后状态。如果刷新失败，返回
`source: "journals"` 和 journal entry pointers，调用方应直接读取这些 journal 条目，
而不是把 Index B 缺失当作查询失败。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.ensure",
  "data": {
    "source": "journals",
    "artifact": "index-b-fallback",
    "date_from": "2026-03",
    "date_to": "2026-03",
    "entry_count": 1,
    "entries": [
      {
        "date": "2026-03-14",
        "title": "Fallback Work",
        "path": "Journals/2026/03/life-index_2026-03-14_001.md"
      }
    ],
    "fallback": {"used": true, "reason": "refresh failed"}
  },
  "errors": []
}
```

### `discover`

`discover` 在月份范围内返回一个紧凑的 facet 值菜单，供调用方 agent 自己选择相关值。
它只接受显式 facet 名称，不接受自然语言查询，不做相关性判断。当前支持的 facet 与
Index B 文档一致：`weather`、`location`、`topic`、`project`、`tag`、`people`。
默认菜单只包含这些前台元数据 facet。调用方也可以显式请求 `content_term`，返回指定
月份范围内 journal 标题和正文中已经出现的词项；这些值是语料观察结果，不是同义词、
概念词表或自然语言推断。遇到概念类问题时，调用方应先检查实际 facet 值菜单并从数据中
选择匹配值，不预设任何特定主题词表。

`project`、`people`、`location` 和 `tag` facet 会使用用户数据目录中的
`entity_graph.yaml` 显式 `primary_name` / `aliases` 做确定性规范化：`project` 只使用
project 实体，`people` 只使用 person 实体，`location` 只使用 place 实体，`tag` 允许所有
实体类型的精确图谱标签。`topic` 与 `weather` 不做规范化。无映射值保留 trim 后原值；
lookup key 使用 trim、空白折叠和 `casefold()`，但 canonical 输出保留图谱
`primary_name` 的原大小写。歧义 label fail-closed 为原值并在
`canonicalization.diagnostics` 中报告。图谱缺失或加载失败不会阻断导航；加载失败时
规范化降级为 no-op 并输出诊断。

自 Phase 2B 起，顶层 `exhaustive` 由枚举事实推导而非硬编码 `true`：范围扫描完整执行
且未跳过任何候选时为 `true`；否则为 `false`，并在原生 `exhaustive_reasons` 数组中逐项
列出被跳过候选的 `{path, reason}`。同一响应还携带同语汇的 `retrieval_coverage`
（`retrieval_coverage.v1`）对象：`complete`/`partial` 与 `exhaustive` 一致，
`observed_total` 与 `returned` 均等于进入响应的范围条目数，`next_offset` 恒为 `null`
（无分页）。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.discover",
  "data": {
    "truth_source": "journals",
    "privacy_level": "same_as_journals",
    "source": "index-b",
    "artifact": "index-b",
    "date_from": "2026-03",
    "date_to": "2026-06",
    "operation_model": "deterministic_navigation.v1",
    "selection_contract": "host_agent_selects_values; tool_executes_only",
    "exhaustive": true,
    "exhaustive_reasons": [],
    "facets": {
      "location": {
        "facet": "location",
        "value_count": 1,
        "values": [
          {
            "value": "London, United Kingdom",
            "count": 2,
            "sample_entry_pointers": [
              "Journals/2026/03/life-index_2026-03-14_001.md"
            ],
            "raw_values": ["London, United Kingdom"]
          }
        ]
      }
    },
    "canonicalization": {
      "status": "active",
      "canonicalization_hash": "sha256-like-hex",
      "diagnostics": []
    },
    "coverage": {"candidate_count": 2, "facet_count": 1},
    "retrieval_coverage": {
      "schema_version": "retrieval_coverage.v1",
      "status": "complete",
      "observed_total": 2,
      "returned": 2,
      "next_offset": null,
      "partial_reasons": [],
      "limits_applied": []
    },
    "navigation_docs": [".life-index/index-b/INDEX.md"],
    "extension_points": ["entity_neighbors"]
  },
  "errors": []
}
```

### `navigate`

`navigate` 在已物化的 Index B 范围上执行确定性结构化导航。它只接受显式谓词：
`--filter facet=value`，重复 `--filter` 表示跨 facet 交集，同一个 filter 内的
`value1||value2` 表示该 facet 的确定性 OR。当前支持的 facet 与 Index B 文档一致：
`weather`、`location`、`topic`、`project`、`tag`、`people`。`content_term` 也可作为
显式过滤 facet，用于匹配调用方已从 `discover --facet content_term`、`search` 或其他
确定性读取中观察到的正文词项。工具不会从自然语言推断应该查哪个 facet；调用方 agent
负责规划和选择谓词。

facet filter 与 `discover` 使用同一套确定性规范化。调用方可以传规范名或显式 alias；
工具会在执行谓词前映射到同一 canonical value。alias lookup 大小写不敏感，显示值保留
图谱 `primary_name` 的原样大小写。规范化不改变 journal 事实来源，不猜测未写入图谱的
同义词，也不做模糊或标点启发式合并。`content_term` 是正文观察词，不使用
`entity_graph.yaml` alias 规范化。

关系型问题可使用同级确定性 op：`--entity-neighbors ENTITY`。调用方 agent 选择实体、
可选 `--entity-relation RELATION` 和 `--entity-max-hops N`；工具只遍历
`entity_graph.yaml` 中显式存在的关系边，返回相邻实体、连接边、关系类型、权重和边上
已经记录的 `supporting_journal_ids`。如果当前 graph 边没有支撑 journal id，工具不会猜测
journal 候选，`entry_pointers` 可为空；调用方可用返回的实体邻居继续规划下一步确定性读取或
搜索。

`navigate` 先执行 `ensure`。Index B fresh 或成功刷新时返回 `source: "index-b"` 和
本次范围涉及的 `navigation_docs`；刷新失败时可返回 journal fallback source。返回的
`entry_pointers` 是候选 journal 路径，调用方仍需用 `journal batch-get` 或 `journal get`
读取 journal 内容后才能引用为事实证据。
与 `discover` 相同，顶层 `exhaustive` 自 Phase 2B 起由枚举事实推导而非硬编码 `true`：
枚举完整执行且无跳过候选才为 `true`，否则为 `false` 并在原生 `exhaustive_reasons`
数组中逐项列出跳过项的 `{path, reason}`；同响应携带同语汇的 `retrieval_coverage`
对象（`complete`/`partial` 与 `exhaustive` 一致；`observed_total`=`returned`=进入响应
的范围条目数；`next_offset` 恒为 `null`）。注意区分：`entity_neighbors[]` 内每个操作
自带的 `exhaustive` 描述的是该次实体图遍历是否因 limit 截断，与本响应级枚举穷尽性是
两个不同字段。
对于干净的 facet 计数或枚举问题，当响应级 `exhaustive` 为 `true`（即
`retrieval_coverage.status` 为 `"complete"`）时，`count`、`entries` 和 `entry_pointers`
是穷尽候选源；调用方应仅读取支撑答案所需的有界 journal 条目（例如边界日期、代表条目
或用于消除日期缺口歧义的条目），不应在成功穷尽导航后默认重启宽泛搜索；
`exhaustive=false` 时应先核对 `exhaustive_reasons` 再决定下一步。

```json
{
  "success": true,
  "schema_version": "m31.index_tree.v1",
  "command": "index-tree.navigate",
  "data": {
    "truth_source": "journals",
    "privacy_level": "same_as_journals",
    "source": "index-b",
    "artifact": "index-b",
    "date_from": "2026-03",
    "date_to": "2026-06",
    "operation_model": "deterministic_navigation.v1",
    "operations": [
      {
        "type": "facet_value_filter",
        "facet": "location",
        "values": ["London, United Kingdom"],
        "match": "any"
      },
      {
        "type": "facet_value_filter",
        "facet": "project",
        "values": ["Life Index"],
        "match": "any"
      },
      {
        "type": "entity_neighbors",
        "entity": "Alice",
        "max_hops": 1,
        "relations": ["works_on"]
      }
    ],
    "implemented_extensions": ["entity_neighbors"],
    "exhaustive": true,
    "exhaustive_reasons": [],
    "count": 1,
    "entry_pointers": ["Journals/2026/03/life-index_2026-03-14_001.md"],
    "entries": [
      {
        "date": "2026-03-14",
        "title": "Facet Work",
        "path": "Journals/2026/03/life-index_2026-03-14_001.md",
        "matched_facets": {
          "location": ["London, United Kingdom"],
          "project": ["Life Index"]
        }
      }
    ],
    "entity_neighbors": [
      {
        "query": "Alice",
        "status": "ok",
        "resolved_entity": {
          "id": "person-alice",
          "type": "actor",
          "attributes": {"kind": "human"},
          "primary_name": "Alice",
          "aliases": []
        },
        "max_hops": 1,
        "relations": ["works_on"],
        "exhaustive": true,
        "neighbor_count": 1,
        "neighbors": [
          {
            "entity_id": "project-atlas",
            "entity_type": "project",
            "primary_name": "Atlas",
            "aliases": [],
            "hops": 1,
            "edges": [
              {
                "source": "person-alice",
                "target": "project-atlas",
                "relation": "works_on",
                "direction": "outgoing",
                "weight": 1.0,
                "supporting_journal_ids": [
                  "Journals/2026/03/life-index_2026-03-14_001.md"
                ]
              }
            ]
          }
        ]
      }
    ],
    "navigation_docs": [
      ".life-index/index-b/INDEX.md",
      ".life-index/index-b/Journals/2026/index.md",
      ".life-index/index-b/Journals/2026/03/index.md"
    ],
    "coverage": {
      "candidate_count_before_filters": 2,
      "candidate_count_after_filters": 1,
      "filter_count": 3,
      "facet_filter_count": 2,
      "entity_neighbor_operation_count": 1,
      "entity_neighbor_supporting_journal_count": 1
    },
    "retrieval_coverage": {
      "schema_version": "retrieval_coverage.v1",
      "status": "complete",
      "observed_total": 2,
      "returned": 2,
      "next_offset": null,
      "partial_reasons": [],
      "limits_applied": []
    },
    "fallback": {"used": false, "reason": null},
    "extension_points": ["entity_neighbors"]
  },
  "errors": []
}
```

### GUI / Consumer 边界

- GUI 只能消费 `index-tree` public JSON envelope；不得读取私有开发 artifact。
- GUI 不得把 lens / shadow diagnostic 当作 truth claim；展示时应保留 evidence paths / node refs。
- GUI 不得绕过 CLI 写入 `Journals/`、`attachments/` 或任何 durable data。
- `frontmatter_signals`、lens value、people/project/location 等 key 可能含真实人名、项目名或地点；隐私等级等同 journal。
- `shadow` 仅诊断，不是 ranking API。任何 search / smart-search ranking 变更必须另走授权和 recall-preservation gate。

### schema_version Policy

`index-tree` emits top-level `schema_version = "m31.index_tree.v1"`.
Existing fields and semantics are stable. Additive optional fields may be added
without a schema bump. Backward-incompatible shape or semantic changes require
a new schema version.

---

## import

### 端点

```bash
life-index import plan --source fixture.import_records --input <fixture.json> --json
life-index import plan --source media.photo_timeline --input <photo-dir> --json
life-index import run --plan <plan.json> --confirm <import_id> --json
life-index import run --plan <plan.json> --confirm <import_id> --source-root <photo-dir> --json
life-index import status --import-id <import_id> --json
life-index import rollback --import-id <import_id> --json
python -m tools import plan --source fixture.import_records --input <fixture.json> --json
```

`import` 是 Tranche A batch import provider contract。它是 durable journal /
attachment 写入的唯一 owner；GUI 或高级模块只能消费 plan、请求 confirmed
run、查询 status、触发 rollback，不能直接写 `Journals/` 或 `attachments/`。

当前 source adapters：

| source | 输入 | 状态 | 说明 |
|---|---|---|---|
| `fixture.import_records` | fixture JSON | Tranche A stable | contract tests 和后续 adapter 对齐用 fixture adapter |
| `media.photo_timeline` | 本地 JPEG 目录 | Tranche B additive | 通过 Pillow 读取 JPEG EXIF，生成照片 timeline import proposals |

`media.photo_timeline` 支持 `.jpg` / `.jpeg`。它提取 capture time、GPS
（可选）、camera make/model（可选）、orientation、content SHA-256、
size、media type，并生成 deterministic journal + attachment proposal。
`import plan` 不写 durable data，不暴露绝对 source path；attachment 中的
`source_rel_path` 只是相对 `--source-root` 的文件名/相对路径，用于
`import run` 复制原始照片字节。社媒 export parsing、Google Photos sidecar
解析、AI drafting、GUI flow 不属于当前命令契约。

### 通用返回 Envelope

所有 `import` 子命令返回同一 envelope：

```json
{
  "schema_version": "import_job.v1",
  "success": true,
  "command": "import.plan",
  "data": {},
  "error": null
}
```

失败时：

```json
{
  "schema_version": "import_job.v1",
  "success": false,
  "command": "import.rollback",
  "data": null,
  "error": {
    "code": "IMPORT_ROLLBACK_CHECKSUM_MISMATCH",
    "message": "Rollback blocked.",
    "details": {},
    "retryable": false
  }
}
```

### `import_id` lexical contract

所有外部 `import_id` 与 plan 内的 `import_id` 在任何 per-parent path/lock、
review-plan、rollback manifest、ledger state 或 durable data 访问前，先做纯 lexical
校验（外层 transaction 取得 data-dir 内固定
`.life-index/import-jobs/ledger.lock` 及创建其父目录仍被允许）：

- parent：lowercase ASCII `[a-z0-9][a-z0-9_-]*`，长度 1..128；
  `CON` / `PRN` / `AUX` / `NUL` / `COM1..9` / `LPT1..9` 大小写不敏感地保留；
- child：`<valid-parent>#batch-[1-9][0-9]{0,8}`，parent 部分长度 1..128、整体总长
  不超过 144（parent 预算 128 + 固定后缀 `#batch-` 7 + 最多 9 位 sequence），sequence
  不得前导零且不超过 `999999999`；child 分支拥有**独立长度预算**，故一个合法 parent
  必然 mint 出合法 child——`run_batch` 追加 `#batch-<seq>` 后缀后，child id 不会超过
  ledger job-key gate 的闭合词法预算（避免系统自身 mint 出的 child id 在下次
  `_read_ledger` 被判为 `job_id_invalid` 的自我腐蚀）；
- parent-only surfaces：`confirm` 的 external override 与 plan id、`confirm --edit`、
  `stage` 的 external override 与 plan id、`review`、`rebind`、`preview`、batch
  `run --import-id`、legacy `run` 的 plan id 与非缺席 `--confirm`；
- parent-or-child surfaces：`status`、`rollback`（含 runner rollback）；
- `reviews --after` 是 opaque pagination cursor，不适用本 lexical contract。

parent-only surface 收到 canonical child 返回 `reason=child_syntax`。失败 envelope
的 error 精确为：

```json
{
  "code": "IMPORT_ID_INVALID",
  "message": "Import id is invalid.",
  "details": {"reason": "syntax"},
  "retryable": false
}
```

`details` 只含一个安全 `reason`，绝不回显原始输入。closed reasons 为
`type` / `empty` / `non_ascii` / `reserved_name` / `child_syntax` /
`child_parent_length` / `child_sequence` / `length` / `syntax` /
`outside_data_dir` / `containment_unavailable`；lexical precedence 为 type → empty →
non-ASCII → reserved name → child recognition/structure → child parent length →
child sequence → total length → syntax。绝对 Windows path、drive-relative path、
UNC、traversal、非 ASCII、malformed child 都在到达 filesystem/network helper 前确定
失败。

`confirm` / `stage` 若 external override 存在，先校验 override，再读取 plan
一次；有效到达的 plan 仍总是校验其 `import_id`，有效但不同的 override 继续作为
effective parent authority。legacy `run --plan` 的**缺席** `--confirm` 不是 hostile
id，继续返回 `IMPORT_CONFIRMATION_REQUIRED`；非缺席 confirm id 先做 lexical
校验，有效但与 plan 不匹配也继续返回 `IMPORT_CONFIRMATION_REQUIRED`。

### `import plan`

`plan` 是 dry-run，只读 source 和当前 data dir 状态，默认只向 stdout 输出
JSON，不写 journal、attachment、ledger、manifest 或 index。

返回 `data.schema_version = "import_plan.v1"`，核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `import_id` | string | `imp_YYYYMMDD_<hash>` 格式的本次计划 ID |
| `dry_run` | bool | 恒为 `true` |
| `source.source_fingerprint` | string | source adapter + source records 的稳定 SHA-256 |
| `plan_fingerprint` | string | plan 内容指纹 |
| `idempotency_key` | string | source + plan + target root 的幂等 key |
| `proposals[]` | array | 拟写入 journal / attachment proposal |
| `proposals[].proposal_fingerprint` | string | 单条 durable write proposal 指纹 |
| `write_set_preview.create_files[]` | array | 预计创建的相对路径 |
| `conflicts[]` | array | 现有目标路径冲突；Tranche A fail-closed |

`media.photo_timeline` attachment proposal 额外包含 `source_rel_path`。GUI
可以展示 `source_ref`、`source_sha256`、`target_rel_path`、`media_type`、
`size_bytes` 和 `copy_mode`，但不得自行读取照片、解析 EXIF、推导目标路径或
写 durable data。执行 `import run` 时，调用方应传回同一照片目录作为
`--source-root`；CLI 会在写入前校验 source hash/size 是否仍与 plan 匹配。

`media.photo_timeline` structured warnings/conflicts：

| code | severity | runnable | 说明 |
|---|---|---|---|
| `PHOTO_GPS_MISSING` | warning | yes | 没有 GPS metadata；不阻塞 run |
| `PHOTO_CAMERA_MISSING` | warning | yes | make/model metadata 缺失 |
| `PHOTO_ORIENTATION_MISSING` | warning | yes | orientation tag 缺失 |
| `PHOTO_UNSUPPORTED_FILE_SKIPPED` | warning | yes | 当前 tranche 不支持的文件被跳过 |
| `PHOTO_UNSUPPORTED_FORMAT` | warning | no | `.heic` / `.heif` 等明确不支持的格式（preview unavailable），不静默跳过；额外携带安全字段 `format`（如 `.heic`）与 `preview_available=false`，供 GUI 如实展示该限制 |
| `PHOTO_EXIF_UNREADABLE` | warning | yes | EXIF 无法读取，adapter 会降级并同时输出缺失 capture time conflict |
| `PHOTO_CAPTURE_TIME_MISSING` | conflict | no | 没有可信 capture date；阻塞 run |
| `PHOTO_CAPTURE_TIME_AMBIGUOUS` | conflict | no | 多个日期来源冲突；阻塞 run |
| `PHOTO_SOURCE_UNREADABLE` | conflict | no | 源文件无法读取 |
| `PHOTO_TARGET_PATH_CONFLICT` | conflict | no | 计划 journal 或 attachment path 已存在 |

### `import run`

`run` 先按 `--import-id` 选项是否出现确定性选择 route：

- 只有 `--import-id` 完全缺席时，才进入 legacy `--plan/--confirm` route；
- `--import-id` 一旦显式出现，就选择 batch route，再校验其值。显式空值或 lexical
  非法值返回既有 `IMPORT_ID_INVALID`；lexical 合法但未知的值返回既有
  `IMPORT_JOB_NOT_FOUND`；
- `--import-id` 与 `--plan/--confirm` 同时出现时，batch route 优先，legacy plan
  不执行。

legacy route 必须带 `--confirm <import_id>`，且 `<import_id>` 必须匹配 plan；缺席或
有效但不匹配仍返回 `IMPORT_CONFIRMATION_REQUIRED`，无效的非缺席 confirm 或无效的
plan `import_id` 返回 `IMPORT_ID_INVALID`。legacy route 按 create-only /
fail-closed 策略写入 plan 中的 journal 和 attachment path，并在写入前建立固定
ledger 和 rollback manifest。

对 `media.photo_timeline`，`run` 还应带 `--source-root <photo-dir>`。CLI 只
使用该 root 解析 plan 中的 `source_rel_path`，并在复制 attachment 前校验
`source_sha256` 与 `size_bytes`；绝对 source path 不进入 plan fingerprint。

固定路径：

```text
.life-index/import-jobs/ledger.json
.life-index/import-jobs/ledger.lock
.life-index/import-jobs/<import_id>/rollback-manifest.json
```

所有 import ledger 读改写事务共用 `ledger.lock` 跨进程串行化；`ledger.json` 通过同目录
temp + fsync + atomic replace 更新。已存在但 malformed/torn/unreadable 的 ledger 返回
`IMPORT_LEDGER_CORRUPT`，绝不按空 ledger 重置或覆盖。

返回 `data.schema_version = "import_run.v1"`，核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | string | `committed` / `already_committed` / `partially_committed` |
| `created_files[]` | array | 实际创建文件；每项含 `kind`、`rel_path`、`sha256_after`、`created_by_import`；M7 hard-link publish 还含 additive `size_bytes`、`publication_state` 与 `ownership_proof` |
| `rollback_manifest_rel_path` | string | 固定 rollback manifest 相对路径 |
| `post_run_actions.index_rebuild_recommended` | bool | Tranche A 不自动 index，只建议后续重建 |

重复运行同一 committed plan 返回 `state=already_committed`，不重复写入。
`running`、`failed`、`partially_committed` 不会被误报为 committed。

`run` 会在写 ledger 或 durable file 之前重新校验 plan 内容：

- journal / attachment `target_rel_path` 必须 resolve 在 `LIFE_INDEX_DATA_DIR`
  内；路径遍历或绝对路径属于 `IMPORT_PLAN_INVALID`；
- `proposal_fingerprint`、`plan_fingerprint`、`idempotency_key` 必须按当前
  plan 内容和目标 data dir 重新计算并匹配；
- `summary.conflict_count > 0`、顶层 `conflicts[]` 非空，或任一
  `proposals[].conflicts[]` 非空时，返回
  `IMPORT_PLAN_CONFLICTS_UNRESOLVED`，不创建 ledger 或 durable files。

### `import status`

`status` 从固定 ledger 和 rollback manifest 读取 job state，不启动 daemon、不扫
描 source、不推断未记录 job。

返回 `data.schema_version = "import_status.v1"`，核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | string | `running` / `committed` / `partially_committed` / `rollback_failed` / `rolled_back` 等 |
| `counts` | object | planned/created journal 与 attachment 计数 |
| `rollback_available` | bool | 是否存在 rollback manifest |
| `rollback_manifest_rel_path` | string | 固定 manifest 相对路径 |

通过 lexical 校验但未知的 `import_id` 返回 `IMPORT_JOB_NOT_FOUND`；lexical 非法输入
返回 `IMPORT_ID_INVALID`。

### `import rollback`

`rollback` 只处理 manifest 中 `created_by_import=true` 的文件。删除前重新计算
当前 SHA-256 / size，并与 manifest 证据精确匹配；带 `ownership_proof` 的 M7 条目还
必须匹配 manifest 在 publish 前记录的 hard-link filesystem identity。任何已发布条目
的 checksum / size / identity mismatch 都会拒绝整个 rollback，返回
`IMPORT_ROLLBACK_CHECKSUM_MISMATCH`，不会删除部分文件。`prepared` 条目若遇到
create-only racing target 且 identity 不同，该 target 被证明不是 import-owned，rollback
只清理自己的 staging 并保留该 target，即使两者 bytes/checksum 相同。
初检通过后，rollback 在既有 shared journals lock 内完成 pending queue、所有 target /
staging 的最终 confinement / identity / SHA-256 / size 复检以及全部 unlink；任一最终
证据变化都在第一次删除前 fail closed。journals lock timeout/unavailable 返回可重试的
既有 `IMPORT_INTERNAL_ERROR`，删除数为零。

rollback 还会 resolve 每个 manifest path，确认目标仍在 `LIFE_INDEX_DATA_DIR`
内；路径遍历、绝对路径、非普通文件等 unsafe path 返回
`IMPORT_ROLLBACK_UNSAFE`，且不会删除任何文件。该错误 fail-closed，但外向 envelope
只含 locator-free 诊断（见下「Resolved path containment (R1b)」）：`reason`、计数与
`created_files` entry index——绝不回显原始 hostile 绝对/遍历路径（原始路径仅写入
用户自有 data dir 内的 durable manifest audit 记录）。

成功 rollback 后：

- created files 被删除；
- rollback manifest 保留为 audit evidence，并更新为 `state=rolled_back`；
- ledger job state 更新为 `rolled_back`；
- 再次 rollback 幂等返回 `rolled_back`。

### 错误码

| code | 说明 |
|---|---|
| `IMPORT_SOURCE_UNSUPPORTED` | 未知 source adapter |
| `IMPORT_SOURCE_UNREADABLE` | source / fixture 无法读取 |
| `IMPORT_ID_INVALID` | external / plan import id lexical 校验失败；不回显原始输入 |
| `IMPORT_PLAN_SCHEMA_UNSUPPORTED` | plan schema version 不支持 |
| `IMPORT_PLAN_INVALID` | plan JSON 缺少必要字段或语义非法 |
| `IMPORT_PLAN_CONFLICTS_UNRESOLVED` | plan 含 unresolved conflicts，Tranche A fail-closed |
| `IMPORT_CONFIRMATION_REQUIRED` | `run` 缺少匹配的 `--confirm <import_id>` |
| `IMPORT_CONFLICT_EXISTING_PATH` | 目标路径已存在且非同一幂等证据 |
| `IMPORT_IDEMPOTENCY_CONFLICT` | 同一 key 映射到不兼容 import job |
| `IMPORT_JOB_NOT_COMMITTED` | 同一 import/idempotency 记录存在但不是 committed 状态 |
| `IMPORT_WRITE_FAILURE` | durable write 在创建任何文件前失败 |
| `IMPORT_JOB_NOT_FOUND` | `status` / `rollback` 找不到 job |
| `IMPORT_ROLLBACK_MANIFEST_MISSING` | 缺失 rollback evidence |
| `IMPORT_ROLLBACK_CHECKSUM_MISMATCH` | rollback 文件当前 hash 与 manifest 不一致 |
| `IMPORT_ROLLBACK_UNSAFE` | rollback 会触碰非安全 import-owned 文件或逃逸 data dir |
| `IMPORT_LEDGER_CORRUPT` | 固定 ledger malformed/torn/unreadable；fail closed 且不重置/覆盖 |
| `IMPORT_INTERNAL_ERROR` | 未归类内部错误 |

#### Resolved path containment (R1b)

每个由 external / plan-contained / stored / newly-minted id 或 relative locator 派生的
import-job 路径，在首次使用前都会被 resolve 并按 component-wise（`relative_to`，非字符串
前缀）证明是 resolved data dir 的严格后代。任何 traversal、绝对路径、junction/reparse/
symlink 逃逸、sibling 前缀混淆、或 resolve 失败都在**产生任何 ledger / manifest / staging
/ attachment 副作用之前** fail closed：不创建/读取/删除根外文件，不预留 child job，source
字节不变，且错误输出不含 hostile 绝对路径或 traceback。

下列既有错误码为此新增**附加安全 `reason`**（在 `error.details.reason`，不改变既有 error 含义、
success shape 或 exit code 映射；`reason` 为开放描述，调用方不应视为闭合枚举严格校验）：

| code | additive `reason` | 触发 |
|---|---|---|
| `IMPORT_WRITE_FAILURE` | `job_path_not_confined` | run / batch 的 manifest 派生路径逃逸 data dir |
| `IMPORT_WRITE_FAILURE` | `review_path_not_confined` | confirm/stage/edit/review/run 的 parent job 路径逃逸（per-parent lock 之前）；rollback 对存储 `parent_review_job_id` 派生路径逃逸（同样 lock 之前） |
| `IMPORT_ROLLBACK_UNSAFE` | `rollback_manifest_path_not_confined` | 存储的 `rollback_manifest_rel_path` 为绝对/遍历/逃逸 locator |
| `IMPORT_ROLLBACK_UNSAFE` | `unsafe_manifest_entries` | manifest 中某 `created_by_import` 条目的 `rel_path` 逃逸 data dir，或其 `ownership_proof` 非法；`details` 另含 `unsafe_path_count` / `invalid_ownership_count` 与 `unsafe_entry_indices` / `invalid_ownership_entry_indices`（`created_files` 数组下标），均 locator-free、不回显原始路径 |
| `IMPORT_LEDGER_CORRUPT` | `import_jobs_area_not_confined` | `.life-index/import-jobs` 区域本身是逃逸 link（首次 ledger I/O 前） |
| `IMPORT_LEDGER_CORRUPT` | `review_plan_path_not_confined` | review-plan 派生路径逃逸 data dir（读写两侧均 raise，见下） |
| `IMPORT_LEDGER_CORRUPT` | `job_id_invalid` | 持久化 ledger 的某个 `jobs` key 非闭合词法 import id（path-like/遍历/非词法）；在首次 `_read_ledger` 读时 fail-closed（见下） |
| `IMPORT_LEDGER_CORRUPT` | `parent_authority_unrecoverable` | parent review job 缺失但 ledger 中存在其 batch child（`kind=="batch"` 且 `parent_review_job_id==parent`）时，从幸存 review plan rebuild 会把已导入 proposal 重置为 `confirmed`、`next_batch_sequence` 重置为 1（第二权威、re-import 风险），故 reconcile 的 rebuild 分支 fail-closed raise 而非 rebuild——覆盖 reconcile 的全部入口（status/confirm/edit/review/run/rollback，含 child rollback）；无 child 时仍保留 genuine first-confirm rebuild（既有行为不变） |
| `IMPORT_PLAN_INVALID` | `duplicate_runnable_target` | `run` 的 runnable 集合中两个 proposal 声称同一 canonical journal/attachment `target_rel_path`（legacy/crafted plan，或 allocation 漏洞残留）；在 batching transition / 首次 durable write **之前** fail-closed，绝不产生 partial publish。`details` 另含 `kind`（`journal`/`attachment`）与 `proposal_ids` |
| `IMPORT_PLAN_INVALID` | `source_facts_drift` | `run` 时从实际 source 文件 re-derive 的不可变 metadata（至少 `metadata_hash`，含 `capture_time` 的 value/source_tag/timezone_authority）与 plan 存储的 `source_facts` 不一致（plan 在 confirm 后被篡改：capture_time + coherently 重算的 metadata_hash）；在 publish **之前** fail-closed。source 无法 re-parse（不支持格式/不可读）同样 fail-closed。`details.proposals` 列出漂移 proposal ids |

附加 surfacing 说明：

- **`review_path_not_confined`（写路径，`IMPORT_WRITE_FAILURE`，`details.reason`）**：confirm/stage/
  edit/review/run 在取 per-parent lock **之前**证明 parent job 路径 confined。rollback 对其**存储的**
  `parent_review_job_id` 先做 lexical 校验——存储 locator 为绝对/遍历/逃逸值时先返回既有
  `IMPORT_ID_INVALID`（lexical 失败，`details.reason` 为 `syntax` 等），lexical 合法但解析逃逸时返回
  `review_path_not_confined`。所有这些写路径都在创建 lock 文件之前失败。
- **`review_plan_path_not_confined`（读+写路径，`IMPORT_LEDGER_CORRUPT`，`details.reason`）**：写入侧
  （`_write_review_plan_atomic`）与读取侧（`read_review_plan`，被 status/queue/preview 以及 `plan` 的
  去重扫描调用）在 review-plan 路径逃逸时均 **raise `ImportLedgerCorruptError`**，CLI 统一映射为
  `IMPORT_LEDGER_CORRUPT`。读取侧**绝不**把逃逸当作"plan 缺失"返回 `None`（否则 reconciliation 会误
  abort 一个 pending intent、甚至 `jobs.pop(parent_id)` 这种由 containment 失败引起的破坏性 in-root
  改动）。真正 confined 但磁盘上不存在的 plan 仍返回 `None`（既有"缺失"行为不变）。status 路径在
  per-parent lock 之前用同一 probe 也会 raise，故 ledger 字节/SHA、jobs、proposal_states、intent 全不变。
- **`job_id_invalid`（读+写路径，`IMPORT_LEDGER_CORRUPT`，`details.reason`）**：`_read_ledger` 在既有结构
  校验之后，对**每个** `jobs` key 用 `validate_import_id(key, allow_child=True)` 做闭合词法校验——任一 key
  非词法 import id（path-like/遍历/非词法）即 raise `ImportLedgerCorruptError(ledger_path, "job_id_invalid")`，
  CLI 统一映射为 `IMPORT_LEDGER_CORRUPT`，退出码映射不变。这是 R1c 的 single-point 闭合：一个敌意的
  durable `jobs` key 对**所有** consumer（status/`run`/`reviews` 读路径、`_derive_child_batches`/
  `_child_batch_projection` 的 `batches` 投影、`_reconcile_parent` 的 settled 扫描）都不可达——在读时
  fail-closed，故无修复、无路径派生、无泄漏、重复调用逐字节一致。敌意 key 值**绝不**进入 error
  （仅 `reason = "job_id_invalid"`）。这同时也**强制**了 `batches` 投影的 locator-free 语义：派生它的
  每个 job key 都已通过词法门，绝无 locator 能从 `data.batches[].import_id` 泄漏。
- **`staging_path_not_confined`（`IMPORT_WRITE_FAILURE` 的 `message` 文本，**非** `details.reason`）**：
  batch 的 staging 派生路径逃逸时，`_stream_copy` / `_publish_text_create_only` 返回
  `(False, "staging_path_not_confined")`，该字符串作为 `RuntimeError` 信息冒泡进 `IMPORT_WRITE_FAILURE`
  的 `message` 文本（形如 `"... staging_path_not_confined"`），**不**进入 `error.details.reason`
  （`details` 仍为 `child_id`/`parent_id`/计数）。它与上表中的 `details.reason` 是不同的 surfacing，
  这里明确区分，不混为一谈。
- **Windows 瞬态 manifest replace 内部重试（1.6.2+，非错误码 surfacing）**：原子写在做
  `os.replace` 时，若 Windows 抛出瞬态 share/access lock（`winerror` 5 access-denied / 32
  sharing-violation），内部做有界重试（最多 3 次 `os.replace` 尝试，退避 0.01s / 0.05s，
  仅两次 sleep）。该重试**不改变任何错误码、success shape 或 exit code**：仅 `os.name == "nt"`
  且 `winerror in {5, 32}` 可重试；不符合该重试资格的错误、非 Windows（即便 `winerror` 32）、以及
  mkdir / mkstemp / json write / fsync / containment / 路径错误一律不重试、首次即抛出。重试耗尽
  仍原样抛出最后一个 `OSError`，走既有 `IMPORT_WRITE_FAILURE` / manifest-guarded 补偿；成功则
  继续既有 directory fsync。这是首跑吸收瞬时锁的内部行为，不产生新的 operator-visible 错误。

合法的 contained 路径（普通 data dir、嵌套 job 目录、data dir 自身含 symlink 组件——两侧都
resolve）继续正常工作，不被误拒。

### schema_version Policy

`import` top-level envelope 使用 `schema_version = "import_job.v1"`。
子对象使用独立 schema：`import_plan.v1`、`import_run.v1`、
`import_status.v1`、`import_rollback.v1`、`import_job_ledger.v1`、
`import_rollback_manifest.v1`。

Tranche A 将以下内容纳入兼容性承诺：

- 上述 schema version 字符串及其已记录字段名、字段类型、必填语义；
- 错误码字符串及其 fail-closed 语义；
- `proposal_fingerprint`、`plan_fingerprint`、`idempotency_key`、source
  fingerprint 的规范化输入和计算公式；
- fixed ledger / rollback manifest 路径语义；
- dry-run 不写真实用户数据，run/rollback 必须限制在 `LIFE_INDEX_DATA_DIR`
  内。

新增 additive 字段不升级版本，消费者必须忽略未知字段。删除、重命名、重设
类型、改变必填语义、改变错误码含义，或改变 fingerprint / idempotency 公式，
都属于破坏性变更，必须升级对应 schema 并补 contract tests。兼容扩展可以继续
使用现有 schema，但不得让旧消费者误判 import state 或 durable write boundary。

### Review queue & batch import（additive，M7 历史照片冷启动）

本节是 **additive** 扩展：它新增一个可恢复照片审阅队列、分批导入、批次回滚和
源不可变性能力，全部复用现有 import ledger / rollback manifest / fingerprint
权威。`import plan` / `import run --plan … --confirm …` / `import status` /
`import rollback` 的既有 Tranche A/B 行为保持不变；下列命令与字段均为新增，旧
消费者忽略未知字段即可。`media.photo_timeline` 的 source facts 不可变：adapter /
provenance、content SHA-256、size、source 相对路径、capture time value/source/
timezone authority、GPS、source relation 与 attachment relation 都是 source facts；
用户只能编辑 journal `title` / `date` / `topic` / `tags` / `content` 与 proposal /
attachment selection，用户编辑是最高事实但不能改写 source facts。

**Immutable attachment provenance**：一个 selected attachment 必须绑定到同一不可变
source fact —— `source_sha256`、`source_rel_path`、`source_ref`、`media_type`、
`size_bytes` 与确定的 `attachment_id`（`att_<source content prefix>`）都要与本
proposal 内绑定的 source fact 完全一致；`confirm` 做绑定交叉校验，任何篡改
（source_rel_path / source_ref / media_type / size / attachment_id / target 逃逸）
返回 `IMPORT_PLAN_INVALID` 并拒绝持久化。对非 frozen 可编辑 proposal，canonical
attachment target 与 journal target 在 `confirm` 时由 effective date + content **重新
派生 / 校验**，绝不信任 incoming GUI 编辑；journal target 必须落在 canonical date
路径 / sequence 内。attachment target / journal target 必须 lexical confined（拒绝
绝对路径与 `..` 段），并在 run 时再经 confinement 复核。部分取消选择 / 全部取消选择
的既有语义保持不变。

#### Proposal lifecycle

`media.photo_timeline` proposal 增加 additive 状态字段 `state`，取值：
`pending`（`import stage` 初始入队、plan 阶段、或日期未解析）、`confirmed`（日期可解析后
经 `import confirm` / 单 proposal `--edit` 持久化）、`skipped`（该 proposal 所有
attachment 被取消选择，不创建空 journal）、`stale`（批次准备时 source 内容/大小已变或源
文件被删除，从本批排除）、`batching`（已进入某个 active child batch）、`imported`
（child batch committed）。
`imported` / `batching` 是 frozen 状态：re-confirm / edit 时其内容权威且不变、绝不降级；
`pending` / `confirmed` / `skipped` 接受安全编辑（含 attachment selection）。
成功 rollback 一个 child batch 后，其 parent proposal 恢复为 `confirmed`。

每个 proposal 携带显式 `date_resolution`（日期权威，绝不来自文件 mtime）：

- `exif_authoritative`：可信 EXIF 提供日期（带 offset 用其本地 calendar date，
  无 offset 按相机本地日期，不猜时区；含 `authority` 来源）。proposal 的
  `journal.date` 与 journal / attachment `target_rel_path` 在 plan 阶段已派生。
  **EXIF offset trust**：offset 只取与所选 capture tag **配对** 的 offset tag
  （`OffsetTimeOriginal` ↔ `DateTimeOriginal`、`OffsetTimeDigitized` ↔ `CreateDate`、
  `OffsetTime` ↔ `DateTime`），绝不借用兄弟 tag（如不用 `OffsetTimeDigitized` 配
  `DateTimeOriginal`）。offset 必须有显式符号（`+`/`-`）、分钟合法（`00`–`59`）、且
  落在真实世界 UTC 范围内（最多 ±14:00，`14` 仅配 `:00`）；否则视为不可信，日期仍按
  相机本地 `exif_naive` 使用，**绝不换算**。`authority` 为 `exif_offset`（带可信
  offset）或 `exif_naive`（无 offset）。
- `user_confirmed`：用户在 `confirm` 时通过 `date_resolution.date` 显式给出
  `YYYY-MM-DD`。这是最高权威——可解析一条不可变的 EXIF capture-time 冲突，
  覆盖 EXIF 日期；`confirm` 校验日期合法性、派生 canonical journal target，然后
  才允许 `confirmed`。
- `unresolved`：缺日期或多日期冲突（`PHOTO_CAPTURE_TIME_MISSING` /
  `PHOTO_CAPTURE_TIME_AMBIGUOUS`）。**无 1970-01-01 sentinel**：这种 proposal 的
  `journal.date == ""`、`journal.target_rel_path == ""`、attachment
  `target_rel_path == ""`，停留在显式 `pending` 区域且不可运行，直到用户给出
  `user_confirmed` 解析；EXIF 冲突仍被如实记录。

`media.photo_timeline` 现支持 JPEG/`.jpg`/`.jpeg`；`.heic` / `.heif` 明确
unsupported：发出 `PHOTO_UNSUPPORTED_FORMAT` warning 且标记 preview unavailable，
不静默跳过。adapter 递归只读扫描源目录，跳过 symlink / junction / reparse
point、root escape 与目录循环；按精确字节哈希。精确 content SHA-256 去重：同名
不同内容保留为独立记录。rescan 的去重集合包含两类来源（read-only）：

1. 已 `committed` 的 child / legacy job 的 rollback manifest 中的 attachment
   `sha256_after`；
2. parent review job 中、authoritative state 为 `confirmed` / `batching` /
   `imported` 的 proposal 的 attachment `source_sha256`。

这使得「已排队但尚未导入」的照片在 rescan 时不被重复候选；被 rollback 恢复为
`confirmed` 的 proposal 仍留在去重集合内（保持排除）。可信日聚合为一个 editable
proposal（多附件）；缺日期/冲突的记录成为独立待处理 proposal（不自动归入某天）。
attachment 列表即 selected set；全部取消选择 ⇒ `skipped`（无 runnable proposal）。
Planning 阶段不复制任何正式附件字节。

#### `import confirm`

```bash
# 持久化/再确认完整 review plan（legacy / stage 之外的整盘再确认）
life-index import confirm --plan <review-plan.json> [--source-root <dir>] [--import-id <parent_id>] --json
# 单 proposal 原子 confirm/edit（package-3）：--plan 与 --edit 互斥
life-index import confirm --edit <review-edit.json> --import-id <parent_id> --expected-queue-revision <int> --json
```

把完整 review plan 原子持久化到固定路径
`.life-index/import-jobs/<parent_id>/review-plan.json`，并在同一 ledger 记录一个
parent review job（additive `kind: "review"`）。写入采用 temp 文件 + fsync +
atomic replace；并发安全由全局 import-ledger transaction lock + per-parent
single-writer lock 保证（均复用 repo 既有 `FileLock`，固定锁序为 ledger → parent）。
`confirm` 必须重新计算 / 校验 immutable fingerprints 与 selected
attachment ids；tamper（指纹/selected id 不匹配）返回 `IMPORT_PLAN_INVALID` 并
拒绝持久化。

`--edit` 走单 proposal 原子 confirm/edit 路径（见下「单 proposal edit」）：严格校验
`import_review_edit.v1` payload、用 `--expected-queue-revision` 做乐观并发令牌、
从持久化 immutable `source_facts` 重建选择、应用 journal 编辑与 decision。`--plan`
与 `--edit` 互斥（同时给出为 usage error，非零退出）。

`confirm` 在 per-parent lock 内先做 plan/ledger authority reconciliation（见下），
若有未结算 active child 则拒绝（`IMPORT_BATCH_ALREADY_ACTIVE`），随后合并 incoming
plan 到既有 review 状态：`imported` / `batching` proposal 冻结（内容权威不变、
state 以 ledger 权威为准、绝不降级），其余 proposal（re-）派生 `date_resolution` 与
canonical target。durable `next_batch_sequence` 在 re-confirm 时保留不变。

**Crash-safe plan↔ledger 更新协议**：为消除「新 plan 已落盘但 ledger 仍是旧投影」
的静默撕裂窗口，`confirm` 在 per-parent lock 内按 **intent → plan → finalize** 三步
顺序更新，且 ledger 是唯一权威（不引入第二个 store）。先在内存中合并出最终 plan 与
parent 投影，然后：

1. **(I1) durable intent**：在 parent job 上原子写入一个 `pending_review_update`
   intent（携带 `expected_plan_fingerprint` / `expected_plan_revision`、完整 finalize
   投影字段、以及 prior 投影快照），保留既有权威字段（含 `next_batch_sequence`）；
2. **(P) atomic plan replace**：temp + fsync + atomic replace 写入新 review-plan.json；
3. **(F) finalize**：从 intent 把 parent 投影落盘并清除 intent，递增 `plan_revision`。

confirm/status/run/rollback 都先做幂等 reconciliation 收敛三个 crash 窗口：intent
的 `expected_plan_fingerprint` 与持久化 plan 指纹匹配 →（crash after plan / before
finalize）幂等 finalize；intent 存在但 plan 仍是旧值/缺失 →（crash after intent /
before plan）abandon intent，恢复 prior 投影（首次 confirm 的空 shell 直接移除）；
**无 intent 但持久化 plan 指纹与 ledger `plan_fingerprint` 不一致** → fail closed
（`recovery_required` + `authority_status = "plan_ledger_mismatch"`），绝不静默二选
一。重复 status 收敛（幂等）。一次新的 `confirm` 用显式 incoming plan 重算指纹、可作
为修复手段并在 finalize 后清除 `authority_status`。

返回 `data.schema_version = "import_review.v1"`，含 `parent_id`、
`source_root_identity`、各 proposal `state`、derived queue counts（`confirmed` /
`skipped` / `pending` / `stale` 计数）、`plan_revision`、`queue_revision`。

固定路径：

```text
.life-index/import-jobs/ledger.lock              (cross-process ledger transaction lock)
.life-index/import-jobs/<parent_id>/review-plan.json
.life-index/import-jobs/<parent_id>/review.lock   (per-parent single-writer lock)
```

##### 两个 revision、各自一个权威（package-3）

parent review job 维护**两个**整数 revision，含义不同、绝不混用：

- `plan_revision` —— review-plan **内容**权威。整盘 `confirm` / `stage` / 单 proposal
  `--edit` 的 finalize 各递增一次；**state-only** 的 run（batching/stale 转移）、
  rollback、reconciliation **永不**改动 `plan_revision`。
- `queue_revision` —— parent-ledger 拥有的**客户端并发令牌**（初始 1）。每次「parent
  可见投影的原子变更」递增恰好一次：stage；edit 或 legacy reconfirm finalize；
  run 转移到 batching/stale；改变 proposal states/active child/recovery 的 child
  commit/rollback/failure reconciliation；rebind（仅当 identity/recovery 可见字段变
  化时）；plan-authority reconciliation（仅当可见复合投影变化时）。pending intent 携
  带 finalize 后的精确 `queue_revision`，故 crash replay 幂等、绝不二次递增。
  `updated_at` 等非权威字段单独变化**不**递增令牌。收敛后重复读为 no-write。

#### `import stage`

```bash
life-index import stage --plan <review-plan.json> --source-root <dir> [--import-id <parent_id>] --json
```

把一批照片 stage 为**初始 pending** review 队列：复用 `confirm` 的
validation / lock / review-plan / ledger / intent 协议，**不复制任何附件字节**。每个
selected proposal 保持 `pending`（可信日与缺日均留在待处理区，日期权威与 target 派
生推迟到后续 edit/confirm），空选择 ⇒ `skipped`。`queue_revision` 与 `plan_revision`
均初始化为 1。

**重复 source root 保护**：若同一 `source_root_identity` 已存在 actionable review job
（任一 proposal 为 `pending` / `confirmed` / `batching`，或有 active child），返回
non-retryable `IMPORT_REVIEW_ALREADY_STAGED`（带 `existing_import_id`），**不创建第二
个 job/plan、零写入**。proposals 全为 `skipped` / `imported` / `stale` 且无 active
child 的 job 视为已完成、**不**阻塞同一 root 的新 stage。

#### 单 proposal edit（`import confirm --edit`）

```bash
life-index import confirm --edit <review-edit.json> --import-id <parent_id> --expected-queue-revision <int> --json
```

`import_review_edit.v1` payload 严格白名单：顶层仅允许
`schema_version` / `proposal_id` / `decision` / `journal` / `selected_attachment_ids`；
任何 source/provenance/target/fingerprint 字段 ⇒ `IMPORT_REVIEW_EDIT_INVALID`（零写
入）。`journal` 仅允许 `title` / `date` / `topic` / `tags` / `content`（类型校验、
`topic` 必须属于既定 taxonomy）；`selected_attachment_ids` 必须是该 proposal 已持久化
`source_facts` 中的已知 attachment id。

处理顺序：schema/字段校验（零写入）→ 令牌校验（`expected_queue_revision` 必须等于当前
`queue_revision`，否则 retryable `IMPORT_REVIEW_REVISION_CONFLICT`，带
`current_queue_revision`，零写入）→ 冻结检查（`batching`/`imported` ⇒
`IMPORT_REVIEW_PROPOSAL_FROZEN`）→ 从 immutable `source_facts` 重建选择（保留全部
`source_facts`，被取消选择的附件日后可仅凭 attachment id 重新选择）→ 应用 journal
编辑与 decision。

decision 语义：`confirmed` 需要可解析日期（用户提供或无 capture 冲突的 EXIF 日），否则
保持 `pending` 并返回 soft reason code `IMPORT_REVIEW_DATE_REQUIRED`（编辑仍持久化、
revisions 各递增一次）；空选择 ⇒ `skipped` + `IMPORT_REVIEW_EMPTY_SELECTION_SKIPPED`；
`pending` 保存编辑但不晋升。两次链式 edit 只需用上一次响应的 `queue_revision` 作令牌
（无需重新拉取 review）。`plan_revision` 与 `queue_revision` 各递增一次。

#### `import review`（bounded read）

```bash
life-index import review --import-id <parent_id> [--offset 0] [--limit 20] [--state <STATE> ...] --json
```

per-parent lock 内 reconcile + capture 后，按持久化 plan 顺序、以 **ledger 权威 state**
叠加（绝不取 plan 内 per-proposal `state` 字段）分页投影。`--limit` clamp 到 1..100
（默认 20），`--offset` 越界返回空页；`--state` 可重复过滤。每个 proposal 仅暴露稳定、
非定位字段 + `available_attachments`（`attachment_id` / `source_ref` / `media_type` /
`size` / `selected`）——**绝不**暴露 source 文件系统定位（无 `source_rel_path`、无绝
对路径）。recovery / mismatch ⇒ `IMPORT_REVIEW_RECOVERY_REQUIRED`。返回
`total_all` / `total_filtered` / `offset` / `limit` / `has_more` / `next_offset` /
`queue_revision`。收敛后重复读为稳定 no-write（ledger 不变）。

**Restart-safe 顶层 plan-warning 投影**：响应还携带 `warnings[]`——持久化 review-plan
顶层 scan-level warning（如 `.heic` / `.heif` 的 `PHOTO_UNSUPPORTED_FORMAT`，标记 photo
unsupported 且 preview unavailable）的投影。这些 warning 在 `import plan` 阶段由 adapter
产生、随 review-plan 落盘；GUI/CLI 重启后 `import review` 每次都从持久化 plan 重新读
回并如实披露，**绝不静默遗漏**受影响的照片。投影只走显式安全 allowlist：`code` /
`severity` / `runnable` / `format` / `preview_available`——**绝不**投影 adapter `message`
（其文本可能内嵌 source 相对路径定位符），也**绝不**盲目透传任意 adapter 扩展字段；
文件名 / 相对或绝对 source 路径 / 含定位符的 message 文本均不进入响应。重复读投影稳定
且为 no-write（同 `queue_revision`、ledger 不变）。

#### `import reviews`（discovery）

```bash
life-index import reviews [--after <import_id>] [--limit 20] --json
```

稳定读：除读取 ledger 外**不做** reconciliation。仅列出 parent review job（排除 child
batch job），按 `import_id` 排序、`--after` 为排他游标、`--limit` clamp 到 1..100。每个
条目携带 `plan_revision` / `queue_revision` / `queue_counts` / `state` /
`active_child_id` / `recovery_required` / `created_at` / `updated_at`——**不含**定位符或
proposal 内容；交错的 `updated_at` 变化不影响排序与 id 集合。

#### `import validate` / `import rebind`

```bash
life-index import validate --source-root <dir> --json
life-index import rebind --import-id <parent_id> --source-root <dir> --json
```

Directory path v1 不假装浏览器能 handle：定位是 explicit path + CLI
validate/rebind。`validate` 返回 canonical readable dir 与 root identity
fingerprint（基于目录规范化路径与稳定 filesystem identity 属性——device 与
inode——的确定性 SHA-256）。该 identity 是 **content-stable**：在 root 内新增、删除
或修改照片都不会改变它（故 POSIX 目录 `ctime` 不参与计算——它在每次目录项增删时
bump，会既拒绝合法 run 又绕过同一物理 root 的重复 stage 保护）；不同物理 root 仍由
device/inode 区分。parent 只存 root identity，不把绝对路径放进公开 plan/review-plan。
restart 后可用 `import-id` 恢复队列；但 `confirm` / `run` / `preview` 必须用当前
rebound locator（`rebind` 或 `--source-root`）重新验证同一 root identity，不匹配返回
`IMPORT_SOURCE_ROOT_IDENTITY_MISMATCH`。

#### `import preview`（read-only）

```bash
life-index import preview --import-id <parent_id> --attachment <attachment_id> [--proposal-id <proposal_id>] [--source-root <dir>] [--output -|<path>] [--metadata-output <path>] --json
```

只读：输入 parent / proposal / attachment + rebound source root，只读取已持久化
`review-plan.json` 引用的文件，复用既有 confinement / reparse checks；先校验
expected SHA-256 与 size，再输出可供 backend 流式传输的 bytes / metadata；绝不
修改源 hash / mtime。预览钉在 `import_id` + `proposal_id` + `attachment_id`，并从持久化
immutable `source_facts` 解析（非客户端提供），故**被取消选择的附件仍可预览**；给出
`--proposal-id` 时附件必须属于该 proposal，否则返回 `IMPORT_PREVIEW_UNAVAILABLE`。
`--source-root` 为瞬态定位符，按 `source_root_identity` 校验。`unsupported` / `stale` /
`missing` / invalid root / unreferenced / proposal 不匹配的 attachment 返回结构化
unavailable / error。`--output -` 时 stdout 为 raw bytes，metadata 经
`--metadata-output` 落盘。

#### Batch `import run`（single active child）

```bash
life-index import run --import-id <parent_id> [--source-root <dir>] --json
```

（与既有 `--plan/--confirm` 路径并存；带 `--import-id` 且该 id 是 parent review
job 时进入 batch 路径。）parent 同一时刻只允许一个 active child batch。batch run
在 per-parent lock 内：先做 plan/ledger authority reconciliation 与 prior active
child 的幂等 reconciliation，再记录 `active_child_id` / selected proposal ids /
transition intent（durable），并把 selected `confirmed` proposal 转为 `batching`；
之后创建 child batch job。

- 并发 / 重复 run（已有未结算 active child）返回 `IMPORT_BATCH_ALREADY_ACTIVE`。
- child id 单调：parent 存 durable `next_batch_sequence`（下一个可用序号），
  child id 形如 `<parent_id>#batch-<seq>`；每个 child job 记录其精确 `proposal_ids`
  ——后续 rollback / reconciliation 从 child 自身成员投影，绝不复用 parent 的上一次
  选择。
- child 是同一 ledger / manifest / fingerprint 权威下的普通 batch job
  （`kind: "batch"`，`parent_review_job_id` 指回 parent）。
- 既有 fixture `--plan/--confirm` plan/run 行为保持不变。

每次 parent status / new run / child rollback projection 都先在 parent lock 内做
幂等 reconciliation：

- 无 child 或无 durable evidence（无 ledger 条目 / 无 committed manifest）→ 清
  active_child_id 并把相关 proposal 恢复 `confirmed`；
- child `committed` → 投影 parent proposal 为 `imported`，清 active_child_id；
- child partial / failed 且有 created evidence → 用既有 checksum-guarded rollback
  补偿；补偿全成功才恢复 `confirmed`，否则保持 `batching` + `recovery_required`；
- child `rolled_back` → 恢复 `confirmed`；
- 未知证据 fail closed（保持 `batching` + `recovery_required`）。该 reconcile 覆盖
  crash-after-batching-before-child、child-before-manifest、commit-before-projection、
  重复 reconciliation 四个窗口。

除 child 投影外，reconciliation 还收敛 **confirm 的 plan↔ledger crash 窗口**（见
`import confirm` 的 intent→plan→finalize 协议）：pending intent 与持久化 plan 指纹匹配
→幂等 finalize；intent 存在但 plan 仍旧/缺失 → abandon intent、恢复 prior 投影（或移除
首次 confirm 的空 shell）；**无 intent 但持久化 plan 指纹与 ledger `plan_fingerprint`
不一致** → fail closed（`recovery_required` + `authority_status =
"plan_ledger_mismatch"`），`run` 此时返回 `IMPORT_RECOVERY_REQUIRED` 而不在不一致的
plan 上动作。

stale 默认确定：batch 准备阶段对 selected proposal 重新哈希 source，changed /
deleted 的 proposal 标 `stale` 并从本批排除，其余继续；全 stale / 无 runnable 则
不创建 child，返回结构化 `IMPORT_NO_RUNNABLE_PROPOSALS`。实际复制时再次关闭
TOCTOU：source 以只读流式复制到 create-only staging，同时计算 SHA-256 / size；
匹配后才 atomic 发布 final attachment；journal frontmatter 在发布前不得引用
staging；不匹配触发 child failure + manifest compensation。M7 staging 使用 child job
目录内的确定性名字。final path 出现前，rollback manifest 已 durable 记录 target
`kind` / `rel_path` / expected SHA-256 / size，以及 staging inode 的
`hardlink_identity` ownership proof；publish 只通过该 staging inode 的 create-only
hard link 完成。故进程在 final publish 后、下一次 manifest 更新前崩溃时，新进程仍能
证明并补偿 owned final；相同 bytes 但不同 identity 的预先存在/racing target 绝不删除。
commit 或成功 rollback 后不保留 staging 文件/目录。源 hash / mtime 保持不变。

**batching transition 之前的三道确定性闸门（F1b/F2b/F3，均在首次 durable write / publish
之前 fail-closed，绝不留半成品）。** 在 stale 检测选出 runnable 集合之后、confirmed→
batching 转换之前依次校验：(1) runnable 集合不得有两个 proposal 声称同一 canonical
journal/attachment `target_rel_path`——否则 `IMPORT_PLAN_INVALID` +
`reason=duplicate_runnable_target`（覆盖 legacy/crafted plan，无 partial publish）；(2)
从实际 source 文件 re-derive 不可变 metadata（至少 `metadata_hash`，含 `capture_time`
value/source_tag/timezone_authority）必须与 plan 存储的 `source_facts` 一致——否则
`IMPORT_PLAN_INVALID` + `reason=source_facts_drift`（plan 在 confirm 后被篡改、或
source 无法 re-parse 时不支持格式/不可读）；(3) mint 出的 child id
`<parent>#batch-<seq>` 经 `validate_import_id(..., allow_child=True)` 复验——失败返回既有
`IMPORT_ID_INVALID`（既有 `reason` 如 `child_sequence`；child 分支的 sequence 检查先于总长
检查且 parent≤128、seq≤9 位时总长必然 ≤144，故 child-`length` 不可达；`length` 仍适用于
parent-only 路径——覆盖 `next_batch_sequence`
超出 9 位后缀的退化情形）。合法 parent 因 child 分支独立长度预算必然 mint 合法 child，
故 (3) 正常流程不触发。三道闸门均在 reservation / child job write / publish 之前。

child batch journal 必须符合 canonical journal schema（`schema_version`、合法
`topic`——photo 默认 `life`，不扩展 canonical topic 集合、`field_sources`、
provenance、frontmatter `attachments` 为 SSOT），只发布 selected attachments，尽
量复用现有 canonical helpers / authority。失败可返回明确 `recovery_required`，但
不得留下模糊半成品。

#### `import status`（additive）

对 parent review job，`status` 额外返回各 proposal `state`、derived queue counts、
`active_child_id`、`recovery_required`、`authority_status`（`null`，或 fail-closed 时
`"plan_ledger_mismatch"`，或存储的 child 权威损坏时投影为
`"invalid_child_authority"`）、`plan_fingerprint`、`plan_revision`、`queue_revision`、
`source_root_identity`，以及 `batches`：**ledger-derived、restart-safe、locator-free** 的
durable child batch 历史。`batches` 在每次读时从 ledger 中 `kind == "batch"` 且
`parent_review_job_id == <parent>` 的 job 派生——GUI 绝不缓存 child id 作为第二真相，这是 GUI
发现可回滚 batch 的**唯一来源**。稳定排序：oldest/lowest numeric `<parent>#batch-<seq>` 在前，
legacy/malformed id 走稳定 fallback（不依赖 dict 插入序）。`batches` 的 **locator-free** 语义现在由
`_read_ledger` 的 job-key 完整性门**强制**：任何 path-like/遍历/非词法的 durable `jobs` key 在派生
`batches` 之前就以 `IMPORT_LEDGER_CORRUPT`（`reason = "job_id_invalid"`）fail-closed，故 `import_id`
字段只能是闭合词法 id，绝无 locator 能经此泄漏；稳定 fallback 仅处理词法合法的 legacy plain id。
每个 batch 投影仅含安全字段：
`import_id`（child id，`#` 原样保留——GUI 之后放在 JSON rollback body 而非 URL path）、`state`、
`proposal_ids`（opaque ids）、`proposal_count`、`created_at`（legacy child 缺失时 fallback 到
`updated_at` 或 `null`）、`updated_at`、`rollback_available`；**绝不**暴露
`rollback_manifest_rel_path`、data-dir / source / journal 路径或 manifest 内容。`rollback_available`
为 true 仅当 child 与 rollback manifest **同时**满足：manifest 是 dict、`schema_version`
为 canonical rollback-manifest 版本、`import_id` 精确等于该 child id、
`parent_review_job_id` 精确等于该 parent id（显式传入、绝不从 child id 字符串推断）、`created_files`
为 list，且两处 state 同为 `committed`，或同为显式可恢复的 `rollback_in_progress` /
`rollback_failed` 并且两处 `rollback_retryable == true`。任一不满足即 fail closed 为 false——
`rolled_back`、non-retryable rollback failure、manifest 缺失、schema 错或缺失、state 不一致、
import_id 或 parent_review_job_id 错链、`created_files` 非 list、其他状态均为 false（status 不重新
实现 rollback、不 hash 用户文件、只读取既有 manifest 的结构 + 链接字段；真正 retry 仍执行完整
ownership / identity / hash / size revalidation）。
该投影在既有 authority reconciliation 之后**只读派生**：不改写
ledger、不递增 `queue_revision`、不重写文件；收敛后重复读为稳定 no-write。既有 job（fixture /
child batch）的 status 字段不变。

**损坏的存储 child 权威为只读（R1c）。** 当 parent job 存储的 `active_child_id` 损坏/恶意
（类型错误、非字符串、空/空白、path-like/词法非法、声称别的 parent 的 `#batch-<seq>` id、或
存在但否认属于本 parent 的 child 记录）时，`status`/`reviews` 这条**读路径**绝不自动修复、绝不
持久化、绝不由该敌意值派生路径、绝不 traceback、绝不泄漏该定位符。它在响应里确定性投影
`recovery_required = true` + `authority_status = "invalid_child_authority"` + `active_child_id = null`
（敌意值仍原样留在 ledger 上，仅不被外露），且重复调用逐字节一致——ledger bytes / SHA-256 /
size / mtime / `queue_revision` / `updated_at` / `proposal_states` 可证不变。判别在 reconciliation
与路径派生**之前**完成（词法校验先于 jobs dict 查找，故 unhashable/path-like 值既不逃逸也不崩溃）。
`None`/缺 key 是正常 settled 状态，**不**判为损坏（既有 no-op 行为不变）。各 mutation 路径
（`run`/`confirm`/`review`/`rollback`）对损坏权威确定地 fail closed：沿用各自既有 recovery 错误码
（`IMPORT_RECOVERY_REQUIRED` / `IMPORT_REVIEW_RECOVERY_REQUIRED`，退出码映射不变），仅加式带上
`authority_status = "invalid_child_authority"`，既不静默修复篡改、也不派生路径、也不泄漏。**有效**
权威（真实一致的 child，含崩溃窗口）的合法 crash-window 收敛行为完全不变。

**child 权威判别的精细区分（R1c rework）。** 一个无 child 记录的存储 `active_child_id` 现在按 id
形式二分：**正确前缀的 `<parent>#batch-<seq>` id**（`run_batch` 在写 child job entry **之前**就原子持久化
`active_child_id` + `selected_proposal_ids` + `batching`，故崩溃后该状态真实出现）仍判为 `"valid"`——
这是合法的 reservation-gap 崩溃窗口，读路径照常收敛（restore confirmed + clear，**允许**持久化）；
**任何其它**无记录 id（plain/legacy id、或已在上文判为 foreign 的 `#batch` id）均判为 `"invalid"` 损坏
权威——读路径只投影 recovery、绝不修复（candidate 曾把 plain unknown id 当 crash-window 静默
repair：restore + clear + persist，现已移除）。存在但不一致的 child 记录仍为 `"invalid"`（不变）。该
判别在路径派生与 jobs dict 查找之前完成。此外，一个**敌意的 durable `jobs` key**（path-like/遍历/非词法）
根本到不了判别这一步：`_read_ledger` 的 job-key 完整性门在上文 `job_id_invalid` 处对所有 consumer
single-point fail-closed——既不会进入 `batches` 投影（ locator-free 由该门**强制**），也不会被 settled
扫描提升为 `active_child_id`。

#### `import rollback`（additive）

`import rollback --import-id <parent_id>` 明确返回
`IMPORT_ROLLBACK_PARENT_NOT_ALLOWED`：parent review job 不可整体回滚，应回滚其
child batch job。child batch job 的 rollback **在 parent 的 per-parent lock 内**执行
（与 `run` 同一把锁，固定锁序为 ledger → parent → journals）：先做 plan/ledger authority
reconciliation，再把 child 自身精确 `proposal_ids` durable 投影为 `batching` +
`active_child_id=<child>` + `recovery_required=true`（一次 `queue_revision` 递增），之后才执行既有
checksum-guarded child rollback，然后用同一 membership 把对应 proposal 恢复 `confirmed`——
投影由本 child 实际成员驱动，绝不
复用 parent 的上一次选择。成功后 rescan 仍识别 `confirmed` / `imported`，被 rollback
恢复的 `confirmed` 不重复。无 parent 的 legacy / standalone batch job 使用
ledger → journals 锁序；不创建新 lock/store。删除前 manifest 与 child ledger 都先 durable
写入 `rollback_in_progress` + `rollback_retryable == true`；中途 unlink 失败返回 retryable
`IMPORT_ROLLBACK_INTERRUPTED`，parent 保持 `batching` + `recovery_required`，重试跳过已缺失的
owned target、重新验证仍存在目标后继续。仅所有删除完成且 manifest / ledger 收敛到
`rolled_back` 后，parent 才恢复 `confirmed`（再递增一次 `queue_revision`）。若在 child 开始前
中断，status 看到仍有效的 committed child 会恢复 `imported` 并清除 marker；若 child 已
`rolled_back`、但 final parent 投影前中断，status 会在确认 owned artifacts 已消失后恢复
`confirmed` 并清除 marker。首次 rollback 在任何删除 intent 前因 checksum 等 non-retryable
校验失败，会撤销本次 pending 投影并恢复 `imported`；parent pending 投影内部同时记录本次
rollback 开始时的 child state（不进入 status / GUI 投影，也不形成第二个 public state/store；
仅此内部 marker 改变时持久化但不递增 `queue_revision`）。若进程在同步撤销前中断，status 仅在
child 与正确链接 manifest **同时**为 non-retryable `rollback_failed` 且内部 origin 为
`committed` 时判定为 pre-delete refusal、恢复 `imported` 并清除 marker；从 durable
`rollback_in_progress` 开始的 retry 或缺失/不可信 origin 继续 fail closed 保持 recovery。

#### Review/batch additive 错误码

| code | 说明 |
|---|---|
| `IMPORT_ROLLBACK_PARENT_NOT_ALLOWED` | 对 parent review job 调用 rollback 被拒绝 |
| `IMPORT_ROLLBACK_INTERRUPTED` | owned target 顺序删除中断；retryable，durable rollback intent 保留并要求恢复 |
| `IMPORT_BATCH_ALREADY_ACTIVE` | parent 已有未结算 active child batch |
| `IMPORT_NO_RUNNABLE_PROPOSALS` | 本批无 runnable proposal（全 stale / 全 skipped） |
| `IMPORT_SOURCE_ROOT_UNREADABLE` | source root 不可读或非目录 |
| `IMPORT_SOURCE_ROOT_IDENTITY_MISMATCH` | 当前 locator 的 root identity 与 parent 记录不符 |
| `IMPORT_REVIEW_PLAN_MISSING` | 缺少持久化 review-plan.json |
| `IMPORT_PREVIEW_UNAVAILABLE` | preview 目标 unavailable（unsupported / stale / missing / unreferenced / proposal 不匹配） |
| `IMPORT_RECOVERY_REQUIRED` | parent 处于需要人工/补偿恢复的 `batching` 状态，或 plan/ledger 权威不一致（`authority_status = "plan_ledger_mismatch"`），或 `run` 命中损坏的存储 child 权威（`authority_status = "invalid_child_authority"`）——均拒绝 fail-closed，退出码映射不变 |
| `IMPORT_REVIEW_ALREADY_STAGED` | 同一 source root 已有 actionable review job 或 active child，拒绝创建第二个 job/plan（带 `existing_import_id`，non-retryable，零写入） |
| `IMPORT_REVIEW_EDIT_INVALID` | `import_review_edit.v1` payload 校验失败（未知字段/类型/topic/decision/未知 attachment id；零写入） |
| `IMPORT_REVIEW_PROPOSAL_FROZEN` | edit 目标 proposal 处于 `batching`/`imported` 冻结态，不可编辑 |
| `IMPORT_REVIEW_REVISION_CONFLICT` | edit 令牌过期（`expected_queue_revision` ≠ 当前值），retryable，带 `current_queue_revision`，零写入 |
| `IMPORT_REVIEW_RECOVERY_REQUIRED` | `import review` / edit / rollback 读到 recovery / plan-ledger mismatch 状态，或命中损坏的存储 child 权威（`authority_status = "invalid_child_authority"`），fail-closed，退出码映射不变 |
| `IMPORT_REVIEW_EMPTY_SELECTION_SKIPPED` | soft reason code：edit 空选择被强转为 `skipped`（成功响应，revisions 已递增） |
| `IMPORT_REVIEW_DATE_REQUIRED` | soft reason code：`confirmed` 但无可解析日期，保持 `pending`（成功响应，revisions 已递增） |

#### Review/batch additive schema versions

新增子对象 schema（additive，不改动既有 `import_*` 字符串）：
`import_review.v1`（confirm / stage / edit / review / reviews 响应）、
`import_review_plan.v1`（持久化 review-plan.json）、
`import_review_edit.v1`（单 proposal edit payload）、
`import_preview.v1`（preview metadata）。消费者必须忽略未知字段。

---

## search_journals

<!-- M16-CONTRACT: search -->

### M16 Public JSON Contract: search

#### JSON Shape / Top-Level Fields

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Whether the search executed successfully |
| `schema_version` | string | yes | `"v1.1.1"` — top-level output schema version (replaces `m16.search.v0`) |
| `provenance` | object | yes | Provenance envelope；详见 [v1.1.1 Observability Contract](#v111-observability-contract) |
| `diagnostics` | object | no | 仅 `--explain` 时出现；详见 [v1.1.1 Observability Contract](#v111-observability-contract) |
| `query_params` | object | yes | Echo of all input parameters |
| `merged_results` | array | yes | Unified result list across all levels |
| `l1_results` | array | yes | Level-1 (index-only) results |
| `l2_results` | array | yes | Level-2 (metadata) results |
| `l3_results` | array | yes | Level-3 (full-text) results |
| `semantic_results` | array | yes | Semantic pipeline results (empty if unavailable) |
| `entity_hints` | array | yes | Entity graph match hints for the query |
| `entity_expansion` | object | yes | Attribution block for deterministic Entity Graph query expansion: `{applied, expansions}` |
| `total_found` | int | yes | Number of results in this response (after `--limit` applied) |
| `total_matches` | int | yes | Total results matched (complete candidate set before truncation); always present, includes zero. `total_matches >= total_found` always holds. |
| `total_available` | int | yes | Total results available (may exceed page); alias for `total_matches` (backward compatibility) |
| `has_more` | bool | yes | Whether more results exist beyond current page |
| `retrieval_coverage` | object | yes | `retrieval_coverage.v1` authority for retrieval completeness (Phase 1); see `retrieval_coverage` Authority below |
| `display_summary` | string | yes | Human-readable "Showing X of Y results" summary |
| `semantic_available` | bool | yes | Legacy compatibility field; current value is `false` because in-tool semantic/vector search is disabled |
| `performance` | object | yes | Timing breakdown (`total_time_ms`, etc.) |
| `warnings` | array | yes | Non-fatal warnings |
| `index_status` | object | yes | Index freshness or pending-writes observability |
| `search_plan` | object\|null | yes | Structured query understanding (Round 11) |
| `ambiguity` | object | yes | Ambiguity signal report |
| `hints` | array | yes | Invocation-time hints (≤5) |
| `semantic_policy` | string | no | Deprecated compatibility echo for accepted `--semantic-policy` input |
| `semantic_fallback_used` | bool | no | Deprecated compatibility field; current value is `false` |
| `semantic_effective_policy` | string | no | `"deprecated_noop"` when legacy semantic flags were requested, otherwise `"off"` |
| `entity_graph_status` | object | no | Entity graph resolution status |

#### Field Semantics

- `success`: retrieval execution success, not "Agent has answered the user". Empty results (`E0303`) are still `success: true`.
- `merged_results`: primary result list consumers should use; items have `path`, `rel_path`, `title`, `date`, `rrf_score`. Results are capped by `--limit` (default 20) at the presentation layer. The retrieval core always returns the complete ranked candidate set; use `--limit 0` to bypass truncation.
- `total_matches`: complete candidate set size before presentation-layer truncation. Invariant: `total_matches >= total_found` always holds. Per CHARTER §1.11, the retrieval/ranking layer must not silently hard-cap results.
- `retrieval_coverage` (`retrieval_coverage.v1`): single authority for retrieval completeness as of Phase 1. `total_found` / `total_matches` / `total_available` / `has_more` are **projections** of it (`total_matches`/`total_available` = `observed_total`; `total_found` = `returned`; `has_more` = `next_offset is not None`). Full shape, complete/partial rules, the `partial_reasons` / `limits_applied` vocabulary, and the high-cardinality fail-closed behavior are documented in **`retrieval_coverage` Authority** below.
- `display_summary`: human-readable count such as "Showing 5 of 56 results" or "Showing all 20 results" (when `--limit 0` or no truncation applied).
- `query_params`: exact echo of all CLI inputs, including defaults filled in.
- `entity_expansion`: caller-facing attribution for Entity Graph query expansion. `applied` is true when at least one expansion was applied; `expansions[]` entries contain `from`, `to`, `via`, `entity_id`, and `primary_name`. S1 emits `via: "alias"`; relation attribution uses the same shape when relation-aware expansion is enabled. This field is a hint, not a gate, and is block-level attribution rather than per-result attribution.
- `performance.total_time_ms`: end-to-end search wall-clock time in milliseconds.
- `index_status`: two mutually exclusive paths — `freshness` (no pending writes) or `pending_before_search`/`auto_updated`/`pending_consumed` (writes in queue).
- `search_plan.intent_type`: `recall` / `count` / `compare` / `summarize` / `unknown`.
- `ambiguity.has_ambiguity`: signal only; Agent decides final interpretation.

#### Error Behavior / Error Codes

Errors use the structured unified format: `{success: false, error: {code, message, details, recovery_strategy}}`.

| Code | Meaning | Recovery Strategy |
|------|---------|-------------------|
| E0300 | Index does not exist | continue |
| E0301 | Search failed | fail |
| E0302 | Query is empty | ask_user |
| E0303 | No results | continue_empty |

Note: `E0303` / empty results indicate successful execution with no matches; callers must not treat this as a search failure.

#### SLO / Performance Expectation

- **p95 latency ≤ 500ms** (keyword-only path). Baseline: ~20ms.
- SLO is a monitoring target, not a unit-test gate.

#### schema_version Policy

`search` emits a top-level `schema_version` field set to `"v1.1.1"`. Schema versioning remains additive-only in sub-structures:
- `evidence_pack.schema_version = "1.0.0"` (when `--include-evidence` used on smart-search, which internally calls search).
- Top-level field names and types are stable; new fields may be added without a version bump.
- A `schema_version` bump will accompany any backward-incompatible change.

<!-- /M16-CONTRACT -->

### 端点

```bash
python -m tools.search_journals [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | string | ❌ | - | 搜索关键词 |
| topic | string | ❌ | - | 按主题过滤 |
| project | string | ❌ | - | 按项目过滤 |
| tags | string | ❌ | - | 按标签过滤（逗号分隔） |
| date_from | string | ❌ | - | 起始日期 (YYYY-MM-DD) |
| date_to | string | ❌ | - | 结束日期 (YYYY-MM-DD) |
| location | string | ❌ | - | 按地点过滤 |
| weather | string | ❌ | - | 按天气过滤 |
| mood | string | ❌ | - | 按心情过滤（逗号分隔） |
| people | string | ❌ | - | 按人物过滤（逗号分隔） |
| level | int | ❌ | 3 | 搜索层级: 1=索引, 2=元数据, 3=全文 |
| --no-index | flag | ❌ | false | 禁用 FTS 索引（默认启用 FTS） |
| --semantic | flag | ❌ | false | Deprecated compatibility no-op；接受但行为等同关键词 + Entity Graph |
| --no-semantic | flag | ❌ | false | Deprecated compatibility no-op；接受但行为等同关键词 + Entity Graph |
| --semantic-policy | enum | ❌ | fallback | Deprecated compatibility no-op；`fallback` / `hybrid` 均不触发向量检索 |
| --semantic-weight | float | ❌ | 1.0 | Deprecated compatibility no-op；不影响排序 |
| --fts-weight | float | ❌ | 1.0 | Deprecated compatibility no-op；不影响排序 |
| --limit | int | ❌ | 20 | 返回结果数量限制（默认 20）；传入 0 时返回全量结果（跳过呈现层截断） |
| --offset | int | ❌ | 0 | 结果偏移量（分页起始位置） |
| --read-top | int | ❌ | 0 | 读取前 N 条结果的完整正文（默认 0 不读取） |
| --explain | flag | ❌ | false | 输出搜索评分详情与 `diagnostics` 诊断块 |
| --diagnose | flag | ❌ | false | 输出最近搜索行为诊断摘要并退出 |
| --diagnose-days | int | ❌ | 7 | 诊断回看天数 |
| --enable-source-tier | flag | ❌ | false | 启用 source-tier 排名加权（gbrain Phase B）。开启后，搜索结果会按文档 frontmatter 丰富度（topic/people/tags/related_entries）进行额外加权；默认关闭以保持行为不变 |
| year | int | ❌ | - | L0 预过滤：限定年份（如 2026），先缩小候选集再进入搜索管道 |
| month | int | ❌ | - | L0 预过滤：限定月份（需配合 --year） |

### 返回值

```json
{
  "success": true,
  "query_params": {
    "query": "重构",
    "level": 3,
    "semantic": true
  },
  "merged_results": [
    {
      "path": "C:/Users/.../Documents/Life-Index/Journals/2026/03/life-index_2026-03-06_001.md",
      "rel_path": "Journals/2026/03/life-index_2026-03-06_001.md",
      "title": "搜索功能重构",
      "date": "2026-03-06",
      "rrf_score": 0.85
    }
  ],
  "entity_hints": [
    {
      "matched_term": "示例别名",
      "entity_id": "EXAMPLE-PERSON-001",
      "primary_name": "示例人物",
      "entity_type": "actor",
      "expansion_terms": ["示例人物", "示例别名"],
      "reason": "alias_match"
    }
  ],
  "entity_expansion": {
    "applied": true,
    "expansions": [
      {
        "from": "Ally",
        "to": ["Alice"],
        "via": "alias",
        "entity_id": "actor-alice",
        "primary_name": "Alice"
      }
    ]
  },
  "total_found": 5,
  "total_matches": 56,
  "total_available": 56,
  "has_more": true,
  "display_summary": "Showing 5 of 56 results",
  "semantic_available": false,
  "semantic_effective_policy": "deprecated_noop",
  "warnings": ["--semantic is deprecated and ignored; using keyword + Entity Graph search."],
  "performance": {"total_time_ms": 45}
}
```

### `retrieval_coverage` Authority (`retrieval_coverage.v1`)

`retrieval_coverage` is the single authority for retrieval completeness as of Phase 1; the legacy `total_found` / `total_matches` / `total_available` / `has_more` fields are projections derived from it so they cannot drift (`total_matches`/`total_available` = `observed_total`; `total_found` = `returned`; `has_more` = `next_offset is not None`). As of Phase 2B, `aggregate` (projected at `evidence_pack.retrieval_coverage`) and `index-tree` `discover`/`navigate` responses also carry a `retrieval_coverage.v1` object projected under this same authority vocabulary.

Shape:

```json
{
  "schema_version": "retrieval_coverage.v1",
  "status": "complete | partial",
  "observed_total": "<int, post-threshold admitted-set size>",
  "returned": "<int, items in THIS response window>",
  "next_offset": "<int | null>",
  "partial_reasons": ["unread_page", "threshold_excluded", "source_cap", "index_not_fresh"],
  "limits_applied": ["fts_threshold:<n>", "fts_min_hits:<n>", "result_limit:<n>", "l2_source_cap:<n>"]
}
```

- `status` is `"complete"` **iff** this single response carries the whole admitted set with no remainder: `returned == observed_total`, `next_offset` is null, and both `partial_reasons` and `limits_applied` are empty. A `partial` status **always** carries ≥1 entry in `partial_reasons` (there is no "partial without a reason"); each reason explains one honest defect. The `partial_reasons` vocabulary is closed and every entry has a real emission path; reasons without a reachable Phase 1 emission path were removed rather than advertised.
- `unread_page` is recorded whenever this response window does NOT carry the whole admitted set (`returned < observed_total`) — including a nonzero-offset final page where `next_offset` is already null. `next_offset` / `has_more` signal **only** whether the same deterministic query can mechanically continue to a next page; they do not imply completeness, and `next_offset` is emitted only when it strictly advances past the current offset (an empty window never yields `next_offset=0` or a cursor equal to the offset). (The tool holds no snapshot/cursor between pages; if the corpus changes between requests, each page recomputes against the current `observed_total` and stays honest — it never fabricates `complete`.)
- `result_limit:<n>` is recorded in `limits_applied` only when the presentation `limit` truly bound the result window (`offset + limit < observed_total`); a final page whose shortfall comes from the `offset` alone records no `result_limit`, and a `limit` that excluded nothing records nothing. `fts_min_hits:<n>` is recorded when the segmented-query min-hits post-filter dropped ≥1 candidate that no fallback recovered (a fully recovered exclusion records nothing). `l2_source_cap:<n>` (from the existing `l2_total_available` field, which preserves the upstream source total even when an L0 candidate filter narrows the returned window) is recorded only when the L2 metadata source was actually capped (`l2_truncated=true`).
- Default token-match relevance threshold is `0`: neither the FTS layer nor the merge/ranking layer drops low-relevance token-matches via a dynamic threshold. An explicit nonzero threshold marks `partial` with `threshold_excluded` + `fts_threshold:<n>` **only when it actually excludes ≥1 candidate**; a configured threshold that excludes 0 does not mark partial. `min_relevance=0` is the intentional Phase 1 recall-first default: search passes an explicit zero token-match threshold and thereby bypasses the legacy high-frequency dynamic threshold; this is by design, not an omission.
- Level 1/2 responses build `retrieval_coverage` from the level's own complete result array (`l1_results` / `l2_results`; `merged_results` stays empty). The presentation layer paginates that array — not the empty `merged_results` — and scopes `returned`/`offset`/`next_offset` to the page window, with the legacy totals projected from the coverage authority.
- **High-cardinality protection**: if the admitted candidate set exceeds the safety bound (`FTS_MAX_RETRIEVAL_BOUND`), the search **fails closed** rather than returning a truncated subset that could be mistaken for complete. It surfaces a machine-readable resource failure via the standard error envelope: `success:false`, `error.code=E0301`, `error.details.reason="retrieval_resource_bound"` (with `observed` and `bound`), no `merged_results`, and no `retrieval_coverage`. The CLI exits nonzero. Ordinary sets (at/below the bound) remain fully complete.

### Round 7 新增返回字段

- `entity_hints`：search 对 query 中实体命中结果的结构化解释字段
- 每个 hint 包含：`matched_term` / `entity_id` / `primary_name` / `entity_type` / `expansion_terms` / `reason`
- `entity_hints[].reason` includes direct entity/alias reasons such as `alias_match`,
  plus `relation_match` when a controlled relationship term expands through confirmed
  graph edges.
- `entity_hints` 属于 read-only suggestion layer，不会修改 query 语义本身；它与 `query_params.expanded_query` 互补存在
- `entity_expansion`：search 对 Entity Graph 扩展的块级归因字段，形状为 `{applied, expansions}`；每个 expansion 包含 `from` / `to` / `via` / `entity_id` / `primary_name`
- `entity_expansion.applied=false` 时 `expansions=[]`；该字段只解释确定性扩展来源，不决定是否展示或过滤任何结果

### Round 11 新增返回字段

#### `search_plan` — 结构化查询理解

L2 Deterministic Preprocessing 的输出，描述 query 在进入检索之前被 CLI 如何结构化理解。**caller-facing field**，供 Agent / Web / 上层 orchestrator 消费。

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `raw_query` | string | 原始查询文本 |
| `normalized_query` | string | 标准化后查询（去标点、trim、全角转半角） |
| `intent_type` | string enum | 查询意图：`recall` / `count` / `compare` / `summarize` / `unknown` |
| `query_mode` | string enum | 查询模式：`keyword` / `natural_language` / `mixed` |
| `keywords` | string[] | 从 query 提取的关键词列表 |
| `date_range` | object \| null | 解析出的时间范围：`{since, until, source}` |
| `topic_hints` | string[] | 推断的主题映射（work/health/learn 等） |
| `entity_hints_used` | array | 使用的实体 hint 列表 |
| `expanded_query` | string | 扩展后的查询文本 |
| `pipelines` | object | 启用的管道：`{keyword: bool, semantic: bool}` |

> `search_plan` 不替用户下最终结论，只记录 query 被如何理解。

#### `ambiguity` — 歧义信号报告

CLI 对"存在多个合理解释 / 需要上层 judgment"的结构化声明。**报告 signal，不替 Agent 裁决**。

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `has_ambiguity` | boolean | 是否存在歧义信号 |
| `items` | array | 歧义信号列表 |
| `items[].type` | string | 歧义类型枚举（见下表） |
| `items[].severity` | string | `low` / `medium` / `high` |
| `items[].reason` | string | 为什么认为这里有歧义 |
| `items[].candidates` | string[] | 可选的多种解释 |

歧义类型枚举：

| type | severity | 说明 |
|------|----------|------|
| `aggregation_requires_agent_judgement` | high | count/compare/summarize 需要 Agent 判断最终答案 |
| `time_range_interpretation` | medium | 相对时间表达存在多种解释窗口 |
| `entity_resolution_multiple_candidates` | medium | 实体解析返回多个候选 |
| `query_too_broad` | low | query 过宽，结果可能不可信 |

#### `hints` — 调用时局部提示

L3 Invocation-Time Hints，提供与本次调用相关的局部提示。**不变成长篇 prescriptive prompt，不替代 SKILL.md**。

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `type` | string | 提示类型（如 `retrieval_boundary`、`refinement_suggestion`、`time_range_parsed`） |
| `severity` | string | `low` / `medium` / `high` |
| `message` | string | 提示内容（≤ 120 字符） |

> 单次调用 hints ≤ 5 条。

#### 三者边界

| 字段 | 所属层 | 作用 | 不做什么 |
|------|--------|------|----------|
| `search_plan` | L2 | 记录 query 被如何结构化理解 | 不替用户下最终结论 |
| `ambiguity` | L2→L4 边界 | 报告歧义信号 | 不替 Agent 裁决 |
| `hints` | L3 | 提供调用时局部提示 | 不变成长篇 prescriptive prompt |

> 当前搜索结果中的 `path` 经常是绝对路径；上层调用方不应直接把它拼进 Web 路由。

### `index_status` — 索引状态可观测性

搜索返回值包含 `index_status` 字段，提供索引更新状态的机读信号。存在两条互斥路径：

#### No-pending freshness 路径（无待消费写入）

当 pending 队列为空时，`index_status` 包含 `freshness` 子字段：

```json
{
  "index_status": {
    "freshness": {
      "fts_fresh": true,
      "vector_fresh": true,
      "overall_fresh": true,
      "issues": []
    }
  }
}
```

- `freshness`：`check_full_freshness()` 的完整报告
- `vector_fresh` 是 legacy compatibility 字段；当前始终为 `true`，不代表存在向量索引。
- `auto_updated`：若索引 stale 触发了增量构建，为 `true`；否则为 `false`（仅 stale 时出现）

#### Pending-writes 路径（有待消费写入）

当 pending 队列非空时，`index_status` 包含 pending 可观测性字段：

```json
{
  "index_status": {
    "pending_before_search": true,
    "auto_updated": true,
    "pending_consumed": true
  },
  "pending_consumed": true
}
```

| 子字段 | 类型 | 成功值 | 失败值 | 说明 |
|--------|------|--------|--------|------|
| `pending_before_search` | bool | `true` | `true` | 搜索开始时 pending 队列非空。此字段仅在该路径存在，值**始终为 `true`**（成功/失败均不变） |
| `auto_updated` | bool | `true` | `false` | 增量索引构建是否成功执行 |
| `pending_consumed` | bool | `true` | `false` | pending 队列是否已清空 |

- 顶层 `pending_consumed`（bool）同时保留，作为向后兼容的快速判断字段
- 构建失败时，`warnings` 数组中追加 `pending_index_update_failed: {error}` 条目，pending 队列保留以供下次搜索重试

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0302 | 查询为空 | ask_user |
| E0303 | 无结果 | continue_empty |
| E0300 | 索引不存在 | continue |

### caller-facing 解释语义

- `search_journals` 返回结果列表表示 retrieval execution 成功，不等于 Agent 已完成最终用户答案
- `E0303` 或空结果应解释为“执行成功但没有匹配结果”，不应解释为执行失败
- 工具 failure 与空结果必须在调用方叙述中严格区分
- Web / Agent 调用方如需做自然语言总结，应基于**同一次 retrieval 返回的结果集**进行解释；不应在上层路由中再维护第二套并行检索 / merge / ranking 真相

---

## smart_search

<!-- M16-CONTRACT: smart-search -->

### M16 Public JSON Contract: smart-search

#### JSON Shape / Top-Level Fields

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Whether the search executed successfully |
| `schema_version` | string | yes | `"m16.smart_search.v0"` — top-level output schema version |
| `query` | string | yes | User's original query |
| `rewritten_query` | string | yes | Search query used by deterministic scaffold; equals original unless deterministic routing expands it |
| `filtered_results` | array | yes | Primary bounded result list from deterministic retrieval |
| `summary` | string | yes | Empty in deterministic scaffold mode; host agents synthesize from returned evidence |
| `citations` | array | yes | Empty in deterministic scaffold mode; host agents cite returned evidence |
| `agent_decisions_summary` | string | conditional | Compatibility summary when `--explain` is absent; currently reports zero in-tool decisions |
| `agent_decisions` | array | conditional | Compatibility array retained by `--explain`; currently empty because orchestration decisions belong to the Host Agent |
| `agent_unavailable` | bool | yes | `true` for deterministic scaffold output; host agent synthesis happens outside the tool |
| `diagnostics` | object | no | 仅 `--explain` 时出现；确定性诊断块，详见 [v1.1.1 Observability Contract](#v111-observability-contract) |
| `performance` | object | yes | Timing breakdown (`total_time_ms`, conditional sub-fields) |
| `smart_search_mode` | string | yes | `deterministic_scaffold` or `deterministic_aggregate` |
| `agent_instructions` | object | yes | Provider-free guidance for the calling agent |
| `answer_scaffold` | object | yes | Suggested response shape and citation policy for the calling agent |
| `query_plan` | object | yes | Query decomposition and strategy metadata |
| `answer` | object | no | 当前产品 CLI 不输出；语言合成属于 Host Agent + Life Index Skill |
| `evidence_pack` | object | no | Additive: retrieval evidence (requires `--include-evidence`) |
| `aggregate_result` | object | no | Additive: deterministic aggregate output when aggregate intent detected |
| `retrieval_coverage` | object | yes (`deterministic_scaffold` path) | Additive (Phase 2A): `retrieval_coverage.v1` completeness authority scoped to THIS response window; absent on the `deterministic_aggregate` short-circuit |
| `events` | array | no | Piggyback event notifications |

#### Field Semantics

- `success`: retrieval execution success. Evidence pack construction failure does not affect this.
- `filtered_results`: primary result list for consumers. Items have `title`, `path`, `date`, `rrf_score`.
- `smart_search_mode`: default is `deterministic_scaffold`; current explicit
  `--synthesize` is an accepted deterministic no-op/no-answer compatibility path.
- `agent_instructions` / `answer_scaffold`: the v1 agent-ready contract. Calling agents should synthesize from returned evidence and cite only returned results.
- `query_plan.strategy`: `keyword_only` for default search; deterministic
  strategy names may be added for bounded tool-side routing.
- In deterministic scaffold mode, natural-language queries reuse the shared
  `SearchPlan` keywords as bounded `query_plan.sub_queries` instead of sending
  only the whole sentence to keyword search. Each sub-query calls keyword +
  Entity Graph search. Legacy semantic fallback fields remain present as
  disabled/no-op compatibility fields.
- `agent_unavailable`: current product CLI returns `true`; the Host Agent owns synthesis.
- `performance`: non-stable; sub-fields may expand. Consumers should tolerate unknown keys.
- `answer.*`: not emitted by the product CLI; consumers synthesize from returned evidence in the Host Agent.
- `aggregate_result`: computed by `tools.aggregate.core.run_aggregate`; LLM never computes counts.
- `retrieval_coverage` (Phase 2A): the additive completeness authority for this
  smart-search response. `filtered_results` is a bounded window of at most 15
  candidates (`ORCHESTRATOR_MAX_CANDIDATES`) — never treat it as the user's
  whole journal record set. `status` is `complete` **iff** this one response
  carries the whole admitted set with no remainder (`returned == observed_total`,
  `next_offset` null, empty `partial_reasons` / `limits_applied`); anything else
  is honestly `partial` with ≥1 reason. Full shape and continuation semantics:
  see **Honest Coverage & Continuation (Phase 2A)** below.

#### Error Behavior / Error Codes

Errors use the structured unified format: `{success: false, error: {code, message, details, recovery_strategy}}`.

Evidence pack uses best-effort failure: `success: true`, no `evidence_pack`, but `performance.evidence_build_ms` and `performance.evidence_error` present.

#### SLO / Performance Expectation

- **Default path p95 ≤ 8s**. Degraded mode p95 ≤ 500ms.
- SLO is a monitoring target, not a unit-test gate.

#### schema_version Policy

`smart-search` emits a top-level `schema_version` field set to `"m16.smart_search.v0"`. Schema versioning is additive-only:
- `evidence_pack.schema_version = "1.0.0"` (when `--include-evidence` is used).
- Top-level field names and types are stable; new fields may be added without a version bump.
- A `schema_version` bump will accompany any backward-incompatible change.

<!-- /M16-CONTRACT -->

### 端点

```bash
life-index smart-search --query "..." [options]
python -m tools.smart_search --query "..." [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | string | ✅ | - | 自然语言搜索查询 |
| explain | flag | ❌ | false | 保留稳定兼容字段并输出确定性 `diagnostics` / provenance；不表示工具内 Agent 或 LLM 决策 |
| include-evidence | flag | ❌ | false | 在输出中包含 evidence pack |
| format-entity-annotated | flag | ❌ | false | 与 `--include-evidence` 同用时，增加人类可读的 `formatted_evidence` |
| synthesize | flag | ❌ | false | 至少保留两个主版本；不注入 LLM、不添加 `answer`、不改变 domain payload，并在 stderr 发出一次稳定弃用警告；见命名 transition block |
| offset | int | ❌ | 0 | 公开 continuation 参数：传入上一响应 `retrieval_coverage.next_offset` 获取下一窗口；必须 ≥ 0，非法值以 argparse 错误退出（code 2）。未传递时调用形状与既有契约逐字节一致 |

### 返回值

**默认输出**（无额外标志）：

```json
{
  "success": true,
  "query": "我和女儿之间有哪些珍贵的回忆？",
  "rewritten_query": "我和女儿之间有哪些珍贵的回忆？",
  "filtered_results": [
    {"title": "...", "path": "...", "date": "...", "rrf_score": 0.85}
  ],
  "summary": "",
  "citations": [],
  "agent_decisions_summary": "0 decisions made",
  "agent_unavailable": true,
  "smart_search_mode": "deterministic_scaffold",
  "agent_instructions": {
    "schema_version": "smart_search.agent_instructions.v1",
    "role": "calling_agent",
    "mode": "deterministic_scaffold",
    "steps": [
      "Use filtered_results as bounded evidence; do not cite outside returned results."
    ]
  },
  "answer_scaffold": {
    "schema_version": "smart_search.answer_scaffold.v1",
    "query": "我和女儿之间有哪些珍贵的回忆？",
    "citation_policy": "cite_only_returned_results",
    "result_count": 3
  },
  "query_plan": {
    "schema_version": "v1.1.1",
    "raw_query": "我和女儿之间有哪些珍贵的回忆？",
    "expanded_query": "我和女儿之间有哪些珍贵的回忆？",
    "sub_queries": ["我和女儿之间有哪些珍贵的回忆？"],
    "strategy": "keyword_only",
    "fallback_decision": false
  },
  "retrieval_coverage": {
    "schema_version": "retrieval_coverage.v1",
    "status": "complete",
    "observed_total": 3,
    "returned": 3,
    "next_offset": null,
    "partial_reasons": [],
    "limits_applied": []
  },
  "performance": {
    "total_time_ms": 142.5,
    "rewrite_time_ms": 0,
    "filter_time_ms": 0,
    "search_time_ms": 45.0,
    "total_available": 3
  }
}
```

#### 默认输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 搜索是否成功执行 |
| `query` | string | 用户原始查询 |
| `rewritten_query` | string | 确定性 scaffold 使用的检索查询；通常等于原始查询 |
| `filtered_results` | list[dict] | 主要结果列表，由确定性检索返回 |
| `summary` | string | 默认确定性模式为空；宿主 agent 负责总结 |
| `citations` | list[string] | 默认确定性模式为空；宿主 agent 负责引用返回证据 |
| `agent_decisions_summary` | string | CLI 默认输出的兼容性摘要；当前为零个工具内决策，传递 `--explain` 时替换为 `agent_decisions` |
| `agent_unavailable` | bool | `true` 表示工具只返回 scaffold，宿主 agent 负责合成 |
| `smart_search_mode` | string | `deterministic_scaffold` / `deterministic_aggregate` |
| `agent_instructions` | object | 给调用 Agent 的消费规则：只基于返回证据回答，不得外部补证 |
| `answer_scaffold` | object | 给调用 Agent 的答案结构建议与引用政策 |
| `query_plan` | object | 查询分解、检索策略与 fallback 判定 |
| `retrieval_coverage` | object | Additive（Phase 2A）：本响应窗口的 `retrieval_coverage.v1` 完整性权威；`deterministic_aggregate` 短路路径不携带 |
| `performance` | object | 性能指标（详见下方 `performance` 子字段表） |

#### `--explain` 输出变化

当传递 `--explain` 时，`agent_decisions_summary`（string）被替换为兼容性字段 `agent_decisions`（list[dict]）。当前工具内不拥有 LLM 决策阶段，因此该数组为空；确定性执行来源记录位于 evidence/planner 元数据。未传递 `--explain` 时，输出包含当前为 `"0 decisions made"` 的 `agent_decisions_summary`，不含 `agent_decisions`。

#### Honest Coverage & Continuation（Phase 2A）

`smart-search` 在 `deterministic_scaffold` 路径上始终输出顶层 `retrieval_coverage`（`retrieval_coverage.v1`），它是本响应窗口完整性的**唯一权威**。字段结构与 `search` 的 `retrieval_coverage` Authority 一节完全相同（`schema_version` / `status` / `observed_total` / `returned` / `next_offset` / `partial_reasons` / `limits_applied`）；区别仅在语义范围：

- **窗口语义**：`filtered_results` 交付的是同一确定性 ranked list 的 `[offset, offset+15)` 窗口（15 = `ORCHESTRATOR_MAX_CANDIDATES`）。`observed_total` 是 admitted set 全量大小（单查询为 search child 的 `observed_total`；多查询为融合去重后的唯一候选数——任一 child 不完整时它是观察下界）。窗口被截断时 `partial_reasons` 必含 `unread_page`，`limits_applied` 记录 `result_limit:15`（仅当窗口、而非 offset，真正约束了本响应）。
- **child 权威消费**：每个 search child 的 `retrieval_coverage.v1` 是唯一完整性输入。任一 child `partial`（无论其 legacy `has_more` / `total_*` 投影是否看起来完整、fused unique 是否 < 15），父级即 `partial` 并继承该 child 的 `partial_reasons` / `limits_applied`。全部 child `complete` 且融合唯一候选 ≤ 15 时父级才是 `complete`。
- **`partial_reasons` 封闭词表（Revision 4）**：smart-search 层与检索层共用同一封闭词表，集中在 `tools/search_journals/coverage.py`，共五个词条：`unread_page` / `source_cap` / `threshold_excluded` / `child_failed` / `index_not_fresh`。不发明、不发布其它词条。
  - `child_failed` — 任一 search child 返回失败 envelope，**或** child 响应没有/带有无效的 `retrieval_coverage.v1` 权威对象（旧 mock / 旧调用方兼容输入）。两种情况都无法证明完整性：响应保留已有安全结果（不伪造 success+complete），fail closed 为 `partial`，并发出**安全 warning**（失败 envelope 为 `subquery_failed: N sub-quer(y|ies) returned failure envelopes; ...`；权威缺失为 `subquery_coverage_missing: N sub-quer(y|ies) returned no valid retrieval_coverage.v1; ...`），这些 warning 只携带计数，不含子查询文本或任何用户内容。legacy `has_more` / `total_*` 只是兼容投影，`has_more=true` 或 `total > 已观察` 时额外记 `unread_page`。
- **Continuation（机械可执行）**：`next_offset` 是非空整数时，用同一 query（确定性 query/filter/date 语义不变）+ 公开 continuation 参数取下一页：
  - Python 入口：`SmartSearchOrchestrator().search(query, offset=next_offset)`
  - CLI 入口：`life-index smart-search --query "..." --offset <next_offset>`
  - 页间按稳定 journal `rel_path` 去重累计，直到 `next_offset` 为 null。最终页（非零 offset）仍是 `partial`（`unread_page`）——它不携带全集，只有累计后的消费方才能宣称看全。`status=complete` 的单响应才自带完整性证明。
  - 工具不持有 snapshot/cursor/session 状态：语料在页间变化时每页按当前 admitted set 重算并保持诚实。offset 传给声明了显式 `offset` 参数的检索后端；生产后端（`hierarchical_search`）返回全量 admitted set，窗口由 smart-search 层本地应用。多查询 continuation 不向 child 转发 offset——融合排序在本地开窗是唯一无重复/无遗漏且无需持久 authority 的方式。
  - 融合排序对同分（equal `rrf_score`）候选以稳定 journal identity（`rel_path`/`path`/`title`）作次序键，排序不依赖 child 迭代顺序，页边界可重复执行。
- **兼容投影同源（Revision 4）**：`total_matches` / `total_available` / `total_found` / `has_more`（含 `evidence_pack.has_more` 与内部 raw envelope）全部由 `project_legacy_from_coverage(retrieval_coverage)` 投影：`total_matches = total_available = observed_total`，`total_found = returned`，**`has_more` 仅表示存在机械下一页（`next_offset is not None`）**，不表示 partial 状态。不可续页的 `partial`（如 `child_failed`、权威缺失）诚实地 `has_more=false`；完整性只由 `retrieval_coverage.status` / `partial_reasons` 判定，`has_more=false` 与 `status=partial` 并存不矛盾。
- `deterministic_aggregate` 短路路径不执行检索、不携带 `retrieval_coverage`；其完整性契约由 `aggregate` 自身负责。

#### `performance` 子字段

| 子字段 | 类型 | 条件 | 说明 |
|--------|------|------|------|
| `total_time_ms` | float | 始终 | 总搜索耗时（毫秒） |
| `rewrite_time_ms` | float | 始终 | 当前确定性产品 CLI 路径固定为 `0` |
| `filter_time_ms` | float | 始终 | 当前确定性产品 CLI 路径固定为 `0` |
| `search_time_ms` | float | 始终 | 底层检索耗时 |
| `total_available` | int | 始终 | 单查询为 Core 报告的可用总数；多子查询为合并前已观察到的唯一候选数下界，不对可能已截断的子结果集合宣称未知的精确并集总数 |
| `evidence_build_ms` | float | 仅传递 `--include-evidence` 时 | Evidence pack 构建耗时；`--synthesize` 单独使用不触发构建 |
| `evidence_error` | string | evidence 构建失败且 `--include-evidence` 时 | 构建失败错误信息 |

> **稳定性说明**: `performance` 子字段集合可能在未来扩展。调用方应容忍未知键。

#### Consumer Guidance（字段消费指引）

| 字段 | Agent 消费者 | GUI 消费者 | 稳定性 |
|------|-------------|-----------|--------|
| `success` | 必须检查 | 必须检查 | **stable** |
| `query` | 引用 | 展示 | **stable** |
| `filtered_results` | 主要结果 | 展示 | **stable** |
| `agent_instructions` | 默认消费规则 | 不需要 | **stable** |
| `answer_scaffold` | 默认答案结构 | 不需要 | **stable** |
| `query_plan` | 检索策略诊断 | 可选（高级） | **stable additive** |
| `smart_search_mode` | 路径判断 | 可展示 | **stable** |
| `summary` | 默认空；宿主 agent 可忽略 | 展示 | **stable** |
| `citations` | 默认空；宿主 agent 应引用 evidence | 可点击链接 | **stable** |
| `answer` / `answer.*` | 当前产品 CLI 不输出；`--synthesize` 不注入 LLM、不添加 `answer`，并保持普通 deterministic domain payload；see the named `--synthesize` transition authority block | 当前无此字段；语言合成由 Host Agent + Skill 完成 | **stable** |
| `evidence_pack` | 按需 | 按需 | **stable** |
| `formatted_evidence` | 可展示 | 可展示 | **stable additive** — 仅 `--include-evidence --format-entity-annotated` 时出现 |
| `aggregate_result` | aggregate/count/bucketed-frequency queries | count/bucket/claim display | **stable additive** - deterministic `aggregate` result; LLM never computes counts |
| `retrieval_coverage` | 完整性判定与 `--offset` 续页的唯一权威；`partial` 时必须向用户披露 `partial_reasons` / `limits_applied` | 可展示完整性状态 | **stable additive**（Phase 2A）— `deterministic_scaffold` 路径始终存在 |
| `evidence_pack.items[].entity_matches` | 按需 | 按需 | **stable**，实体匹配溯源；消费者应容忍缺失字段 |
| `rewritten_query` | 不需要 | 不需要 | **internal** — 检索查询诊断，消费者应使用 `query` |
| `agent_unavailable` | 不需要 | 不需要 | **internal** — 诊断信号，UI 应从 `answer`/`summary` 存在性推断 |
| `agent_decisions_summary` | 不需要 | 不需要 | **internal** — 仅调试用 |
| `agent_decisions` | 不需要 | 不需要 | **internal** — 仅 `--explain` 时出现 |
| `performance.*` | 不需要 | 可选（高级） | **non-stable** — 性能分析用，子字段可能扩展 |

> **稳定性定义**: `stable` = 字段语义承诺不变；`internal` = 仅用于调试/诊断，可能在未来移除或改名；`non-stable` = 子字段集合可能扩展，消费者应容忍未知键。

### 说明

- `smart-search` 产品 CLI 不启用工具内嵌 LLM；宿主 agent / Skills 负责 query 改写、多轮检索策略、判断与总结。当前显式 `--synthesize` 是 accepted deterministic no-op/no-answer 兼容路径，见下方 transition block
- Clear aggregate/count/bucketed-frequency intents may short-circuit into deterministic `aggregate` and add top-level `aggregate_result`; existing smart-search fields remain present.
- `aggregate_result` is computed by `tools.aggregate.core.run_aggregate`; LLM must not compute the count.
- 默认模式下 `agent_unavailable: true`，表示工具只提供确定性检索 scaffold
- Data Minimization：工具返回 bounded evidence；后续读取由宿主 agent 显式调用
- 实现详见 `docs/ARCHITECTURE.md` §5.8

### Aggregate Result（`aggregate_result`）

当 `smart-search` 通过确定性路由检测到 aggregate/count/bucketed-frequency 意图时（如 "过去60天我有多少天晚睡" 或 "按月统计一下我今年写日志的频率"），返回值增加顶层 `aggregate_result` 字段。

> **确定性路由**: 路由使用正则模式匹配，不依赖 LLM。`tools.aggregate.core.run_aggregate` 是唯一的计算器。LLM 永远不计算计数。

`aggregate_result` 的值是 `run_aggregate` 的完整输出，包含 `command`、`unit`、`range`、`predicate`、`result`（含 `count`、`denominator`、`exactness`、`confidence`）、`buckets`、`matched_entries`、`excluded_entries`、`unknown_entries`、`evidence_paths`、`limitations`、`performance`、`claim_envelope`、`evidence_pack`。

#### 当前支持的自动路由模式

| 模式 | 匹配条件 | 路由到 |
|------|----------|--------|
| 晚睡计数 | "过去N天" + 聚合信号（多少/统计/count） + "晚睡" | `unit=day`, `predicate=entry_time_after=22:00`, `range=<anchor-N+1>..<anchor>` |
| 写日志频率趋势 | "今年" + 写日志关键词 + 聚合信号（频率/趋势/统计） | `unit=month`, `predicate=journal_count`, `range=<year-01-01>..<anchor>` |

> `LIFE_INDEX_TIME_ANCHOR=YYYY-MM-DD` 环境变量用于覆盖当前日期锚点（测试用）。未设置时使用 `date.today()`。

#### Additive 契约

- `aggregate_result` 是**纯增量的**：不存在时不影响现有字段
- 所有现有 smart-search 必需字段（`success`、`query`、`filtered_results` 等）始终保留
- 非 aggregate 意图的查询**不会**包含 `aggregate_result`
- `aggregate_result` 出现时，smart-search 短路到 deterministic aggregate；normal search 不执行，但既有输出字段仍以空列表/空字符串形式保留
- `aggregate_result.claim_envelope` 与 `aggregate_result.evidence_pack` 是 additive 子字段；它们不表示完整 Index Tree API 或 batch/cursor 平台已经实现

### Evidence Pack（`--include-evidence`）

默认行为（不传递 `--include-evidence`）下，返回值**不包含** `evidence_pack` 字段。

当传递 `--include-evidence` 时，返回值增加 `evidence_pack` 字段，结构如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `evidence_pack.query_context` | object | 查询上下文，含 `query`、`expanded_query`、`search_plan`、`entity_hints` |
| `evidence_pack.items` | array | 检索证据项列表，每项含 `document`（文档引用）、`scores`（评分明细）、`snippet`（片段）、`entity_matches`（实体匹配溯源，仅匹配时出现） |
| `evidence_pack.semantic_candidates` | array | Deprecated legacy 字段；当前恒为空列表 |
| `evidence_pack.total_available` | int | 与 `performance.total_available` 一致；多子查询时为已观察到的唯一候选数下界 |
| `evidence_pack.has_more` | bool | 仅表示存在机械下一页（由 `retrieval_coverage` 投影，`has_more = next_offset is not None`）。不可续页的 partial（如 `child_failed`）诚实地为 `false`；完整性只由 `retrieval_coverage.status` / `partial_reasons` 判定 |
| `evidence_pack.no_confident_match` | bool | **检索层级信号**：底层搜索管道是否未找到高置信度匹配。这是检索质量指标，不是答案质量信号。调用方不应将其等同于 `answer.confidence` 的判断依据 |
| `evidence_pack.diagnostics` | object | **确定性检索诊断**。不依赖 LLM，从已有搜索结果字段推导。详见下方 Diagnostics 子节 |
| `evidence_pack.schema_version` | string | 证据包 schema 版本。当前为 `"1.0.0"`。旧 payload 反序列化时默认 `"1.0.0"` |
| `performance.evidence_build_ms` | float | evidence pack 构建耗时（毫秒） |

> **Forward-compatibility**: Evidence pack 的每个对象可能包含未在本文档中列出的额外字段（来自内部 `extra` 字典）。调用方应容忍未知字段，不应做严格 schema 校验。所有 9 个内部 dataclass（`ScoreBreakdown`、`DocumentRef`、`EntityMatch`、`EvidenceItem`、`SemanticCandidate`、`QueryContext`、`PipelineComposition`、`EvidenceDiagnostics`、`EvidencePack`）均携带 `extra` 字典；`from_dict()` 将未知键保留到 `extra`，`to_dict()` 将其重新发出。这提供了零开销的前向兼容机制。

#### Validation Behavior

`tools/evidence/types.py` 提供可选的 `validate_evidence_pack(pack: EvidencePack) -> None` 校验函数。

- 调用方可选择在消费前调用，以拒绝无效域值。
- 无效值（如不在已知集合中的 `confidence`、`provenance`、`retrieval_outcome`、`primary_pipeline`）抛出 `ValueError`。
- 当前闭合集合：`confidence` = `high` / `medium` / `low`；`provenance` = `keyword`（legacy payload may contain `semantic` / `hybrid`）；`retrieval_outcome` = `ok` / `weak_results` / `no_confident_match` / `zero_results`；`primary_pipeline` = `none` / `fts`（legacy payload may contain `semantic` / `hybrid`）。
- 未知 `schema_version` 发出 `UserWarning`，**不**抛出异常，以保留前向兼容。
- `extra` 字典中的字段完全绕过校验，不检查、不丢弃、不修改。
- 校验不修改输入对象。

#### Diagnostics（`evidence_pack.diagnostics`）

当 `--include-evidence` 请求 evidence pack 时，`diagnostics` 字段始终存在。纯确定性推导，不调用 LLM、不访问文件系统、不触发额外搜索。

**字段结构：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `retrieval_outcome` | string enum | 检索质量分类（见下表） |
| `outcome_reason` | string | 当前分类的具体原因（见下表） |
| `notes` | string[] | 上下文观察（如置信度分布、截断信息）。为空时省略 |
| `suggestions` | string[] | 改善检索的可操作建议。为空时省略 |
| `pipeline_composition` | object | 参与本次检索的管道组成。见下方 Pipeline Composition 子节 |

**`retrieval_outcome` 枚举值：**

| 值 | 含义 | 触发条件 |
|----|------|----------|
| `ok` | 检索正常，有高或中置信度结果 | 至少一个 item confidence 为 `high` 或 `medium` |
| `weak_results` | 有结果但质量较弱 | 全部 low confidence 且 `no_confident_match` 为 false |
| `no_confident_match` | 搜索核心标记无高置信匹配 | `no_confident_match` 为 true |
| `zero_results` | 无任何检索结果 | `merged_results` 为空 |

**`outcome_reason` 枚举值：**

| 值 | 对应 outcome | 说明 |
|----|-------------|------|
| `confident_results_present` | `ok` | 存在 medium/high 置信度结果 |
| `all_items_low_confidence_full_recall` | `weak_results` | 全部 low，total 不超过 items 数且 `has_more=false`（已全量召回） |
| `low_confidence_with_potential_under_recall` | `weak_results` | 全部 low，且 total > items 数或 `has_more=true`（结果集不完整或可能还有更多未召回） |
| `all_items_low_confidence` | `no_confident_match` | `no_confident_match` flag 且全部 low |
| `search_core_flagged_no_confident` | `no_confident_match` | `no_confident_match` flag 但存在 medium/high |
| `no_matches_found` | `zero_results` | 无关键词 / Entity Graph 匹配结果 |
| `results_truncated_before_delivery` | `zero_results` | total_available > 0 但 items 为空 |

> `outcome_reason` 值为描述性文本，可能在不升级 `schema_version` 的情况下扩展。调用方不应将其视为闭合枚举进行严格校验。

**Legacy semantic diagnostics：**

旧 payload 可能包含 `semantic` / `hybrid` pipeline 字段；当前运行时不再生成 semantic-only 结果。诊断层按关键词 / Entity Graph 结果判定 `ok`、`weak_results`、`no_confident_match` 或 `zero_results`。

**Pipeline Composition（`pipeline_composition`）：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `primary_pipeline` | string enum | `none` / `fts`（legacy payload may contain `semantic` / `hybrid`） |

`primary_pipeline` 的判定规则（从 `merged_results` 的 `source` 字段确定性推导）：

| 值 | 条件 |
|----|------|
| `none` | `merged_results` 为空，或所有 item 的 `source` 均不含 `fts` |
| `fts` | 至少一个 item 的 `source` 含 `fts` |
| `semantic` | Legacy payload only；当前运行时不再生成 |
| `hybrid` | Legacy payload only；当前运行时不再生成 |

**Consumer Guidance（消费指引）：**

| `retrieval_outcome` | Agent 行为 | GUI 行为 |
|---------------------|-----------|----------|
| `ok` | 消费 `filtered_results` / evidence，由宿主 agent 合成 | 正常展示结果 |
| `weak_results` | 向用户说明结果置信度较低，建议调整查询；可参考 `suggestions` | 显示弱结果提示，提供 `suggestions` 给用户 |
| `no_confident_match` | 明确告知用户未找到高置信匹配；参考 `suggestions` 建议换词或加过滤 | 显示"未找到精确匹配"提示 |
| `zero_results` | 如实报告无结果；参考 `suggestions` 建议放宽条件 | 显示空结果页面和 `suggestions` |

> `notes` 是观察性描述，`suggestions` 是可操作建议。两者均为 `string[]`；为空时序列化输出可能省略该字段。

**诊断示例（`weak_results`）：**

```json
{
  "evidence_pack": {
    "diagnostics": {
      "retrieval_outcome": "weak_results",
      "outcome_reason": "all_items_low_confidence_full_recall",
      "notes": [
        "All 3 items have low confidence.",
        "total_available equals item count (full recall, weak quality)."
      ],
      "suggestions": [
        "Query may be too vague or match tangential content.",
        "Try adding time range or entity filters."
      ]
    }
  }
}
```

#### Entity Match Provenance（`evidence_pack.items[].entity_matches`）

当 `entity_hints` 中的实体匹配到某个 evidence item 的文本字段时，该 item 会包含 `entity_matches` 数组。未匹配到任何实体的 item 不包含此字段。

**字段结构：**

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `entity_id` | string | 实体唯一标识 |
| `primary_name` | string | 实体确定性显示名；旧 payload 可能为空字符串 |
| `entity_type` | string | 实体类型（如 `actor`、`place`、`project`、`event`、`artifact`、`concept`） |
| `matched_terms` | array\<string\> | 匹配到的实体术语（已去重）。来源包括 `entity_hints[].matched_term` 和 `entity_hints[].expansion_terms` 中的别名，仅包含在 item 文本中实际出现的术语 |
| `match_sources` | array\<string\> | 匹配来源字段（如 `title`、`snippet`、`metadata`、`abstract`，已排序去重） |
| `query_matched_term` | string | 可选，原始 query 中触发匹配的术语 |

**特性：**
- 纯确定性推导：从已有 `entity_hints`（含 `matched_term` 和 `expansion_terms`）和搜索结果字段（`title`、`snippet`、`abstract`、`metadata`）推导，不调用 LLM、不访问文件系统
- `matched_terms` 仅包含在 item 文本中实际出现的术语（来自 `matched_term` 或 `expansion_terms`），不会包含未出现的候选词
- `query_matched_term` 始终保留原始 `matched_term`，即使 item 中只匹配到了 `expansion_terms` 里的别名
- 当 `entity_matches` 为空数组时，序列化输出中省略此字段
- 旧 payload（无 `entity_matches`）仍可正常反序列化

**匹配语义（S1-C 实测确认）：**

- **大小写不敏感**：实体图谱查找（`resolve_via_runtime`）、确定性查询扩展（`expand_query_with_entity_graph`、`resolve_query_entities`）以及证据实体匹配溯源（`_build_entity_matches`）均使用大小写归一化进行匹配。`life index` 与 `Life Index` 和 `LIFE INDEX` 等效。原始实体名称/别名在输出（`matched_terms`、`primary_name`、`aliases`）中保留原始大小写
- **ASCII 边界匹配**：ASCII 实体名/别名使用大小写不敏感的字母数字边界匹配；短别名不会匹配到无关单词内部。例如 `LI` 不匹配 `life`，`Ali` 不匹配 `Alibaba` / `Align` / `Ali_note`
- **下划线语义**：`_` 被视为 ASCII word character，因此 `my_LI_project` 不匹配 `LI`。这是为了避免代码式标识符、文件名片段或标签中的短别名误报
- **非 ASCII 子串匹配**：中文等非 ASCII 术语保留子串匹配行为；系统当前不引入中文分词边界。调用方应将极短中文别名视为可能产生误报的高风险别名
- **路径隐私**：Evidence Pack 的 `document.path` 是相对文档引用或被省略；消费者不得依赖绝对文件系统路径，系统也不应通过 `evidence_pack.items[].document.path` 暴露本机绝对路径
- **abstract + metadata 双重归因**：`metadata.abstract`（或 `metadata.summary`）的文本同时出现在 `abstract` 和 `metadata` 两个来源字段中，导致 `match_sources` 可能包含 `["abstract", "metadata"]` 双重归因。这是确定性文本扫描的正常结果，不代表独立匹配
- **`metadata` 源聚合**：`metadata` 源字段由 frontmatter 中所有字符串值（含列表元素）拼接而成，覆盖 `location`、`weather`、`people`、`tags` 等全部元数据字段

#### 最佳努力失败行为

Evidence pack 采用**最佳努力（best-effort）**策略：

- 若 evidence 构建失败，搜索本身仍返回 `success: true`
- 返回值**不携带** `evidence_pack` 字段
- `performance` 中记录 `evidence_build_ms` 和 `evidence_error`（错误信息）
- 调用方不应将 `evidence_pack` 缺失等同于搜索失败

<!-- PLATFORM-SSOT:SYNTHESIZE-TRANSITION:START -->
### `--synthesize` transition authority

Current runtime: the product CLI accepts `--synthesize` for at least two major versions and constructs `SmartSearchOrchestrator()` with no injection surface. It emits no `answer` and preserves the ordinary deterministic domain payload.

Current warning: exactly one stderr line is emitted: `DEPRECATED: --synthesize is a compatibility no-op; synthesis belongs to the Host Agent + Life Index Skill.`

A3/A4 implementation: search/smart-search production packages contain no dormant/injectable LLM rewrite, filter, provider, prompt, trust-gate, or synthesis implementation. The Tier 1 no-LLM hard check enforces the documented static structural policy over these production roots. A5 extends the deterministic-only boundary and structural scan to product eval; #163 remains open pending review, so D1-A is not complete.

Intelligence owner: Host Agent + Skill remain responsible for planning, multi-hop reasoning, orchestration, interpretation, and synthesis.
<!-- PLATFORM-SSOT:SYNTHESIZE-TRANSITION:END -->

### `--synthesize` current compatibility behavior

The named transition block above is the sole authority for current versus target
status. The product CLI has no provider/client injection path and does not emit
`answer`, including when `--synthesize` is present. The flag emits the stable
warning above and then uses the same deterministic execution path. Only timing
metadata may vary between separate invocations; the domain payload is equivalent.

#### 组合标志语义

| 标志组合 | 行为 |
|----------|------|
| （无标志） | 确定性结果；不进行工具内 LLM rewrite/filter/summary |
| `--include-evidence` | 添加 evidence_pack |
| `--synthesize` | 当前接受至少两个主版本；stderr 发出一次稳定弃用警告；不注入 LLM、不添加 `answer`，domain payload 与普通调用等价 |
| `--include-evidence --synthesize` | 添加 evidence_pack；stderr 发出一次稳定弃用警告；`--synthesize` 不改变 JSON/domain 输出 |

### Aggregate Delegation（自动聚合路由）

当 smart-search 检测到明确的聚合/计数/趋势意图时，会自动委派给确定性 `aggregate` 原语计算，而非通过 LLM 自由计数。路由为纯确定性模式匹配（无 LLM），发生在正常检索管线之前。

**触发条件（确定性，无 LLM）**：

| 查询模式 | 路由参数 | 示例 |
|----------|----------|------|
| "过去N天" + 聚合信号 + "晚睡/late sleep" | `unit=day`, `predicate=entry_time_after=22:00` | "过去60天我有多少天晚睡" |
| "过去N天" + 聚合信号 + "多少篇/条日志/日记/记录" | `unit=entry`, `predicate=journal_count` | "过去90天有多少篇日志" |
| "过去N天" + 聚合信号 + "多少天写日志/有记录" | `unit=day`, `predicate=journal_count` | "过去90天有多少天写日志" |
| "past/last N days" + "how many/count" + "journal entries/logs" | `unit=entry`, `predicate=journal_count` | "past 30 days how many journal entries" |
| "今年" + "写日志" + 聚合/趋势信号 | `unit=month`, `predicate=journal_count` | "统计一下我今年写日志的频率趋势" |
| "过去N天" + 聚合信号 + 引号词 + "提到/mention" | `unit=entry`, `predicate=term_presence=TERM` | `过去60天有多少次提到"OpenClaw"` |
| "过去N天" + 聚合信号 + 引号词 + "多少天提到" | `unit=day`, `predicate=term_presence=TERM` | `过去60天有多少天提到"OpenClaw"` |
| "past/last N days" + "how many" + 引号词 + "mention" | `unit=entry`, `predicate=term_presence=TERM` | `past 60 days how many entries mention "OpenClaw"` |
| "past/last N days" + "how many days" + 引号词 + "mention" | `unit=day`, `predicate=term_presence=TERM` | `past 60 days how many days mention "OpenClaw"` |
| "今年/this year" + 聚合信号 + 引号词 + "提到/mention" | `unit=entry`, `predicate=term_presence=TERM` | `今年有多少次提到"OpenClaw"` |
| "过去N天" + 聚合信号 + `field=value` or `field:value` | `unit=entry`, `predicate=field_equals=FIELD:VALUE` | "过去60天有多少篇 topic=work 的日志" |
| "过去N天" + 聚合信号 + "多少天" + `field=value` or `field:value` | `unit=day`, `predicate=field_equals=FIELD:VALUE` | "过去60天有多少天 topic=work 的日记" |
| "今年/this year" + 聚合信号 + `field=value` or `field:value` | `unit=entry`, `predicate=field_equals=FIELD:VALUE` | "今年有多少篇 topic=health 的日志" |
| "past/last N days" + "how many/count" + `field=value` or `field:value` | `unit=entry`, `predicate=field_equals=FIELD:VALUE` | "past 30 days count journal entries where topic=work" |
| "past/last N days" + "how many days" + `field=value` or `field:value` | `unit=day`, `predicate=field_equals=FIELD:VALUE` | "past 30 days how many days topic=health journal" |

**委派行为**：

- 使用 `LIFE_INDEX_TIME_ANCHOR=YYYY-MM-DD` 环境变量（若存在）确定时间锚点；否则使用 `date.today()`
- 路由成功时，`aggregate` 为唯一计算器（`tools.aggregate.core.run_aggregate`），不经过 LLM rewrite/filter/synthesis 管线
- 正常检索字段（`filtered_results`、`summary` 等）保留但为空值
- `agent_unavailable` 在当前产品 CLI 中为 `true`；它不是 aggregate 路由是否执行的标志

**`field_equals` 自动路由限制**：

- 仅支持显式 `field=value` 或 `field:value` 语法（field 必须匹配 `[A-Za-z_][A-Za-z0-9_]*`）；不支持模糊自然语言字段提取
- value 可选地用单引号、双引号或弯引号包围，路由会自动去除引号；未加引号的 value 在第一个空白处结束，加引号的 value 可包含空格
- 不含时间范围（"过去N天" 或 "今年/this year"）的查询不触发 `field_equals` 路由
- 不含聚合信号（"多少"/"count"/"how many" 等）的查询不触发路由
- 单位（`entry` vs `day`）由 "篇/条/个" vs "天" 或英文 "entries" vs "days" 决定

#### `aggregate_result` 输出字段

仅在 smart-search 委派到 `aggregate` 时出现。结构与 `aggregate` 命令输出一致（见 aggregate 章节）。关键字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `aggregate_result.command` | string | 固定为 `"aggregate"` |
| `aggregate_result.range` | object | 解析后的日期范围 `{"since", "until"}` |
| `aggregate_result.predicate.type` | string | 谓词类型，如 `entry_time_after`、`journal_count` |
| `aggregate_result.result.count` | int | 计算结果计数 |
| `aggregate_result.result.exactness` | enum | `exact` / `approximate` / `partial` / `not_measurable` |
| `aggregate_result.limitations` | array | 局限性说明（如"日志写入时间不等于实际入睡时间"） |
| `aggregate_result.claim_envelope` | object | 证据化结论外壳；结构同 aggregate 命令 |
| `aggregate_result.evidence_pack` | object | aggregate 专用证据包；结构同 aggregate 命令 |

**示例**：

```json
{
  "success": true,
  "query": "过去60天我有多少天晚睡",
  "rewritten_query": "过去60天我有多少天晚睡",
  "filtered_results": [],
  "summary": "",
  "citations": [],
  "agent_decisions": [],
  "agent_unavailable": true,
  "aggregate_result": {
    "success": true,
    "command": "aggregate",
    "predicate": {"type": "entry_time_after", "threshold": "22:00", "definition": "..."},
    "range": {"since": "2026-03-15", "until": "2026-05-13"},
    "result": {
      "count": 7,
      "denominator": 60,
      "exactness": "partial",
      "confidence": "high",
      "min_count": 7,
      "max_count": 11,
      "unknown_count": 4,
      "unknown_bucket_count": 4,
      "count_semantics": "partial_lower_bound"
    },
    "limitations": ["No reliable time-of-day field was available for one or more journal entries."]
  },
  "performance": {"total_time_ms": 45.2}
}
```

**field_equals 路由示例**：

```json
{
  "success": true,
  "query": "过去60天有多少篇 topic=work 的日志",
  "rewritten_query": "过去60天有多少篇 topic=work 的日志",
  "filtered_results": [],
  "summary": "",
  "citations": [],
  "agent_decisions": [],
  "agent_unavailable": true,
  "aggregate_result": {
    "success": true,
    "command": "aggregate",
    "predicate": {"type": "field_equals", "field": "topic", "value": "work"},
    "range": {"since": "2026-03-17", "until": "2026-05-15"},
    "result": {
      "count": 12,
      "denominator": 60,
      "exactness": "exact",
      "confidence": "high"
    },
    "limitations": []
  },
  "performance": {"total_time_ms": 38.1}
}
```

**Consumer Guidance**：

- 非聚合查询不包含 `aggregate_result` 字段
- `aggregate_result` 为附加字段（additive），不影响现有字段语义
- `aggregate_result.claim_envelope` 和 `aggregate_result.evidence_pack` 位于 `aggregate_result` 内，不新增 smart-search 顶层字段
- `agent_unavailable` 在当前产品 CLI 中为 `true`；aggregate 路由本身不调用 LLM

### Aggregate Evaluation Coverage (Internal Developer Tooling)

`life-index eval` may consume operator-supplied evaluation data stored outside
public artifacts. Public source releases ship the deterministic harness, not
private corpus facts. When no local query set is present, data-dependent eval
runs return an explicit skipped state instead of inventing placeholder results.
Operator data may also contain companion sections for deterministic
aggregate/analyze checks:

- `aggregate_queries` exercises the aggregate primitive directly.
- `smart_aggregate_queries` exercises smart-search deterministic aggregate
  routing before normal retrieval.

The smart-aggregate companion set is a route-family coverage matrix, not a
product scenario registry. Each operator-supplied case must prove that a query
maps to an already documented generic deterministic primitive such as
`journal_count`, `entry_time_after`, `term_presence`, or `field_equals`. Public
authority does not pin private query text, IDs, thresholds, expected counts, or
corpus observations.

These cases do not participate in search MRR/Recall/Precision calculations;
they are reported under `aggregate_eval` and `smart_aggregate_eval` so
aggregate regressions and smart-search route regressions are visible without
polluting retrieval metrics.

`aggregate_eval` exposes numeric `total_queries`, `passed_queries`, and
`failed_queries`; a `metrics` object; category summaries; `per_query` records;
and `failures`. Per-query records carry an operator-supplied ID plus
`eval_mode`, `command`, `count`, `exactness`, and `pass`. Public documentation
defines field semantics but deliberately supplies no private case ID, expected
count, pass rate, title, query, or threshold.

`smart_aggregate_eval` uses the same high-level shape, with per-query entries
adding `eval_mode: "smart_aggregate"`, `route_present`, and predicate-detail
fields such as `predicate_term` or `predicate_threshold` when applicable. It
validates that a natural-language smart-search query produced a top-level
`aggregate_result` with the expected deterministic aggregate contract:

The same aggregate fields are present for smart-aggregate diagnostics.
Per-query records add `eval_mode`, `route_present`, predicate-detail fields,
`unit`, and exactness/pass facts. Private IDs, predicate values, thresholds,
expected counts, and measured pass rates remain outside public artifacts.

#### Diagnostic-Only Mode

When `run_evaluation()` is called without an explicit `data_dir` (default/live
eval against real user data), aggregate companion checks and smart aggregate
route companion checks run in **diagnostic-only** mode. In this mode:

- `diagnostic_only` is set to `true`.
- `failed_queries` is always `0` — count mismatches do not fail the gate.
- `failures` is an empty list.
- Mismatches are reported as `diagnostic_observations` with `id`, `query`,
  `reason`, `expected`, and `actual` fields.

When `data_dir` is explicitly provided for a synthetic or private evaluation,
aggregate and smart aggregate route checks retain deterministic mismatch
accounting, including `failed_queries`, but the evaluation remains advisory and
does not decide CI or merge success. Blocking authority belongs only to the
separately executed public synthetic deterministic contracts and Core sentinel.

This is an eval-system extension, not a second Gold Set. Real-log diagnostic
queries should be promoted into `aggregate_queries` or `smart_aggregate_queries`
only after their expected counts, route criteria, and evidence criteria are
stable.

### Answer Evaluation Harness（Internal Developer Tooling，非 CLI Public API）

> **注意**: `tools/eval/answer_eval.py` 是**内部开发者/评估工具**，不属于 CLI 公共 API。以下文档仅供开发者和评估流水线参考。GUI 或 Agent 消费者不应导入或依赖此模块。

`tools/eval/answer_eval.py` 提供确定性 answer 级别评估工具。不依赖网络或 LLM 凭证，对 orchestrator 输出做离线质量分类。

#### 评估维度

| 维度 | 说明 | Verdict 值 |
|------|------|------------|
| 支撑度 | Answer 有有效引用且无不实声称 | `supported` |
| 过度声称 | 含 "all entries" 等全称断言但引用不足 | `overclaiming` |
| 无效引用 | 所有引用均为幻觉路径或绝对路径 | `invalid_citation` |
| 无引用 | Citations 列表为空 | `no_citations` |
| 空答案 | Answer text 为空 | `empty` |

#### 透明度质量

| 质量等级 | 说明 |
|----------|------|
| `complete` | `confidence_reason` + `limitations`(list) + `evidence_summary` 均存在 |
| `partial` | 部分字段缺失或 `limitations` 不是 list |
| `missing` | 三个透明度字段均缺失 |
| `not_applicable` | 答案为空，不适用透明度评估 |

#### API

**单条评估：**

```python
from tools.eval.answer_eval import evaluate_answer, evaluate_answer_from_orchestrator_output

# 直接评估 answer dict
result = evaluate_answer(answer_dict, known_paths={"Journals/..."})
print(result.verdict, result.valid_citation_count, result.transparency.verdict)

# 从完整 orchestrator 输出评估（自动提取 known_paths）
result = evaluate_answer_from_orchestrator_output(orchestrator_output_dict)
```

**批量评估：**

```python
from tools.eval.answer_eval import evaluate_answer_batch

batch = evaluate_answer_batch([
    {"answer": answer_dict_1, "known_paths": paths_1},
    {"answer": answer_dict_2, "known_paths": paths_2},
])
print(batch.by_verdict)  # {"supported": 1, "invalid_citation": 1}
```

#### 引用失败模式契约

| 失败模式 | 原因 | `reason` 字段 |
|----------|------|---------------|
| 绝对路径 | 引用包含完整文件系统路径 | `absolute_path` |
| 幻觉路径 | 引用路径不在 `known_paths` 中 | `unknown_path` |
| 类型错误 | 引用不是 string | `not_a_string` |
| 越界索引 | 数字引用不属于本 answer-eval 的 string path contract | `not_a_string` |

---

## eval

> **Internal developer evaluation tooling.** `eval` reports advisory search
> quality observations against a local/private query set when one is configured. Public source
> releases ship the harness but not the eval data. It is not a user search
> endpoint and must not be used to write or mutate journal data.
>
> **M04 注**：以下文档描述内部开发者 eval 测量子系统的实现行为，不是公开的
> CLI/API 扩展。没有新增公共 CLI flag（如 `--export-ir` 或 `--export-trec`）。

### 端点

```bash
life-index eval [options]
python -m tools eval [options]
```

### 参数

| 名称 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| data-dir | path | temp fixture data | 使用指定数据目录运行 eval |
| save-baseline | path | - | 保存当前 eval 结果为 baseline JSON |
| compare-baseline | path | - | 与既有 baseline JSON 对比 |
| json | flag | false | 输出完整 JSON |
| semantic | flag | false | Deprecated compatibility no-op；eval 仍运行 keyword gate |
| no-semantic | flag | false | Deprecated compatibility no-op；eval 仍运行 keyword gate |
| semantic-report | flag | false | Deprecated compatibility no-op；返回禁用/无运行诊断，不执行第二次向量 pass |
| judge | enum | keyword | `keyword` 运行确定性评估；`llm` 作为兼容输入保留，但立即返回非成功结果 |
| live | flag | false | 使用真实 `~/Documents/Life-Index` 数据运行诊断 |
| no-overlay | flag | false | 禁用本地私有 eval overlay |
| overlay-path | path | - | 指定私有 eval overlay YAML |

### 本地 / 私有 Eval 数据

公开源码只包含 deterministic eval harness。私有查询、标题、路径、计数、指标、
阈值与 corpus facts 均由 operator 在公开制品之外提供和保存。缺失时，数据依赖
eval 返回显式 skipped 状态；存在时，其结果仍为 advisory，不能替代公开合成 Core
assertion，也不能覆盖 exact Core result。

### LLM 边界

- `judge=keyword` 是唯一执行路径；它不初始化 provider client、不读取 LLM key、不调用外部 LLM。
- `--judge llm` 为本版本保留的兼容输入。它在评估、配置读取或 provider 模块加载前立即返回退出码 `2` 和稳定错误 `EVAL_LLM_JUDGE_HOST_AGENT_REQUIRED`；不会静默退回 keyword，也不会声称已执行。
- 语言辅助评估属于 Host Agent + Life Index Skill，不属于产品 CLI。
- `--semantic` / `--semantic-report` 仅为兼容 no-op，不等同于 LLM judge，也不加载 embedding 模型。

<!-- PLATFORM-SSOT:EVAL-LLM-TRANSITION:START -->
### `eval --judge llm` compatibility boundary

`life-index eval --judge llm` remains recognizable for compatibility, but it
fails before evaluation or any provider/configuration import. The stable
non-success payload is:

```json
{
  "success": false,
  "error": {
    "code": "EVAL_LLM_JUDGE_HOST_AGENT_REQUIRED",
    "message": "Language-assisted evaluation belongs to the Host Agent + Life Index Skill."
  }
}
```

There is no fallback to keyword and no provider/model recommendation. The A5
candidate removes product eval provider selection, prompts, clients, and calls
while preserving deterministic C7 metrics. #163 remains open pending review;
this runtime fact does not close the Issue or complete D1-A.
<!-- PLATFORM-SSOT:EVAL-LLM-TRANSITION:END -->

### 返回值

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "eval",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "summary_lines": ["Deterministic evaluation completed"],
    "metrics": {},
    "judge_mode": "keyword",
    "semantic_enabled": false,
    "aggregate_eval": {},
    "smart_aggregate_eval": {}
  }
}
```

### 内部测量输出（M04 实现）

`run_evaluation()` 在 JSON 结果中附加以下内部开发者测量字段。这些字段由
`tools/eval/run_eval.py` 生成，供 baseline 保存、回归比较和 CI 门控使用。

#### `ir_eval` — IR 测量制品

`ir_eval` 是 Pack A 引入的纯增量内部测量节，基于现有的 `tools/eval/eval_qrels.py`、
`eval_run.py`、`eval_export.py` 等无依赖 helper 构建。

| 字段 | 类型 | 说明 |
|------|------|------|
| `ir_eval.qrel_coverage` | object | Qrel 覆盖分类报告，见下表 |
| `ir_eval.run_coverage` | object | Run 覆盖统计报告，见下表 |
| `ir_eval.artifacts.qrels` | dict | query ID → doc ID → int grade 的 qrels 字典 |
| `ir_eval.artifacts.run` | dict | query ID → doc ID → float score 的 run 字典 |

**隐私约束**：`artifacts.qrels` 和 `artifacts.run` 仅包含 query ID 和 doc ID；
不序列化原始 query 文本、日志标题或正文内容。该约束由
`tests/unit/test_eval_runner.py::test_eval_runner_includes_ir_eval_artifacts` 校验。

**`qrel_coverage` 字段**：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `total_queries` | int | 总查询数 |
| `resolved` | int | 已解析到至少一个 doc ID 的查询数 |
| `ambiguous` | int | 存在多个可能 doc 匹配的查询数 |
| `unresolved` | int | 无法解析到 doc ID 的查询数 |
| `negative` | int | 负例查询数（预期无匹配结果） |
| `min_results_only` | int | 仅含 `min_results` 期望、无 title 期望的查询数 |
| `broad_eval` | int | 使用 broad_eval 谓词评估的查询数 |
| `broad_eval_with_titles` | int | 同时使用 broad_eval 和 must_contain_title 的查询数 |
| `unresolved_ids` | list[str] | 未解析查询 ID 列表 |
| `ambiguous_ids` | list[str] | 歧义查询 ID 列表 |
| `procedural_only_ids` | list[str] | 纯过程性查询 ID 列表 |
| `warnings` | list[str] | 构建过程中的警告信息 |

**`run_coverage` 字段**：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `total_queries` | int | 总查询数 |
| `total_result_items` | int | 结果项总数 |
| `emitted_items` | int | 实际写入 run 的项数 |
| `skipped_empty_doc_ids` | int | 因 doc ID 为空而被跳过的项数 |
| `length_mismatch_query_ids` | list[str] | 结果长度与期望长度不匹配的查询 ID |
| `duplicate_doc_ids_query_ids` | list[str] | 存在重复 doc ID 的查询 ID |
| `queries_with_no_run_items` | list[str] | 没有任何 run 项的查询 ID |
| `warnings` | list[str] | 构建过程中的警告信息 |

#### Baseline 规范化策略（M04 Pack B）

Baseline 查找遵循确定性 local/private 路径偏好：

1. **Canonical 目录**：优先使用配置的私有 eval 目录中的 `baselines/`。
2. **Fallback 目录**：仅当调用方显式传入 fallback 目录时才使用。
3. **确定性排序**：在同一目录内，按 embedded `frozen_at` 或 `anchor_date` 降序、
   文件名降序排序；mtime 仅作为最终 tie-breaker。

`save-baseline` 写入时开发者自行指定路径；`compare-baseline` 读取调用方显式传入的
baseline 路径。`_find_latest_baseline()` 使用上述策略为未设置
`LIFE_INDEX_TIME_ANCHOR` 的 eval run 推断稳定时间锚点。

#### `compare_against_baseline()` diff 增量（M04 Pack C）

当使用 `compare-baseline` 时，`diff` 对象在保留原有字段（`metric_deltas`、
`regressions`、`new_failures`、`new_passes`、`recall_gap_changes`）的基础上，
新增以下内部比较节：

| 字段 | 类型 | 说明 |
|------|------|------|
| `diff.eval_comparison` | object | 基于 `EvalRun` 的 typed pass/fail 比较结果 |
| `diff.ir_run_comparison` | object | 基于 qrels/run 的 IR 指标比较结果 |
| `diff.companion_eval_deltas` | list[object] | aggregate / smart-aggregate / timeline 的 companion 比较增量 |

**`eval_comparison` 字段**：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `baseline_commit` | str | baseline 的 git commit |
| `candidate_commit` | str | current 的 git commit |
| `baseline_anchor` | str | baseline 的锚定日期 |
| `candidate_anchor` | str | current 的锚定日期 |
| `total_shared_queries` | int | 两边共有的查询数 |
| `fixed_query_ids` | list[str] | 从失败变为修复的查询 ID |
| `regressed_query_ids` | list[str] | 从通过变为失败的查询 ID |
| `still_failing_ids` | list[str] | 两边均失败的查询 ID |
| `still_passing_ids` | list[str] | 两边均通过的查询 ID |
| `new_in_candidate` | list[str] | current 新增而 baseline 没有的查询 ID |
| `missing_from_candidate` | list[str] | baseline 有而 current 缺失的查询 ID |
| `failure_delta` | int | current 相对 baseline 的失败数变化（负值表示改善） |

**`ir_run_comparison` 字段**：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `metric_deltas` | list[object] | 每项含 `metric_name`、`baseline_value`、`candidate_value`、`delta`、`direction` |
| `per_query_deltas` | list[object] | 每项含 `query_id`、`status`，以及可选 `baseline_score`、`candidate_score`、`delta`、`metric_deltas` |
| `queries_compared` | int | 实际参与比较的查询数 |
| `queries_skipped_no_qrel` | int | 因缺少 qrel 而跳过的查询数 |

> **降级行为**：当 baseline 为 legacy 格式（不含 `ir_eval` 节）时，
> `ir_run_comparison` 不会崩溃，而是显式报告 `queries_skipped_no_qrel` 并继续。

**`companion_eval_deltas` 字段**：

`companion_eval_deltas` 是一个列表，每项对应一个 companion eval 节
（`aggregate_eval`、`smart_aggregate_eval`、`timeline_eval`），结构如下：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `section` | str | 节名称 |
| `baseline_mode` | str \| null | baseline 的评估模式：`hard_gate` / `diagnostic` / `null` |
| `current_mode` | str \| null | current 的评估模式 |
| `passed_delta` | int | current 通过数 − baseline 通过数 |
| `failed_delta` | int | current 失败数 − baseline 失败数 |
| `pass_rate_delta` | float | current 通过率 − baseline 通过率 |
| `comparable` | bool | 两节是否可比较 |
| `reason` | str | 不可比较时的原因说明 |

> **隔离原则**：companion eval deltas 始终与搜索 MRR/Recall/P 指标分离，
> 不会合并到 `metric_deltas` 中。诊断模式与硬 gate 模式之间的结构差异会降级为
> 显式警告，不会导致崩溃。

## entity-graph-eval

> **Graph ablation evaluation (gbrain Phase A).** Runs search across effective
> Entity Graph on/off combinations with legacy semantic/hybrid slots retained as
> no-op compatibility fields. Default path is fully deterministic —
> zero LLM calls. Output schema version: `gbrain-ablation.v1`.

### 端点

```bash
life-index entity-graph-eval --queries <fixture.json> [--output stdout|<path>] [--data-dir <dir>]
python -m tools.eval.ablation --queries <fixture.json> [--output stdout|<path>] [--data-dir <dir>]
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| queries | path | (required) | JSON fixture path with ablation queries |
| output | string | `stdout` | `stdout` or a file path for JSON output |
| data-dir | path | — | Override data directory (sets `LIFE_INDEX_DATA_DIR`) |

### 返回值

```json
{
  "success": true,
  "schema_version": "gbrain-ablation.v1",
  "query_count": 25,
  "combinations": [
    {
      "entity_graph": false,
      "semantic": false,
      "hybrid": false,
      "precision_at_5": 0.12,
      "recall_at_5": 0.08,
      "mrr_at_5": 0.15,
      "query_count": 25
    }
  ]
}
```

**Output contains 4 effective entries** — one for each Entity Graph on/off
combination and legacy semantic/hybrid compatibility slots:

| Flag | Values | Effect |
|------|--------|--------|
| `entity_graph` | true/false | Entity Graph alias expansion on/off |
| `semantic` | true/false | Deprecated no-op; retained for historical comparison shape |
| `hybrid` | true/false | Deprecated no-op; retained for historical comparison shape |

### LLM 边界

- Default path: **zero LLM calls**. All search uses FTS keyword + deterministic ranking.
- `semantic=true` combinations are deprecated no-ops. They do not use `sentence-transformers`, do not download models, and make no API call.
- No `anthropic`, `openai`, or `llm_client` imports in the module.

### Fixture format

The queries fixture is a JSON array of objects:

```json
[
  {
    "id": "AQ01",
    "query": "search terms",
    "category": "entity_expansion",
    "expected_relevant_ids": ["life-index_2026-03-04_002.md"]
  }
]
```

---

## upgrade

### Endpoint

```bash
life-index upgrade --plan --json
life-index upgrade --apply --json
python -m tools upgrade --plan --json
python -m tools upgrade --apply --json
```

### Purpose

`upgrade` is a deterministic, read-only host-agent operations primitive. It
diagnoses whether the installed Life Index program is current or requires clean
replacement. It does not install, uninstall, fetch, pull, repair, deliver a
skill, modify an environment, touch user journals, or replace the developer
release workflow.

`--plan` reports installed package and bootstrap manifest versions, PyPI
release/yank status, optional checkout freshness plus a read-only remote probe,
health JSON parseability, sync-skill discovery status, `actions[]`, and
`recommended_next_step`.

The health and skill-discovery probes run from a neutral temporary working directory
with a synthetic data directory and cleared `PYTHONPATH`. They never inspect the
configured user-data root merely to decide whether the program needs replacement.
If isolated health reports version truth that disagrees with the upgrade process,
the plan fails closed with `reinstall_managed_environment` instead of reporting a
contradictory current/no-op result.

`--apply` builds the same read-only plan. It never runs executable in-place
`git pull`, `git fetch`, `pip install --upgrade`, `pip install -e`, or
`sync-skill --install` operations.

### Replacement behavior

A known update or program inconsistency produces one human-required action:

```json
{
  "id": "reinstall_managed_environment",
  "description": "Leave the existing environment and checkout untouched; create a fresh dedicated install.",
  "side_effect": "write",
  "command": null,
  "reason": "Follow AGENT_ONBOARDING.md.",
  "safe_to_run": false,
  "requires_human": true
}
```

The host agent must follow `AGENT_ONBOARDING.md`, create a fresh dedicated
install, and leave shared/global Python environments plus existing developer-
or user-owned checkouts untouched. User data remains separate and must never be
deleted, moved, or overwritten.

Healthy/current apply returns a truthful successful no-op. Dirty, ahead,
diverged, unreachable, unknown, or otherwise human-risk states retain
fail-closed diagnostics and never authorize mutation.

### JSON contract

```json
{
  "success": false,
  "schema_version": "m36.upgrade.v0",
  "command": "upgrade",
  "mode": "apply",
  "error": {
    "code": "UPGRADE_REINSTALL_REQUIRED",
    "message": "The program environment must be replaced through the canonical onboarding path."
  },
  "data": {
    "installed": {
      "package_version": "1.5.1",
      "bootstrap_manifest_repo_version": "1.5.1",
      "install_type": "package|editable|unknown",
      "repo_path": null
    },
    "pypi": {
      "status": "ok|partial",
      "error": null,
      "latest_non_yanked": "1.5.2",
      "recommended_version": "1.5.2",
      "current_version_yanked": false,
      "current_yanked_reason": null
    },
    "git": null,
    "health": {},
    "sync_skill": {},
    "onboarding": "AGENT_ONBOARDING.md",
    "actions": [],
    "recommended_next_step": {},
    "partial": false,
    "reinstall_required": true,
    "applied_actions": []
  }
}
```

Every `actions[]` item contains:

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable action id |
| `description` | string | Human-readable action summary |
| `side_effect` | string | `"read"` or `"write"` |
| `command` | string \| null | Displayable read command, or `null` when human replacement is required |
| `reason` | string | Why the action exists |
| `safe_to_run` | bool | Whether an automatic operation is allowed |
| `requires_human` | bool | Whether the host agent must stop and involve the user |

### Exit and error behavior

- Plan normally exits 0 with `success: true`, including partial advisory
  metadata.
- Reinstall-required apply exits 1 with
  `error.code = "UPGRADE_REINSTALL_REQUIRED"`,
  `data.reinstall_required = true`, and `data.applied_actions = []`.
- Healthy/current apply exits 0 with `success: true`,
  `data.reinstall_required = false`, and `data.applied_actions = []`.
- Existing human-risk states remain fail-closed. Common codes include
  `UPGRADE_DIRTY_WORKTREE`, `UPGRADE_GIT_REQUIRES_HUMAN`, and
  `UPGRADE_REQUIRES_HUMAN`.

### Freshness rules

Version equality is not sufficient for editable/source diagnostics. A checkout
behind its tracking ref, or a read-only remote probe that sees newer commits,
requires clean replacement. Dirty, ahead, and diverged states require human
review. Remote probe failure marks the report partial and freshness unknown.

PyPI metadata is advisory and non-fatal. Yanked releases are never recommended
as targets. Network failure does not authorize a write.

### schema_version Policy

`upgrade` retains top-level `schema_version = "m36.upgrade.v0"`. The
`reinstall_managed_environment.command` value is `null` and validates under
the current v0 output contract. Top-level envelope fields remain unchanged.
---

## bootstrap

### 端点

```bash
life-index bootstrap --json
python -m tools bootstrap --json
```

### 语义

`bootstrap` 是只读安装 / 数据状态检测命令，用于 Agent onboarding 前置判断。它不 clone、不 install、不 migrate、不 repair、不写入用户数据、不修改 `.venv`，也不删除任何 checkout。

`bootstrap` 会以有界、非致命、只读方式查询最新发布版本。网络不可用、超时或设置 `LIFE_INDEX_NO_NET=1` 时，`freshness` 返回 `"unknown"` 并继续使用本地检测。`install_in_sync` 仍只表示本机安装包版本是否与当前 checkout manifest 版本一致。

`journal_count` 使用共享 canonical journal-file 计数口径，只统计文件名匹配 `life-index_YYYY-MM-DD_NNN.md` 的日志文件；standard `health` 与 `migrate --dry-run` 使用同一口径。

### 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--json` | yes | 输出 JSON contract |
| `--data-dir <path>` | no | 覆盖 Life Index 数据目录；仅影响本次检测 |
| `--checkout-path <path>` | no | 要评估的本地 checkout 路径 |
| `--checkout-origin discovered\|host_managed\|user_designated` | no | `--checkout-path` 的来源；默认 `discovered` |

### checkout origin 规则

`safe_to_adopt: true` 只会在以下条件同时满足时出现：

1. checkout 含 `SKILL.md`、`pyproject.toml`、`bootstrap-manifest.json`;
2. 未发现强 development-directory 信号；
3. `--checkout-origin` 是 `host_managed` 或 `user_designated`。

随机发现的 checkout 即使结构完整，也返回 `verdict: "ambiguous"`，并通过 `needs_human` 要求 Agent 让用户或 host platform 明确安装目标。

### 返回值

```json
{
  "success": true,
  "schema_version": "m34.bootstrap.v0",
  "command": "bootstrap",
  "detected_state": {
    "has_user_data": true,
    "journal_count": 12,
    "data_dir": "<data-dir>",
    "installed_version": "1.3.0",
    "manifest_version": "1.3.0",
    "install_in_sync": true,
    "install_type": "editable",
    "freshness": "current",
    "latest_release": "1.3.0",
    "update_available": null,
    "update_reasons": [],
    "freshness_error": null,
    "suggested_refresh_step": null,
    "git_freshness": "current",
    "git_upstream": "origin/main",
    "git_behind_count": 0,
    "git_ahead_count": 0,
    "git_error": null,
    "migration_needed": 0,
    "migration_check_error": null,
    "checkout_assessment": null
  },
  "route": "upgrade",
  "route_reason": "Existing journal data detected in <data-dir>",
  "execution_policy": {
    "needs_human": "relay_items_and_stop",
    "safe_next_steps": "run_in_order_without_additions",
    "uncertain_or_failed_step": "stop_and_report_exact_output",
    "data_safety": "never_delete_or_overwrite_user_data",
    "default_recovery": "refresh_or_reinstall_code_only_then_rerun_bootstrap"
  },
  "needs_human": [],
  "safe_next_steps": [
    "life-index migrate --dry-run",
    "life-index index --rebuild",
    "life-index index-tree materialize --json",
    "life-index generate-index --all-months",
    "life-index sync-skill",
    "life-index health"
  ]
}
```

If `update_available` is set or `install_in_sync` is `false`, both
`suggested_refresh_step` and the first inserted `safe_next_steps` item are the
read-only canonical pointer `life-index upgrade --plan --json`, regardless of
whether `install_type` is `editable` or `package`. The returned upgrade plan
then points replacement cases to `AGENT_ONBOARDING.md`; bootstrap never exposes
an executable git, pip, or skill-install refresh command.

For editable/git checkouts, bootstrap uses local read commands plus
`git ls-remote` and never fetches or updates refs. It reports `git_freshness`,
`git_upstream`, `git_behind_count`, and `git_ahead_count`. Exact ahead/behind
counts are reported only when the remote tip matches the local tracking ref.
If they differ, freshness is `"unknown"`, counts are `null`, and `git_error`
routes the caller to `life-index upgrade --plan --json` rather than claiming a
stale tracking ref is current.

If release freshness cannot be checked, `freshness` is `"unknown"` and
`freshness_error` explains why. This is diagnostic only; bootstrap remains
read-only.

### route 值

| route | 说明 |
|---|---|
| `fresh_install` | 未发现既有 journal 数据 |
| `upgrade` | 已发现既有 journal 数据 |

### needs_human codes

| code | 说明 |
|---|---|
| `AMBIGUOUS_CHECKOUT` | checkout 结构完整但缺少 host/user 正向采纳授权 |
| `DEV_DIR_FOUND` | checkout 有 development-directory 强信号 |
| `INVALID_CHECKOUT` | checkout 缺少必要文件；保持原路径不动，在新空目标创建 dedicated install，后续 cleanup 须按 onboarding 证明 ownership |
| `INSTALL_REFRESH_UNKNOWN` | 需要刷新安装但 bootstrap 无法识别安装类型；Agent 应停止并转达 |
| `MIGRATION_CHECK_FAILED` | in-process migration scan 失败；不得当作无需迁移 |

---

## maintenance

> **Maintenance cycle (gbrain Phase D).** Dry-run/report-only maintenance command that
> aggregates six health checks without any production writes. All external CLI calls
> are delegated via subprocess. Default path is fully deterministic — zero LLM calls.
> Output schema version: `m16.maintenance.v0`.
>
> **Data Doctor maintenance contract.** The `maintenance audit|plan|repair|proposal`
> family adds stable `m33.maintenance_*.v0` JSON envelopes for user-data
> maintenance. It coexists with the legacy `m16.maintenance.v0` dry-run cycle.
> Audit, plan, repair dry-run, and proposal validation are read-only. Repair
> apply is limited to low-risk rebuildable artifacts and explicitly confirmed
> safe archive moves.

### 端点

```bash
life-index maintenance --dry-run [--output text|json] [--data-dir <dir>]
python -m tools maintenance --dry-run [--output text|json] [--data-dir <dir>]

life-index maintenance audit --json [--domain <domains>] [--data-dir <dir>]
life-index maintenance plan --issue-id <id> --json [--data-dir <dir>]
life-index maintenance repair --issue-id <id> --dry-run --json [--data-dir <dir>]
life-index maintenance repair --issue-id <id> --apply --json [--data-dir <dir>]
life-index maintenance proposal validate --file proposal.json --json [--data-dir <dir>]
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| dry-run | flag | (default) | Run maintenance in dry-run/report-only mode |
| output | enum | `text` | Output format: `text` (human-readable) or `json` |
| data-dir | path | — | Override data directory (sets `LIFE_INDEX_DATA_DIR`) |
| json | flag | — | Emit JSON for `audit`, `plan`, `repair`, or `proposal validate` |
| domain | CSV | all domains | Optional audit domain filter |
| issue-id | string | — | Stable issue ID from `maintenance audit` |
| file | path | — | Proposal JSON file for deterministic validation |
| apply | flag | — | Apply an allowed low-risk repair |

### 六项检查

| 检查 | 说明 | 调用的 CLI |
|------|------|-----------|
| `index_freshness` | FTS index health and freshness | `index --check --json` |
| `entity_audit` | Entity graph quality audit (duplicates, pending candidates, incomplete relationships) | `entity --audit` |
| `orphan_related_entries` | Journal `related_entries` referencing unknown entities | Read-only file inspection |
| `search_eval_smoke` | Minimal ablation eval smoke test (3 queries) | `entity-graph-eval --queries <fixture>` |
| `backup_verification` | Backup destination accessibility check | `backup --list --dest <path>` |
| `candidate_edges` | Candidate relationship edges report | `entity --candidate-edges` |

### 状态枚举

每项检查返回以下状态之一：

| 状态 | 含义 |
|------|------|
| `pass` | 检查通过，无需操作 |
| `fail` | 检查失败，需要调查 |
| `needs-user-action` | 需要用户手动操作 |

### JSON 返回值

```json
{
  "success": true,
  "command": "maintenance",
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "maintenance",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "checks": [
    {
      "category": "index_freshness",
      "status": "pass",
      "details": {
        "fts_count": 56,
        "vector_count": 0,
        "file_count": 56,
        "healthy": true
      },
      "timestamp": "2026-05-21T10:00:00.000000+00:00"
    }
  ],
  "summary": {
    "pass_count": 4,
    "fail_count": 0,
    "needs_user_action_count": 2,
    "overall_healthy": true
  },
  "timestamp": "2026-05-21T10:00:05.000000+00:00",
  "error": null
}
```

### LLM 边界

- Default path: **zero LLM calls**. All checks use subprocess delegation or read-only file inspection.
- No `anthropic`, `openai`, or `llm_client` imports in the module.
- Search eval smoke delegates to `entity-graph-eval` which is itself LLM-free.

### 设计约束

- **零生产写入**: maintenance 自身及其所有子进程调用均为只读操作
- **Subprocess 边界**: 所有外部 CLI 调用通过 subprocess，不直接 import 被调用模块内部
- **Legacy report-only**: `maintenance --dry-run` 只报告状态，不执行自动修复
- **Data Doctor repair boundary**: `maintenance repair --apply` can write only
  rebuildable derived artifacts such as generated Markdown indexes, `.index/`,
  `.cache/`, and `.life-index/cache/`, or archive recognized non-canonical
  timestamped journal copies from `Journals/` and loose `entity_graph.yaml.backup_*`
  files into `.trash/maintenance/` after the canonical source still exists. It
  must not modify canonical journals, attachments, `entity_graph.yaml`, import
  source files, config secrets, hand-curated Markdown, or migration state.

### Data Doctor Audit Envelope

Schema: `m33.maintenance_audit.v0`

```json
{
  "success": true,
  "schema_version": "m33.maintenance_audit.v0",
  "command": "maintenance audit",
  "generated_at": "2026-06-01T00:00:00+00:00",
  "summary": {
    "total_issues": 3,
    "domain_counts": {
      "layout": 2,
      "search_index": 1
    },
    "detector_status": {
      "layout": "ok",
      "search_index": "ok"
    },
    "truncated": false,
    "limit": null,
    "offset": 0,
    "has_more": false
  },
  "detectors": [
    {
      "domain": "layout",
      "status": "ok",
      "issue_count": 2
    }
  ],
  "issues": [
    {
      "issue_id": "layout.missing_generated_index:INDEX.md",
      "domain": "layout",
      "type": "missing_generated_index",
      "severity": "warning",
      "risk": "low",
      "repair_class": "derived",
      "repairable": true,
      "message": "Generated root index is missing.",
      "evidence": [
        {
          "path": "INDEX.md",
          "kind": "missing"
        }
      ]
    }
  ],
  "error": null
}
```

Audit domains:

`layout`, `search_index`, `frontmatter`, `text_encoding`, `links`,
`attachments`, `revisions`, `entity_nodes`, `entity_relations`, `import_jobs`,
`migration`, `backup`, `config`, `path_portability`, `privacy`.

All evidence paths are relative to `LIFE_INDEX_DATA_DIR`. Public output must not
include absolute local paths or raw secret values. Detector failures are reported
per domain as `status: "error"` and do not truncate unrelated detector output.

### Data Doctor Plan Envelope

Schema: `m33.maintenance_plan.v0`

`maintenance plan --issue-id <id> --json` returns a dry-run plan for the current
audit issue. Repairable plans include `risk`, `touched_paths`, `preconditions`,
`post_check_command`, `rollback_story`, `requires_user_ack`, and `plan_steps`.
Human-judgment issues return `repairable: false` with a
`non_repairable_reason`.

### Data Doctor Repair Envelope

Schema: `m33.maintenance_repair.v0`

`maintenance repair --dry-run` changes no files and reports `planned_paths`.
`maintenance repair --apply` is implemented only for low-risk repairs:

- generated Markdown indexes via `generate-index --rebuild`;
- search index/cache artifacts via `index --rebuild --fts-only`.
- loose timestamped journal copies such as
  `life-index_YYYY-MM-DD_NNN_YYYYMMDD_HHMMSS_ffffff.md`, archived under
  `.trash/maintenance/timestamped-journal-copies/` only when the matching
  canonical `life-index_YYYY-MM-DD_NNN.md` file still exists.
- loose `entity_graph.yaml.backup_*` files, archived under
  `.trash/maintenance/entity-graph-backups/` only when the canonical
  `entity_graph.yaml` file still exists. The canonical graph is never modified
  by this repair.

Unsafe or non-repairable issue IDs return structured errors such as
`MAINTENANCE_REPAIR_NOT_ALLOWED`, `MAINTENANCE_REPAIR_COMMAND_FAILED`, or
`MAINTENANCE_REPAIR_UNSAFE_CHANGED_PATH`.

### Data Doctor Proposal Validation

Schema: `m33.maintenance_proposal.v0`

`maintenance proposal validate --file proposal.json --json` validates proposal
files produced by users, GUI flows, or L3 agents. It does not call an LLM and it
does not apply changes. It verifies:

- proposal schema version;
- evidence presence;
- relative paths confined to `LIFE_INDEX_DATA_DIR`;
- source file hash freshness;
- explicit `requires_user_ack: true`;
- supported frontmatter fields;
- secret-like token absence;
- entity alias collision safety;
- entity relation source/target existence.

Representative rejection codes include
`MAINTENANCE_PROPOSAL_INVALID_SCHEMA`,
`MAINTENANCE_PROPOSAL_MISSING_EVIDENCE`,
`MAINTENANCE_PROPOSAL_PATH_ESCAPE`,
`MAINTENANCE_PROPOSAL_SECRET_EXPOSURE`,
`MAINTENANCE_PROPOSAL_UNSUPPORTED_FIELD`,
`MAINTENANCE_PROPOSAL_ENTITY_ALIAS_COLLISION`,
`MAINTENANCE_PROPOSAL_MISSING_USER_ACK`, and
`MAINTENANCE_PROPOSAL_STALE_SOURCE_HASH`.

Compatibility: `m33.maintenance_*.v0` is a stable initial public contract.
Additive optional fields may be added without a schema bump; incompatible shape
or semantic changes require a new schema version or schema name.

---

## aggregate

<!-- M16-CONTRACT: aggregate -->

### M16 Public JSON Contract: aggregate

#### JSON Shape / Top-Level Fields

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Command execution success (`not_measurable` is still success) |
| `schema_version` | string | yes | `"m16.aggregate.v0"` — top-level output schema version |
| `query` | string | yes | Caller-provided natural language query (may be empty string) |
| `command` | string | yes | Fixed `"aggregate"` |
| `metric` | string | yes | Computed metric name (e.g., `journal_count`, `entry_count`) |
| `unit` | string | yes | Aggregation unit: `day` / `week` / `month` / `entry` |
| `range` | object | yes | Parsed date range `{since, until}` |
| `predicate` | object | yes | Parsed predicate with `type`, `definition`, and type-specific fields |
| `result` | object | yes | `{count, denominator, exactness, confidence}` plus additive partial fields |
| `buckets` | array | yes | Per-unit group stats (empty for `entry` unit) |
| `matched_entries` | array | yes | Relative paths of entries matching the predicate |
| `excluded_entries` | array | yes | Relative paths of entries not matching |
| `unknown_entries` | array | yes | Entries that could not be evaluated (`{path, reason}`) |
| `evidence_paths` | array | yes | All participating relative paths (matched + excluded + unknown) |
| `limitations` | array | yes | Human-readable limitation notes |
| `performance` | object | yes | `{total_time_ms}` |
| `claim_envelope` | object | yes | M02/A+ evidence-based claim wrapper |
| `evidence_pack` | object | yes | M02/A+ aggregate-specific evidence pack |

#### Field Semantics

- `success`: execution success. `result.exactness = not_measurable` is still `success: true`.
- `command`: always `"aggregate"` even when invoked via the `analyze` alias.
- `result.exactness`: `exact` / `approximate` / `partial` / `not_measurable`.
- `result.confidence`: data quality signal (`high`/`medium`/`low`), not LLM opinion.
- `claim_envelope.schema_version`: `m02a.claim_envelope.v0`.
- `evidence_pack.schema_version`: `m02a.aggregate_evidence_pack.v0`.
- All output paths are relative; no absolute filesystem paths.

#### Error Behavior / Error Codes

Errors use the structured unified format with `command="aggregate"`:

| Code | Meaning | Recovery Strategy |
|------|---------|-------------------|
| E0001 | Invalid input (bad format, unknown predicate, illegal unit) | ask_user |

For both `aggregate` and its `analyze` alias, invalid range, unit, and predicate inputs return `success: false`, `command: "aggregate"`, `error.code: "E0001"`.

#### schema_version Policy

`aggregate` emits a top-level `schema_version` field set to `"m16.aggregate.v0"`. Versioning in additive sub-structures is unchanged:
- `claim_envelope.schema_version = "m02a.claim_envelope.v0"` — stable; changes require a new version string.
- `evidence_pack.schema_version = "m02a.aggregate_evidence_pack.v0"` — stable; changes require a new version string.
- Top-level field names and types are stable; new fields may be added without a version bump.
- A `schema_version` bump will accompany any backward-incompatible change.

<!-- /M16-CONTRACT -->

> **Boundary SSOT.** `aggregate` owns deterministic counts, buckets, and claim
> envelopes over structured journal predicates. It does **not** own typed
> observation time series; use `trajectory` for field-value observations over
> time. It also does **not** replace `search` or `smart-search`; use those for
> retrieval and synthesis. Use `aggregate` only when the user question can be
> settled by a whitelisted predicate over a date range.

### 端点

```bash
life-index aggregate --range <since>..<until> --unit <unit> --predicate <predicate> [--query "..."] [--explain] [--json]
python -m tools aggregate --range <since>..<until> --unit <unit> --predicate <predicate> [--query "..."] [--explain] [--json]
life-index analyze --range <since>..<until> --unit <unit> --predicate <predicate> [--query "..."] [--explain] [--json]
python -m tools analyze --range <since>..<until> --unit <unit> --predicate <predicate> [--query "..."] [--explain] [--json]
```

`analyze` is an alias for `aggregate`. It does not add a separate reasoning
engine; JSON output still uses `"command": "aggregate"` and the same
claim/evidence contract.

<!-- M16-CONTRACT: analyze -->

### M16 Public JSON Contract: analyze

#### JSON Shape / Top-Level Fields

`analyze` produces the **identical** JSON output shape as `aggregate`. The `command` field is always `"aggregate"`. See the `aggregate` M16 contract block for the full field table.

#### Field Semantics

All field semantics are identical to `aggregate`. The alias exists for user convenience; no separate processing pipeline or additional fields are involved.

#### Error Behavior / Error Codes

Error behavior is identical to `aggregate`: invalid inputs return `success: false`, `command: "aggregate"`, `error.code: "E0001"`. Error payloads always use `command: "aggregate"` even when invoked via the `analyze` alias.

#### schema_version Policy

Identical to `aggregate`: emits top-level `schema_version = "m16.aggregate.v0"`. Additive sub-structures carry their own version stamps (`m02a.claim_envelope.v0`, `m02a.aggregate_evidence_pack.v0`).

<!-- /M16-CONTRACT -->

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--range` | string | ✅ | — | 日期范围，格式 `YYYY-MM-DD..YYYY-MM-DD`（两端均包含） |
| `--unit` | enum | ✅ | — | 聚合单位：`day`、`week`、`month`、`entry` |
| `--predicate` | string | ✅ | — | 白名单谓词表达式（见下方） |
| `--query` | string | ❌ | `""` | 原始自然语言查询（仅存入输出，不参与计算） |
| `--explain` | flag | ❌ | false | 在输出中包含人类可读的谓词解释与局限性说明 |
| `--json` | flag | ❌ | false | 输出完整 JSON 契约 |

### 支持的聚合单位

| 单位 | 行为 |
|------|------|
| `day` | 按日历日聚合；同一日多条日志去重 |
| `week` | 按 ISO 周聚合（`YYYY-WNN`） |
| `month` | 按月聚合（`YYYY-MM`） |
| `entry` | 按单条日志文件计数，不做去重 |

### 支持的谓词

| 谓词 | 语法 | 数据要求 | 精确度 | 说明 |
|------|------|----------|--------|------|
| `journal_count` | `journal_count` | 仅需日期范围和日志路径 | `exact` | 统计每个聚合单位内的日志数量 |
| `entry_time_after` | `entry_time_after=HH:MM` | Frontmatter `date` 含时间部分或独立 `time` 字段 | `exact`（全部有时间字段）或 `partial`（部分缺失） | 日志时间戳晚于指定时间 |
| `term_presence` | `term_presence=TERM` | 全文检索覆盖标题、正文、摘要 | `approximate` | 日志内容中出现指定词项 |
| `entity_presence` | `entity_presence=ENTITY_ID` | Entity Graph 别名扩展 + 文本匹配 | `approximate` | 日志中出现指定实体（主名 + 别名） |
| `field_equals` | `field_equals=FIELD:VALUE` | Frontmatter 标量或列表字段 | `exact` | Frontmatter 字段值等于指定值（大小写不敏感）；列表字段匹配任一元素 |

> **⚠️ 重要**：`entry_time_after=22:00` 表示**日志写入/记录时间晚于 22:00**，不是实际入睡时间的证明。系统优先读取 frontmatter `date` 中的 ISO 8601 时间部分；若不存在，则回退到独立的 `time` 字段。若两者均缺失，对应条目进入 `unknown_entries`，精确度降为 `partial`，`count` 为确认下限而非完整计数。

### 返回值

```json
{
  "success": true,
  "query": "过去2天我有多少次晚睡",
  "command": "aggregate",
  "metric": "entry_count",
  "unit": "day",
  "range": {"since": "2026-03-14", "until": "2026-03-15"},
  "predicate": {
    "type": "entry_time_after",
    "threshold": "22:00",
    "definition": "journal timestamp later than 22:00; not proof of actual sleep time"
  },
  "result": {
    "count": 1,
    "denominator": 2,
    "exactness": "partial",
    "confidence": "high",
    "min_count": 1,
    "max_count": 2,
    "unknown_count": 1,
    "unknown_bucket_count": 1,
    "count_semantics": "partial_lower_bound"
  },
  "buckets": [],
  "matched_entries": ["Journals/2026/03/life-index_2026-03-14_001.md"],
  "excluded_entries": [],
  "unknown_entries": [
    {"path": "Journals/2026/03/life-index_2026-03-15_001.md", "reason": "no_time_field_available"}
  ],
  "evidence_paths": [
    "Journals/2026/03/life-index_2026-03-14_001.md",
    "Journals/2026/03/life-index_2026-03-15_001.md"
  ],
  "limitations": [
    "No reliable time-of-day field was available for one or more journal entries."
  ],
  "performance": {"total_time_ms": 45.2}
}
```

### 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 命令执行是否成功（`not_measurable` 仍视为成功） |
| `query` | string | 调用方传入的原始自然语言查询 |
| `command` | string | 固定为 `"aggregate"` |
| `metric` | string | 计算出的指标名，如 `journal_count`、`entry_count`、`term_presence_count`、`entity_presence_count`、`field_equals_count` |
| `unit` | string | 聚合单位 |
| `range` | object | 解析后的日期范围 `{"since", "until"}` |
| `predicate` | object | 解析后的谓词，含 `type`、`threshold`/`term`/`entity_id`/`field`/`value`（如适用）及 `definition` |
| `result.count` | int | 计算结果计数 |
| `result.denominator` | int | 范围内总候选单位数（如总天数） |
| `result.exactness` | enum | `exact` / `approximate` / `partial` / `not_measurable` |
| `result.confidence` | enum | `high` / `medium` / `low`；反映数据质量，非 LLM 意见 |
| `result.min_count` | int | additive；`exactness=partial` 时确认的下限计数 |
| `result.max_count` | int | additive；`exactness=partial` 时可能的上限计数（含未知条目） |
| `result.unknown_count` | int | additive；`exactness=partial` 时缺失数据字段的条目总数 |
| `result.unknown_bucket_count` | int | additive；`exactness=partial` 时仅含未知条目（无确认匹配）的桶数 |
| `result.count_semantics` | string | additive；`exactness=partial` 时为 `"partial_lower_bound"` |
| `buckets` | array | 非 `entry` 单位时的分组统计；每项含 `key`、`count`、`total`、`evidence_paths` |
| `matched_entries` | array | 谓词判定为 true 的日志相对路径 |
| `excluded_entries` | array | 谓词判定为 false 的日志相对路径 |
| `unknown_entries` | array | 无法评估的日志，每项含 `path` 和 `reason` |
| `evidence_paths` | array | 参与结果的所有相对路径（`matched` + `excluded` + `unknown`） |
| `limitations` | array | 人类可读的局限性说明 |
| `performance.total_time_ms` | float | 执行耗时 |
| `claim_envelope` | object | M02/A+ 证据化结论外壳，见下方 Claim Envelope 子节 |
| `evidence_pack` | object | M02/A+ aggregate 专用证据包，见下方 Aggregate Evidence Pack 子节 |

### Claim Envelope（`claim_envelope`）

`claim_envelope` 是 aggregate 结果的 additive 机器可读结论外壳。它不改变 `result` 字段语义，只把已有计数、精确度、谓词和局限性组织成未来 L3/L4 模块可组合的 claim。

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定为 `m02a.claim_envelope.v0` |
| `claim_type` | enum | `measurable_exact` / `measurable_approximate` / `measurable_partial` / `not_measurable`，由 `result.exactness` 映射 |
| `source_command` | string | 固定为 `aggregate` |
| `query` | string | 原始自然语言查询（若调用方提供） |
| `metric` | string | aggregate 指标名 |
| `unit` | string | aggregate 单位 |
| `time_range` | object | 与 `range` 相同的日期范围 |
| `predicate` | object | 解析后的谓词 |
| `value` | int | 与 `result.count` 相同 |
| `denominator` | int | 与 `result.denominator` 相同 |
| `exactness` | enum | 与 `result.exactness` 相同 |
| `confidence` | enum | 与 `result.confidence` 相同 |
| `limitations` | array | 与 aggregate 局限性说明相同 |
| `evidence_pack_ref` | string | 固定为 `aggregate.evidence_pack` |
| `min_count` | int | additive；`exactness=partial` 时与 `result.min_count` 相同 |
| `max_count` | int | additive；`exactness=partial` 时与 `result.max_count` 相同 |
| `unknown_count` | int | additive；`exactness=partial` 时与 `result.unknown_count` 相同 |
| `unknown_bucket_count` | int | additive；`exactness=partial` 时与 `result.unknown_bucket_count` 相同 |
| `count_semantics` | string | additive；`exactness=partial` 时与 `result.count_semantics` 相同 |

### Aggregate Evidence Pack（`evidence_pack`）

aggregate 专用 `evidence_pack` 是 deterministic source map，不是 smart-search `--include-evidence` 的检索证据包。它列出本次 aggregate 判定涉及的日志路径、日期、角色和最小未来兼容钩子。

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定为 `m02a.aggregate_evidence_pack.v0` |
| `source_command` | string | 固定为 `aggregate` |
| `query` | string | 原始自然语言查询（若调用方提供） |
| `time_range` | object | 与 `range` 相同的日期范围 |
| `predicate` | object | 解析后的谓词 |
| `items` | array | 证据项列表 |
| `index_scope` | object | 月度 Index Tree 导航锚点范围，见下方 `index_scope` 子节 |
| `retrieval_coverage` | object | Phase 2B 起 additive：`retrieval_coverage.v1` 完整性权威对象，位于 evidence pack 内；投影规则见下 |
| `page_info` | object | 最小未来钩子，当前固定 `has_more=false`, `cursor=null`, `cursor_hint=null` |

Phase 2B 起的投影规则：`status="complete"` 当且仅当（本次扫描为全树回退扫描，或导航索引月份目录与范围内实际存在的月份目录一致）**且**无可解析失败候选；否则为 `"partial"`，`partial_reasons` 仅使用闭集码（月份核对不一致 → `index_not_fresh`），可解析失败候选经既有 `limitations` 通道披露计数、不新造闭集码。`observed_total` 为本次观察到的候选路径数（`partial` 时为下界）；`returned` 为本次携带的 evidence 条数；`next_offset` 恒为 `null`。D2 注记：`page_info.has_more` 恒为 `false` 属真实性修复——aggregate 无分页，`has_more` 是 `next_offset` 的投影。

`items[]` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | string | 日志相对路径，使用 `/`，不得为绝对路径 |
| `date` | string | 日志日期 |
| `role` | enum | `matched` / `excluded` / `unknown` |
| `bucket` | string | aggregate bucket key |
| `reason` | string | `unknown` 等状态的原因（如适用） |
| `index_node_ref` | object | 可选未来钩子，当前为月度 Index Tree 引用；不是完整 Index Tree API |

`index_node_ref` 字段（additive，月度引用）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定为 `"month"` |
| `node_id` | string | 逻辑节点标识，格式 `month:YYYY-MM`（如 `"month:2026-03"`） |
| `id` | string | 物理月路径，格式 `Journals/YYYY/MM`（如 `"Journals/2026/03"`） |
| `path` | string | 月度索引文件相对路径（如 `"Journals/2026/03/index_2026-03.md"`） |

> `node_id` 与 `id` 构成月度节点的**双身份**：`node_id` 是逻辑标识（用于导航/分组/比较），`id` 是既有物理路径引用（用于文件系统定位）。`node_id` 为 additive 字段，现有消费者可忽略。

`index_scope` 字段（additive，范围级月度锚点）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定为 `"month_range"` |
| `refs` | array | `since..until` 范围内所有月份的 `index_node_ref` 列表，按时间顺序排列 |
| `note` | string | 固定为 `"navigation anchors only; evidence items remain authoritative"` |

> `index_scope` 是导航辅助信息，不替代 `items[]` 中的证据路径。`refs` 列表由 `since`/`until` 日期范围确定性生成，不读取或写入文件系统，不包含 cursor/page 行为，不过滤证据。

### 精确度标签语义

| 标签 | 含义 |
|------|------|
| `exact` | 所有单元均使用可靠结构化数据完成布尔判定，无推断或启发式 |
| `approximate` | 谓词依赖检索召回（词项/实体存在），可能存在假阳性或假阴性 |
| `partial` | 部分条目有所需数据字段，部分缺失；`count` 为确认下限，附加 `min_count`/`max_count`/`unknown_count`/`unknown_bucket_count`/`count_semantics` 字段提供完整范围 |
| `not_measurable` | 所需数据字段缺失或不可靠；`count` 按惯例为 `0`，不得当作统计意义上的零 |

### 行为约束

- **只读**：`aggregate` 不创建、修改或删除任何日志、索引、Entity Graph 文件。
- **本地执行**：所有计算在用户本地完成，无内容上传。
- **沙盒兼容**：正确响应 `LIFE_INDEX_DATA_DIR` 指向临时目录的场景。
- **路径隐私**：输出路径均为相对路径，不含绝对文件系统路径。

### 限制与已知问题

- `analyze` is an alias for `aggregate`; JSON output still uses `"command": "aggregate"`。
- 复合谓词（如 `AND` / `OR`）在 MVP 中**不支持**。
- `term_presence` 和 `entity_presence` 使用大小写不敏感的简单子串匹配（`casefold()`），不做分词或语义扩展；计数为召回支撑，非现实世界行为的证明。
- `field_equals` 的 `FIELD` 限制为 `[A-Za-z_][A-Za-z0-9_]*` 模式；值为大小写不敏感的精确字符串匹配。列表字段匹配任一元素。不含目标字段的条目归入 `excluded_entries`。
- 性能目标：典型范围（< 5 年数据）< 2 秒；未针对 > 10,000 条日志做过专项优化。

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0001 | 无效输入（格式错误、未知谓词、非法单位等） | ask_user |

For both `aggregate` and its `analyze` alias, invalid range, unit, and
predicate inputs are returned as JSON error payloads with `success=false`,
`command="aggregate"`, and `error.code="E0001"`.

---

## edit_journal

### 端点

```bash
life-index edit --journal "<path>" [options]
python -m tools.edit_journal --journal "<path>" [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| journal | string | ✅ | - | 日志文件路径 |
| set-title | string | ❌ | - | 设置标题 |
| set-date | string | ❌ | - | 设置日期 |
| set-location | string | ❌ | - | 设置地点 |
| set-weather | string | ❌ | - | 设置天气 |
| set-mood | string | ❌ | - | 设置心情（逗号分隔） |
| set-people | string | ❌ | - | 设置人物（逗号分隔） |
| set-tags | string | ❌ | - | 设置标签（逗号分隔） |
| set-project | string | ❌ | - | 设置项目 |
| set-topic | string | ❌ | - | 设置主题（逗号分隔） |
| set-abstract | string | ❌ | - | 设置摘要 |
| set-links | string | ❌ | - | 设置外部链接（逗号分隔） |
| set-related-entries | string | ❌ | - | 设置关联日志相对路径（逗号分隔） |
| append-content | string | ❌ | - | 追加内容到正文 |
| replace-content | string | ❌ | - | 替换整个正文 |
| dry-run | flag | ❌ | false | 模拟运行 |

`life-index edit --append-content` receives a literal string and does not expand `@file` arguments.

### 编辑规则

- 只要修改 `location`，就必须同时提交新的 `weather`
- 推荐顺序：先调用 `query_weather` 获取天气；如果失败，允许 Agent 手动联网查询天气后再继续编辑
- 如果最终拿不到新的天气，本次地点修改不得成功写入
- 调用前必须先解决 target selection 与 mutation intent；`edit_journal` 不负责替调用方猜测编辑目标或变更类型

### 地点 / 天气耦合语义

- `edit_journal` 是**确定性修改工具**，不负责自动刷新天气
- `query_weather` 负责天气能力查询，不负责 journal mutation
- 因此只修改 `location` 时，Agent / caller 必须显式承担“先查天气、再同时提交 location + weather”的 orchestration
- 如果天气刷新失败，Agent 必须诚实区分“journal edit 状态”和“weather refresh 状态”，不能暗示天气已经同步正确

### caller-facing 成功 / 失败语义

- `edit_journal` success 应理解为请求的 deterministic mutation 已成功应用
- 如果 edit 前置条件尚未满足（例如 coupled-field prerequisite 未解决），正确行为是先澄清或补齐，再调用工具
- 对于 location/weather 这类耦合修改，调用方必须区分“编辑失败”与“语义对齐尚未完成”

### 返回值

```json
{
  "success": true,
  "write_outcome": "success_pending_confirmation",
  "journal_path": "C:/Users/.../Documents/Life-Index/Journals/2026/03/life-index_2026-03-10_001.md",
  "changes": {
    "location": {"old": "Chongqing, China", "new": "Beijing, China"},
    "weather": {"old": "Sunny", "new": "Cloudy"}
  },
  "content_modified": false,
  "indices_updated": [],
  "error": null
}
```

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0500 | 日志不存在 | ask_user |
| E0502 | 字段不识别 | ask_user |
| E0503 | 无变更 | ask_user |
| E0504 | 修改地点时缺少天气 | ask_user |

---

## query_weather

### 端点

```bash
python -m tools.query_weather --location "<location>" [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| location | string | ❌ | "Chongqing, China" | 地点名称 |
| lat | float | ❌ | - | 纬度 |
| lon | float | ❌ | - | 经度 |
| date | string | ❌ | "today" | 日期 (YYYY-MM-DD) |

### 返回值

```json
{
  "success": true,
  "date": "2026-03-10",
  "location": {"lat": 39.9, "lon": 116.4},
  "weather": {
    "code": 2,
    "description": "Partly cloudy (多云)",
    "simple": "多云",
    "temperature_max": 18.5,
    "temperature_min": 8.2,
    "precipitation": 0.0
  },
  "error": null
}
```

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0400 | API 请求失败 | skip_optional |
| E0401 | API 超时 | skip_optional |
| E0402 | 地点未找到 | ask_user |

### 天气失败后的兜底

- `query_weather` 是首选天气来源
- 如果 `query_weather` 失败，Agent 可手动联网查询天气并将结果提供给 `edit_journal`
- 对于地点修改场景，只有 `query_weather` 和 Agent 手动查询都失败时，才允许把本次修改判定为失败
- `query_weather` 是 capability tool，不是 recovery orchestrator；失败后的流程判断由 Agent / caller 负责

---

## generate_index

<!-- M16-CONTRACT: generate-index -->

### M16 Public JSON Contract: generate-index

#### JSON Shape / Top-Level Fields

`generate-index --json` emits a JSON **array** of result objects (not a single top-level response wrapper). Each element's shape depends on the operation:

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `type` | string | conditional | Operation type: `"monthly"` / `"yearly"` / `"root"` / `"rebuild"` / `"index-b"` / `"entity-profiles"` |
| `success` | bool | yes | Whether this specific operation succeeded |
| `year` | int | conditional | Year (monthly/yearly results) |
| `month` | int | conditional | Month (monthly results) |
| `output_path` | string | conditional | Generated index file path |
| `journal_count` | int | conditional | Number of journals indexed |
| `message` | string | conditional | Human-readable status message |
| `updated` | bool | conditional | Whether the index was actually updated |
| `monthly_indexes_rebuilt` | int | conditional | Rebuild mode: count of monthly indexes rebuilt |
| `yearly_indexes_rebuilt` | int | conditional | Rebuild mode: count of yearly indexes rebuilt |
| `root_index_rebuilt` | bool | conditional | Rebuild mode: whether root was rebuilt |
| `errors` | array | conditional | Rebuild mode: failed result objects |
| `profile_count` | int | conditional | Entity profile materialization: number of profile docs generated |
| `profile_paths` | array<string> | conditional | Entity profile materialization: generated profile doc paths relative to data root |
| `source_hash` | string | conditional | Entity profile materialization: source entity graph hash used in generated docs |

#### Field Semantics

- The output is a JSON array; each element represents one index operation result.
- `success: true` on an element means that specific index generation succeeded.
- Error objects from internal functions (`create_error_response`) are appended to the results array, not emitted as a separate top-level error envelope.
- `journal_count`: number of journals covered by the generated index.
- `generate-index --all-months` and `generate-index --rebuild` append an additive
  `type: "index-b"` element that refreshes `.life-index/index-b/` navigation docs
  and manifest. Legacy generated indexes remain compatibility artifacts; Index B
  is the host-agent navigation surface.

#### Error Behavior / Error Codes

**Known deviation**: `generate-index` error handling is inconsistent with the unified error format.

- **Parse errors** (e.g., invalid `--month` format): the CLI raises `SystemExit` and outputs a plain text error message. No JSON error payload is emitted.
- **I/O errors** during index generation: `create_error_response` objects are appended as elements within the results array. These are not top-level CLI error envelopes.
- No structured `{success: false, error: {code, message, ...}}` envelope is emitted for CLI-level errors.
- Runtime alignment to the unified error format is deferred to a post-M16 milestone.

#### schema_version Policy

`generate-index` does **not** emit a `schema_version` field at any level. Top-level field names and types are stable; new fields may be added without a version bump. **BLOCKED**: `generate-index --json` emits a JSON **array**, not a dict; wrapping it with a top-level `schema_version` would be a breaking shape change for existing consumers. A future milestone may introduce versioning by migrating the output to a dict wrapper (`{schema_version, results}`), which requires a documented migration path.

<!-- /M16-CONTRACT -->

> ⚡ 别名：`life-index abstract`（向后兼容）

### 端点

```bash
python -m tools.generate_index [options]
life-index generate-index [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| month | string | ❌ | - | 生成月度索引 (YYYY-MM)，输出 `index_YYYY-MM.md` |
| year | int | ❌ | - | 生成年度索引 (YYYY)，输出 `index_YYYY.md` |
| all-months | flag | ❌ | false | 批量生成所有有日志月份的月度索引，并同步刷新 Index B；与 `year` 一起使用时仅生成该年月份 |
| rebuild | flag | ❌ | false | 全量重建 legacy 三层索引树（月→年→根），并同步刷新 Index B |
| entities | flag | ❌ | false | 物化 confirmed 实体档案，输出 `Entities/index.md` 与 `Entities/<entity_id>.md`，并在根 `INDEX.md` 加入口 |
| id | string | ❌ | - | 与 `entities` 一起使用时，仅物化指定实体 ID 的档案 |
| dry-run | flag | ❌ | false | 预览模式 |

### 返回值

月度索引：

```json
{
  "success": true,
  "type": "monthly",
  "year": 2026,
  "month": 3,
  "output_path": "~/Documents/Life-Index/Journals/2026/03/index_2026-03.md",
  "journal_count": 15,
  "message": "月度索引已生成"
}
```

全量重建：

```json
{
  "success": true,
  "monthly_indexes_rebuilt": 12,
  "yearly_indexes_rebuilt": 1,
  "root_index_rebuilt": true,
  "errors": []
}
```

实体档案物化：

```bash
life-index abstract --entities --json
life-index abstract --entities --id actor-alice --json
```

```json
{
  "success": true,
  "type": "entity-profiles",
  "updated": true,
  "dry_run": false,
  "entity_id": null,
  "profile_count": 2,
  "skipped_candidate_count": 1,
  "source_hash": "sha256:...",
  "index_path": "~/Documents/Life-Index/Entities/index.md",
  "root_index_path": "~/Documents/Life-Index/INDEX.md",
  "profile_paths": [
    "Entities/actor-alice.md",
    "Entities/actor-bob.md"
  ],
  "removed_stale_profiles": [],
  "message": "Generated 2 entity profile(s)"
}
```

`Entities/*.md` 是派生视图：只读 `entity_graph.yaml` 和搜索索引生成，不回写图谱。
candidate 实体不会进入清单或档案。档案文件名使用稳定 opaque `entity_id`；
frontmatter 含 `entity_id`、`type`、`kind`、`status`、`generated_at` 与 `source_hash`。

---

## build_index

### 端点

```bash
python -m tools.build_index [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| rebuild | flag | ❌ | false | 全量重建索引 |
| validate | flag | ❌ | false | 验证索引完整性 |
| check | flag | ❌ | false | 索引一致性诊断（只读，不修改任何文件） |
| fts-only | flag | ❌ | false | 仅更新 FTS 索引 |
| vec-only | flag | ❌ | false | Deprecated compatibility no-op；接受但不构建向量索引 |
| stats | flag | ❌ | false | 显示索引统计信息 |
| json | flag | ❌ | false | 以 JSON 格式输出结果（含 `schema_version` + `provenance`） |
| explain | flag | ❌ | false | 输出构建诊断 JSON（含 `diagnostics`） |
| cache-dry-run | flag | ❌ | false | 评估 cache 失效状态，**零写入** |

### 返回值

**构建/重建模式**：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "index",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "fts": {
    "success": true,
    "added": 45,
    "updated": 0,
    "removed": 0
  },
  "semantic_status": "disabled",
  "warnings": [],
  "duration_seconds": 1.2
}
```

**`--check` 模式**：

```json
{
  "healthy": true,
  "fts_count": 53,
  "vector_count": 0,
  "file_count": 53,
  "issues": []
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| healthy | bool | FTS 与实际日志文件一致时为 true |
| fts_count | int | FTS 索引中的条目数 |
| vector_count | int | Legacy compatibility 字段；当前恒为 `0` |
| file_count | int | Journals/ 下实际日志文件数 |
| issues | string[] | 不一致描述列表；空列表表示健康 |

**`--cache-dry-run` 模式**：

```json
{
  "success": true,
  "dry_run": true,
  "cache_version": {
    "exists": true,
    "stored_schema_version": "v1.1.2",
    "stored_source_hash": "sha256:...",
    "current_schema_version": "v1.1.2",
    "version_match": true,
    "hash_match": true,
    "would_rebuild": false,
    "reasons": []
  }
}
```

退出码：healthy → 0, unhealthy → 1（便于 CI 集成）

---

## health

<!-- M16-CONTRACT: health -->

### M16 Public JSON Contract: health

#### JSON Shape / Top-Level Fields

**Standard mode:**

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Always `true` (even when degraded) |
| `schema_version` | string | yes | `"m16.health.v0"` — top-level output schema version |
| `data` | object | yes | `{status, checks[], upgrade_freshness, entity_maintenance, issues[], issue_count, actionable_issues[], chronic_debt[], issue_summary}` |
| `data.status` | string | yes | `"healthy"` / `"degraded"` / `"unhealthy"` |
| `data.checks` | array | yes | Individual check results |
| `data.upgrade_freshness` | object | yes | Session-visible local freshness signal for host agents |
| `data.entity_maintenance` | object | yes | Entity graph rhythm signal: traffic light, pending count, audit age, duplicate count, and review command |
| `data.issues` | array | yes | Issue descriptions |
| `data.issue_count` | int | yes | Number of issues found |
| `data.actionable_issues` | array | yes | Issues with immediate commands or setup fixes to run now |
| `data.chronic_debt` | array | yes | Non-blocking recurring maintenance reminders |
| `data.issue_summary` | object | yes | Counts for actionable and chronic issue groups |
| `events` | array | no | Piggyback event notifications |

**`--data-audit` mode:**

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Always `true` |
| `schema_version` | string | yes | `"m16.health.v0"` — top-level output schema version |
| `data` | object | yes | Data Doctor summary and next-step commands |
| `data.source` | string | yes | `"maintenance audit"` |
| `data.status` | string | yes | `"ok"` or `"issues_found"` |
| `data.issue_count` | int | yes | Total Data Doctor issue count |
| `data.summary` | object | yes | `maintenance audit` summary object |
| `data.detectors` | array | yes | Per-domain detector rows from Data Doctor |
| `data.issues_preview` | array | yes | Bounded preview of audit issues |
| `data.next_command` | string | yes | Full audit command (`life-index maintenance audit --json`) |
| `data.plan_command_template` | string | yes | Plan command template for one issue id |

#### Field Semantics

- `success`: always `true` for health checks. Degraded/unhealthy status is communicated via `data.status`, not via `success: false`.
- `data.status`: the primary health indicator. `degraded` means partial functionality; `unhealthy` means critical issues.
- `data.checks`: additive; new checks may be added (e.g., `index_tree` check).
- Suggested commands in `data.checks`, `data.upgrade_freshness`, and
  `events[].data` may include additive `side_effect: "read" | "write"` and
  `side_effect_note` metadata. Host agents should inspect this metadata before
  executing a suggestion. `write` may still mean a derived-artifact refresh
  rather than source-data mutation; the note states the boundary.
- `data.upgrade_freshness`: non-blocking session signal. It reports local
  installed/manifest mismatch and checkout-vs-upstream metadata, including
  `suggested_refresh_step: "life-index upgrade --plan --json"` when a local
  update signal is visible, with `side_effect: "read"`. It does not replace
  `bootstrap --json`. Editable checkouts also report dirty worktree
  hints under `git.dirty` / `git.dirty_count`; a dirty-only checkout adds
  `warning` plus the read-only `suggested_command: "git --no-optional-locks status --short"` with
  `side_effect: "read"`. Its note tells the caller to leave changes untouched
  and ask the owner; it does not add a health issue or block other operations.
- `data.entity_maintenance`: `traffic_light` is `green` when pending review is
  clear and the graph was touched within 30 days; `yellow` when candidates are
  pending or the audit is stale; `red` when structural errors or duplicate
  confirmed names need review. Entity suggestions point to
  `life-index entity --review`. When `traffic_light == "green"` and
  `pending_count == 0`, `suggested_next_step.command` is `null`.
- `data.actionable_issues`: install/runtime or index-readiness items that can be acted on immediately.
- `data.chronic_debt`: non-blocking maintenance reminders such as entity graph or Index Tree upkeep. These remain visible without implying an install failure.
- `data.checks[name="data_directory"].journal_count`: counts only canonical journal filenames matching `life-index_YYYY-MM-DD_NNN.md`; this is the same journal enumeration used by `bootstrap` and `migrate --dry-run`.
- `data.checks[name="data_directory"].last_journal_date`: newest canonical
  journal filename date (`YYYY-MM-DD`) or `null` when no canonical journals
  exist.
- `health --data-audit`: compatibility summary over `maintenance audit`; Data
  Doctor is the SSOT for data-health issue detection, planning, and low-risk
  repairs.
- `events`: piggyback notifications; same format as other commands.

#### Error Behavior / Error Codes

**Known deviation**: `health` does not use the structured error format for error paths.

- Standard mode always returns `success: true`. Health status degradation is communicated through `data.status` and `data.issues`, not through structured error codes.
- No `{success: false, error: {code, message, ...}}` envelope is emitted in normal operation.
- Runtime alignment to the unified error format is deferred to a post-M16 milestone.

#### schema_version Policy

`health` emits a top-level `schema_version` field set to `"m16.health.v0"`. The output shape is stable; new `data.checks` entries and additive `health --data-audit` summary fields may be added without a version bump. A `schema_version` bump will accompany any backward-incompatible change.

<!-- /M16-CONTRACT -->

### 端点

```bash
python -m tools health [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| json | flag | ❌ | true | 输出 JSON（默认行为） |
| data-audit | flag | ❌ | false | 数据目录清洁度审计 |
| cache-audit | flag | ❌ | false | Cache 版本只读审计（JSON） |
| help / h | flag | ❌ | false | 显示 usage/help 文本，不执行 health checks |

### 返回值

**标准模式**：

```json
{
  "success": true,
  "data": {
    "status": "healthy|degraded|unhealthy",
    "checks": [ ... ],
    "issues": [ ... ],
    "issue_count": 0,
    "actionable_issues": [ ... ],
    "chronic_debt": [ ... ],
    "issue_summary": {
      "actionable_count": 0,
      "chronic_debt_count": 0,
      "non_blocking_count": 0
    }
  },
  "events": [ ... ]
}
```

**`--cache-audit` 模式**：

```json
{
  "success": true,
  "cache_audit": {
    "version_exists": true,
    "status": "valid|stale|incompatible|missing",
    "json": true
  }
}
```

Additive standard checks may include:

| check.name | status | meaning |
|------------|--------|---------|
| index_tree | ok / warning / info | Internal Index Tree freshness visibility. Warnings are non-critical; run `life-index generate-index --all-months` to refresh missing/stale month nodes and Index B navigation docs. |

**`--data-audit` 模式**：

```json
{
  "success": true,
  "data": {
    "status": "issues_found",
    "source": "maintenance audit",
    "issue_count": 1,
    "summary": {"total_issues": 1, "domain_counts": {"revisions": 1}},
    "detectors": [{"domain": "revisions", "status": "ok", "issue_count": 1}],
    "issues_preview": [
      {
        "issue_id": "revisions.entity_graph_backup_copy:entity_graph.yaml.backup_20260621_120000",
        "domain": "revisions",
        "type": "entity_graph_backup_copy",
        "repairable": true
      }
    ],
    "next_command": "life-index maintenance audit --json",
    "plan_command_template": "life-index maintenance plan --issue-id <issue-id> --json"
  }
}
```

`health --data-audit` 不再维护独立 detector 栈。它只显示 Data Doctor 摘要和跳转命令；
完整 issue 列表、dry-run plan 和可确认 repair 均由 `maintenance audit|plan|repair`
提供。

---

## backup

### 端点

```bash
python -m tools.backup [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| dest | string | 条件必填 | - | 备份目标目录；create/list 模式需要 |
| full | flag | ❌ | false | 执行全量备份 |
| dry-run | flag | ❌ | false | 模拟运行，不实际复制文件 |
| list | flag | ❌ | false | 列出指定备份目录下的备份记录 |
| restore | string | ❌ | - | 从指定备份目录恢复 |

### 返回值

创建备份示例：

```json
{
  "success": true,
  "backup_path": "D:/backup/life-index-backup-20260325_120000",
  "files_backed_up": 42,
  "files_skipped": 10,
  "errors": [],
  "manifest_path": "D:/backup/.life-index-backup-manifest.json",
  "recovery_manifest_path": "D:/backup/life-index-backup-20260325_120000/.life-index-recovery-manifest.json"
}
```

### 说明

- `backup` 属于数据安全与 operator 工具，不改变 journal/frontmatter 契约
- `--full` 成功时，timestamped backup 内的
  `.life-index-recovery-manifest.json` 是自包含恢复证据。它使用
  `schema_version: "life-index.backup-manifest.v1"`、`hash_algorithm: "sha256"`
  和按相对路径排序的 `artifacts[]`。每项包含 `path`、`classification`、
  `included`、`sha256`、`size`。
- journals、attachments 与 `entity_graph.yaml` 分类为 `canonical_source`。
  已发现的 `.index/` 文件分类为 `rebuildable_derived` 且 `included: false`；
  restore 后用 `life-index index --rebuild` 重建，不把旧机器缓存恢复为真相源。
- full backup 不允许 caller exclusion 移除任何 canonical source；这种
  请求会 fail closed，不发布 recovery manifest。同一秒内的多次备份
  使用独立的 create-only 后缀目录，catalog 保留每个 recovery point。
- recovery artifact 路径以规范化后的精确字符串为身份。大小写不同
  的合法源文件可在 case-sensitive 备份/恢复文件系统上保留；若目标
  文件系统无法区分，则在发布或恢复数据前 fail closed。
- 任一 source copy 失败时，结果 `success: false` 且 `errors[]` 指明 artifact；
  该 backup 不发布 complete recovery manifest，也不追加成功 catalog record。
- manifest-backed restore 在任何复制前校验封闭的 manifest/artifact
  schema、`complete: true`、唯一且规范化的相对路径、固定的 path-to-
  classification/included 映射、size 与 SHA-256。备份源和恢复目标路径
  中的 symlink/reparse point 会 fail closed。
- 目标必须不存在或完全为空；非空目标会在零变更前失败，restore 不
  提供 overlay/overwrite 语义。若复制中途失败，restore 精确撤销本次
  已创建的文件/目录，将目标恢复为可重试的空状态。
- 通过 recovery manifest 校验的恢复返回 `restore_mode:
  "manifest_verified"` 和 `recovery_manifest_verified: true`。无 recovery
  manifest 的旧备份保持兼容，但返回 `restore_mode: "legacy_unverified"`、
  `recovery_manifest_verified: false` 及明确的 `warnings[]`；不得将其表述为
  manifest-verified recovery。
- destination-level catalog 只在文件复制完成后持有专用文件锁，重新
  读取最新 history/files 并合并本次记录，然后通过临时文件原子替换。
  发布中断保留旧 catalog 字节不变，当前 backup 返回 `success: false`。
- CLI restore 的目标是当前 `LIFE_INDEX_DATA_DIR`。自动化恢复必须设置
  `LIFE_INDEX_VALIDATION_MODE=1` 和显式 sandbox `LIFE_INDEX_DATA_DIR`，并先证明
  目标为空。

---

## verify

### 端点

```bash
life-index verify [--json]
python -m tools verify [--json]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--json` | flag | ❌ | false | 以 JSON 格式输出结果 |

### 返回值

```json
{
  "success": true,
  "total_journals": 42,
  "checks": [
    {
      "name": "frontmatter_valid",
      "status": "ok",
      "count": 42,
      "issues": []
    },
    {
      "name": "required_fields",
      "status": "ok",
      "count": 42,
      "issues": []
    },
    {
      "name": "fts_consistency",
      "status": "ok",
      "count": 42,
      "issues": []
    },
    {
      "name": "attachment_refs",
      "status": "ok",
      "count": 3,
      "issues": []
    },
    {
      "name": "topic_consistency",
      "status": "ok",
      "count": 15,
      "issues": []
    }
  ],
  "issues_count": 0,
  "suggestion": ""
}
```

### 检查项说明

| 检查名 | 说明 |
|--------|------|
| `frontmatter_valid` | 每篇日志的 YAML frontmatter 是否可正常解析 |
| `required_fields` | 必填字段（如 `date`）是否完整 |
| `fts_consistency` | FTS 索引条目与实际日志文件的一致性（缺失 / 孤儿） |
| `attachment_refs` | 正文中引用的附件文件是否存在 |
| `topic_consistency` | `by-topic/` 索引中链接的日志路径是否有效 |

`fts_consistency` 的 canonical journal 集合不包含 co-located `.revisions/` 编辑快照；FTS rebuild 同样不索引这些快照。真实 canonical journal 缺失和真实孤儿 FTS 行仍会报告。

### 行为约束

- **只读**：不创建、修改或删除任何文件。
- `success` 为 `true` 当且仅当 `issues_count == 0`。
- 存在问题时，`suggestion` 包含修复建议（如 `life-index index --rebuild`）。

---

## timeline

<!-- M16-CONTRACT: timeline -->

### M16 Public JSON Contract: timeline

#### JSON Shape / Top-Level Fields

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Whether the timeline was generated |
| `schema_version` | string | yes | `"m16.timeline.v0"` — top-level output schema version |
| `range` | array | yes | `[start_month, end_month]` as `"YYYY-MM"` strings |
| `entries` | array | yes | Timeline entry objects |
| `entries[].date` | string | yes | Entry date `"YYYY-MM-DD"` |
| `entries[].title` | string | yes | Entry title |
| `entries[].mood` | array | yes | Mood tags |
| `entries[].abstract` | string | yes | Entry abstract/summary |
| `entries[].path` | string | yes | Relative journal path |
| `total` | int | yes | Total number of entries |

#### Field Semantics

- `success`: whether the timeline was generated successfully.
- `range`: two-element array of the requested time range (YYYY-MM format, inclusive).
- `entries`: sorted by date ascending.
- `entries[].path`: relative path to the journal file.
- `total`: total count of entries in the response.

#### Error Behavior / Error Codes

**Known deviation**: `timeline` error handling is inconsistent with the unified error format.

- Invalid date format returns `{success: false, error: "Invalid date format..."}` where `error` is a **plain string**, not a structured `{code, message, details, recovery_strategy}` object.
- The `success` and `error` keys are present, but `error` does not conform to the unified error object format documented in the 通用规范.
- Runtime alignment to the structured error format is deferred to a post-M16 milestone.

#### schema_version Policy

`timeline` emits a top-level `schema_version` field set to `"m16.timeline.v0"`. Top-level field names and types are stable; new fields may be added without a version bump. A `schema_version` bump will accompany any backward-incompatible change.

<!-- /M16-CONTRACT -->

### 端点

```bash
life-index timeline --range <START> <END> [--topic <topic>]
python -m tools timeline --range <START> <END> [--topic <topic>]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--range` | string×2 | ✅ | — | 时间范围，两个 `YYYY-MM` 参数（起止月份，均包含） |
| `--topic` | string | ❌ | — | 按主题过滤 |

### 返回值

```json
{
  "success": true,
  "range": ["2026-01", "2026-03"],
  "entries": [
    {
      "date": "2026-01-15",
      "title": "项目启动",
      "mood": ["focused"],
      "abstract": "开始了新项目的开发...",
      "path": "Journals/2026/01/life-index_2026-01-15_001.md"
    }
  ],
  "total": 25
}
```

### 行为约束

- **只读**：不创建、修改或删除任何文件。
- `entries` 按日期升序排列。
- `--topic` 过滤匹配 frontmatter `topic` 字段（列表中任一元素）。
- 日期格式错误时返回 `success: false`，`error` 字段含描述。

---

## on-this-day

<!-- M24-CONTRACT: on-this-day -->

### M24 Public JSON Contract: on-this-day

#### JSON Shape / Top-Level Fields

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Whether the command succeeded |
| `command` | string | yes | Fixed `"on-this-day"` |
| `schema_version` | string | yes | `"m24.on_this_day.v0"` |
| `query` | object | yes | Echo of resolved query/date parameters |
| `query.date` | string | yes | Target date `"YYYY-MM-DD"` (defaults to today) |
| `query.month_day` | string | yes | Target month/day `"MM-DD"` used for matching |
| `query.years_back` | int | yes | Years lookback range used |
| `query.since_year` | int | yes | First prior year scanned |
| `query.until_year` | int | yes | Last prior year scanned; excludes target year |
| `matches` | array | yes | Array of match objects (may be empty) |
| `matches[].date` | string | yes | Entry date `"YYYY-MM-DD"` |
| `matches[].year` | int | yes | Entry year |
| `matches[].years_ago` | int | yes | How many years before target |
| `matches[].title` | string | yes | Entry title |
| `matches[].abstract` | string | yes | Entry abstract |
| `matches[].mood` | array | yes | Mood tags from the timeline entry |
| `matches[].path` | string | yes | Relative journal path (forward slashes only) |
| `matches[].source_command` | string | yes | Fixed `"timeline"` |
| `total` | int | yes | Count of returned matches |
| `evidence_paths` | array | yes | Array of relative paths |
| `source_contracts` | array | yes | `[{command: "timeline", contract: "M16 Public JSON Contract"}]` |
| `limitations` | array | yes | Human-readable limitation notes |
| `performance` | object | yes | `{timeline_calls, total_time_ms}` |
| `error` | object\|null | yes | Structured error on failure; `null` on success |

#### Field Semantics

- `success`: execution success. No matches is still `success: true` with `total: 0` and `matches: []`.
- `command`: always `"on-this-day"`.
- `schema_version`: `"m24.on_this_day.v0"`.
- `query.date`: the resolved target date in YYYY-MM-DD format (defaults to today).
- `query.month_day`: the same-month/day key used to filter timeline entries.
- `query.years_back`: the lookback range in years (`target_year - years_back` through `target_year - 1`).
- `query.since_year` / `query.until_year`: inclusive prior-year scan bounds.
- `matches`: sorted newest-first by date; excludes the target year.
- `matches[].path`: relative path with forward slashes only; no backslashes.
- `total`: count of matches actually returned (after `--limit` applied).
- `source_contracts`: identifies the upstream data source contract.
- `performance.timeline_calls`: number of timeline subprocess invocations.

#### Error Behavior / Error Codes

| Code | Meaning | Recovery Strategy |
|------|---------|-------------------|
| E2401 | Invalid `--date` format | ask_user |
| E2402 | Invalid numeric bounds (`--years-back` or `--limit`) | ask_user |
| E2403 | Timeline subprocess/contract failure | retry |

#### schema_version Policy

`on-this-day` emits `schema_version = "m24.on_this_day.v0"`. Top-level field names and types are stable; new fields may be added without a version bump. A version bump will accompany any backward-incompatible change.

<!-- /M24-CONTRACT -->

### 端点

```bash
life-index on-this-day [--date YYYY-MM-DD] [--years-back N] [--limit N] [--json]
python -m tools on-this-day [--date YYYY-MM-DD] [--years-back N] [--limit N] [--json]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--date` | string | ❌ | today | 目标日期 (YYYY-MM-DD) |
| `--years-back` | int | ❌ | 10 | 向前回溯年数 |
| `--limit` | int | ❌ | 20 | 最大返回条数 |
| `--json` | flag | ❌ | true | 输出 JSON（唯一格式） |

### 返回值

```json
{
  "success": true,
  "command": "on-this-day",
  "schema_version": "m24.on_this_day.v0",
  "query": {
    "date": "2026-05-19",
    "month_day": "05-19",
    "years_back": 10,
    "since_year": 2016,
    "until_year": 2025
  },
  "matches": [
    {
      "date": "2025-05-19",
      "year": 2025,
      "years_ago": 1,
      "title": "Example title",
      "abstract": "Example abstract",
      "mood": ["calm"],
      "path": "Journals/2025/05/life-index_2025-05-19_001.md",
      "source_command": "timeline"
    }
  ],
  "total": 1,
  "evidence_paths": [
    "Journals/2025/05/life-index_2025-05-19_001.md"
  ],
  "source_contracts": [
    {"command": "timeline", "contract": "M16 Public JSON Contract"}
  ],
  "limitations": [
    "Deterministic same-month/day recall aid; not narrative synthesis.",
    "Relies on timeline CLI subprocess for journal discovery."
  ],
  "performance": {
    "timeline_calls": 10,
    "total_time_ms": 500
  },
  "error": null
}
```

### 行为约束

- **只读**：不创建、修改或删除任何文件。
- 通过 `timeline` CLI 子进程发现日志条目；不直接扫描 `Journals/**`。
- 排除目标年份的条目。
- `matches` 按日期降序排列（newest-first）。
- 所有路径为相对路径，仅使用正斜杠。

---

## recall

> **Deprecated compatibility wrapper**: `recall` is retained for existing
> integrations for one compatibility window. New host-agent flows should call
> `life-index search` directly. Use `life-index search --query "..." --no-semantic`
> for strict FTS-only retrieval, and `life-index search --query "..."` for the
> default deterministic search path.

<!-- GBRAIN-E-CONTRACT: recall -->

### recall Public JSON Contract

#### JSON Shape / Top-Level Fields

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Whether the recall search succeeded |
| `schema_version` | string | yes | `"gbrain.recall.v1"` |
| `mode` | string | yes | Requested mode: `default` / `recall` / `deep` |
| `effective_mode` | string | yes | Actual mode used (may differ from `mode` on degradation) |
| `query` | string | yes | Search query string |
| `results` | array | yes | Array of search result objects from L2 (may be empty) |
| `source_command` | string | yes | L2 command used: `search --no-semantic` / `search` |
| `deprecated` | bool | yes | Always `true`; marks `recall` as a compatibility wrapper |
| `deprecation` | object | yes | Replacement guidance for new callers |
| `performance` | object | yes | `{total_time_ms}` |
| `error` | object\|null | yes | Structured error on failure; `null` on success |

#### Field Semantics

- `success`: search execution success. Empty results is still `success: true` with `results: []`.
- `mode`: the mode requested by the caller.
- `effective_mode`: the mode actually executed. `mode=deep` is retained as a compatibility alias and executes deterministic `recall`.
- `source_command`: identifies which L2 command was used — confirms subprocess boundary.
- `results`: extracted from L2 output (`merged_results` from `search`; `filtered_results` is tolerated for old internal compatibility).
- `deprecated`: marks this command as compatibility-only.
- `deprecation.replacement_command`: direct `search` command new callers should use.

#### Mode Behavior

| Mode | L2 Command | LLM? | Notes |
|------|-----------|------|-------|
| `default` | `search --no-semantic` | No | Compatibility alias for pure FTS keyword search. Use `search --no-semantic` directly in new flows. |
| `recall` | `search` | No | Compatibility alias for the default search path. Use `search` directly in new flows. |
| `deep` | `search` | No | Compatibility alias for deterministic recall. Stderr warning emitted. `effective_mode=recall`. Use `search` directly in new flows. |

#### Error Behavior / Error Codes

| Code | Meaning | Recovery Strategy |
|------|---------|-------------------|
| E2501 | Invalid mode value | ask_user |
| E2502 | Empty query | ask_user |
| E2503 | L2 subprocess failure | retry |

#### schema_version Policy

`recall` emits `schema_version = "gbrain.recall.v1"`. Top-level field names and types are stable; new fields may be added without a version bump.

<!-- /GBRAIN-E-CONTRACT -->

### 端点

```bash
life-index recall --mode {default|recall|deep} --query "..."
python -m tools recall --mode {default|recall|deep} --query "..."
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--mode` | enum | ✅ | - | 兼容模式：`default`（`search --no-semantic`）、`recall`（`search`）、`deep`（`search`，`effective_mode=recall`） |
| `--query` | string | ✅ | - | 搜索查询字符串 |

### 返回值

```json
{
  "success": true,
  "schema_version": "gbrain.recall.v1",
  "mode": "default",
  "effective_mode": "default",
  "query": "python",
  "results": [
    {
      "path": "C:/Users/.../Journals/2026/03/life-index_2026-03-01_001.md",
      "rel_path": "Journals/2026/03/life-index_2026-03-01_001.md",
      "title": "Python Learning",
      "date": "2026-03-01",
      "rrf_score": 0.85
    }
  ],
  "source_command": "search --no-semantic",
  "deprecated": true,
  "deprecation": {
    "message": "recall is a deprecated compatibility wrapper over search; new host-agent flows should call search directly.",
    "replacement_command": "life-index search --query ... --no-semantic",
    "compatibility_window": "command retained for existing integrations"
  },
  "performance": {
    "total_time_ms": 50
  },
  "error": null
}
```

### 行为约束

- **只读**：不创建、修改或删除任何文件。
- 通过 subprocess 调用 L2 `search`；不直接 import L2 内部模块。
- `recall` 是兼容壳，不是独立检索能力。新调用方应直接使用 `search`。
- `default` 和 `recall` 模式：零 LLM 调用。
- `deep` 模式：作为确定性 `recall` 兼容别名执行，stderr 输出警告。
- `--use-llm` 已退役；传入该 flag 会被 CLI 参数解析拒绝。
- 保留 `LIFE_INDEX_DATA_DIR` 环境变量传递给子进程。

---

## entity

<!-- M16-CONTRACT: entity -->

### M16 Public JSON Contract: entity

#### JSON Shape / Top-Level Fields

`entity` has multiple subcommand shapes. All share a common envelope pattern but with known deviations:

**Standard envelope** (used by `build --from-batch`, `audit --json`, `maintain --normalize`, `maintain --delete`, `maintain --add-relationship`, `--audit`, `--stats`, `--check`, `--review`, `--list`, `--propose`, `--apply-batch`):

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `success` | bool | yes | Whether the subcommand succeeded |
| `schema_version` | string | yes | `"v1.1.1"` — top-level output schema版本（取代 `m16.entity.v0`） |
| `provenance` | object | yes | Provenance envelope；详见 [v1.1.1 Observability Contract](#v111-observability-contract) |
| `data` | object\|array | yes | Subcommand-specific result payload |
| `error` | null\|string | yes | `null` on success; string on some error paths |

**action deviations** (`--unmerge`, `--review --action ...`; flat envelope, no `data` wrapper):

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the action succeeded |
| `action` | string | `"merge_as_alias"`, `"add_relationship"`, `"unmerge"`, etc. |
| `source_id` | string | Source entity ID when applicable |
| `target_id` | string | Target entity ID when applicable |
| `transferred_names` | array | Names/aliases transferred from source to target for merge |

**`--resolve` envelope:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether resolution succeeded |
| `data` | object\|null | Resolved entity or null |
| `error` | null\|string | `null` on success; plain string (e.g., `"Entity not found"`) on failure |

#### Field Semantics

- `success`: subcommand execution success.
- `data`: subcommand-specific payload. Shape varies by subcommand (see per-subcommand examples below).
- `error`: on most subcommands, `null` for success. Known deviations:
  - `--resolve` returns a plain string error message on failure (not a structured error object).
  - `--unmerge` and `--review --action ...` return flat action objects without `data` wrapper.
- `--audit` data contains: `audit_date`, `total_entities`, `issues[]`, `summary{}`, and neutral `facts{}`.
- `build --from-journals --preview --json` previews journal-frontmatter seed candidates without mutating `entity_graph.yaml`; `data` contains `preview`, `source`, `new_entities`, `added[]`, `skipped_existing[]`, and `skipped_low_frequency[]`.
- `build --from-batch FILE --preview/--apply --json` delegates to `--apply-batch` and preserves its `data` shape: `preview`, `new_entities`, `new_relationships`, `conflicts`, `duplicates_skipped`, and `conflict_items`.
- `profile --id ENTITY_ID --json` and `profile --name NAME --json` assemble a confirmed entity profile from `entity_graph.yaml` plus the FTS index; `data` contains `identity`, `relationships`, `mentions`, `evidence`, and `stats`. Candidate entities fail closed and point to `entity --review`.
- `audit --json` data is a read-only workflow facade containing `workflow: "audit"`, `traffic_light`, `pending_count`, `structural_issue_count`, `quality_issue_count`, `duplicate_count`, `next_step{}`, and `components{check,audit,stats}`.
- `maintain --normalize --preview/--apply --backup --json` data contains `workflow: "maintain.normalize"`, `preview`, `applied`, `summary{entity_count,change_count,review_question_count}`, `changes[]`, `review_questions[]`, and `backup_path`.
- `maintain --delete --id ENTITY_ID --preview/--apply --backup --json` data contains `workflow: "maintain.delete"`, `preview`, `applied`, `backup_path`, `deleted_id`, `deleted_name`, and `cleaned_refs[]`.
- `maintain --add-relationship --id SOURCE_ID --target-id TARGET_ID --relation RELATION --preview/--apply --json` data contains `workflow: "maintain.add_relationship"`, `preview`, `applied`, `source_id`, `source_name`, `target_id`, `target_name`, `relation`, `input_relation`, `operation`, and `changed`. Applies only to confirmed source and target entities. It writes `source: user,status: confirmed,evidence: []`; existing candidate edges are promoted instead of duplicated.
- `--stats` data contains: `total_entities`, `by_type{}`, `total_aliases`, `total_relationships`, `top_referenced[]`, `top_cooccurrence[]`.
- `--check` data contains: `total_entities`, `issues[]`, `summary{}`.

#### Error Behavior / Error Codes

**Known deviations**: `entity` error handling is inconsistent across subcommands.

- Most read subcommands (`--audit`, `--stats`, `--check`, `--review`) use the standard `{success, data, error}` envelope with `error: null` on success.
- `--unmerge` and `--review --action ...` return a **flat shape** without a `data` wrapper — this is a documented deviation from the standard envelope.
- `--resolve` returns `error` as a **plain string** (e.g., `"Entity not found"`) instead of a structured error object with `code`/`message`/`recovery_strategy`.
- Parser errors (missing required flags) raise `SystemExit` with a plain text message, not a JSON error envelope.
- Runtime alignment to the unified error format is deferred to a post-M16 milestone.

#### schema_version Policy

`entity` emits a top-level `schema_version` field set to `"v1.1.1"`. Subcommand output shapes are stable; new fields in `data` objects may be added without a version bump. A `schema_version` bump will accompany any backward-incompatible change.

<!-- /M16-CONTRACT -->

### 端点

```bash
python -m tools.entity [options]
python -m tools.entity build --from-journals --preview --json
python -m tools.entity build --from-batch batch.yaml --preview --json
python -m tools.entity build --from-batch batch.yaml --apply --json
python -m tools.entity profile --id ENTITY_ID --json
python -m tools.entity profile --name NAME --json
python -m tools.entity audit --json
python -m tools.entity maintain --normalize --preview --json
python -m tools.entity maintain --normalize --apply --backup --json
python -m tools.entity maintain --delete --id ENTITY_ID --preview --json
python -m tools.entity maintain --delete --id ENTITY_ID --apply --backup --json
python -m tools.entity maintain --add-relationship --id SOURCE_ID --target-id TARGET_ID --relation RELATION --preview --json
python -m tools.entity maintain --add-relationship --id SOURCE_ID --target-id TARGET_ID --relation RELATION --apply --json
python -m tools.entity --set-self --id ENTITY_ID --json
python -m tools.entity --unset-self --json
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `build --from-journals --preview --json` | subcommand | ❌ | - | 预览 journal frontmatter 冷启动候选，零写入 |
| `build --from-batch FILE --preview --json` | subcommand | ❌ | - | 预览用户确认批量实体/关系导入，零写入 |
| `build --from-batch FILE --apply --json` | subcommand | ❌ | - | 应用用户确认批量实体/关系导入；委托 `--apply-batch` |
| `profile --id ENTITY_ID --json` | subcommand | ❌ | - | 装配 confirmed 实体档案，按稳定 ID 选择 |
| `profile --name NAME --json` | subcommand | ❌ | - | 装配 confirmed 实体档案；名称必须唯一，否则 fail-closed 返回候选 |
| `audit --json` | subcommand | ❌ | - | 聚合 `--check` / `--audit` / `--stats` 的只读健康 facade |
| `maintain --normalize --preview --json` | subcommand | ❌ | - | 预览旧实体类型到 `type` + `attributes.kind` 的迁移计划，零写入 |
| `maintain --normalize --apply --backup --json` | subcommand | ❌ | - | 应用 deterministic normalize plan；必须创建 `entity_graph.yaml.backup_*` |
| `maintain --delete --id ENTITY_ID --preview --json` | subcommand | ❌ | - | 预览实体删除影响，零写入 |
| `maintain --delete --id ENTITY_ID --apply --backup --json` | subcommand | ❌ | - | 删除实体并清理引用；必须创建 `entity_graph.yaml.backup_*` |
| `--list` | flag | ❌ | false | 列出实体图谱中的所有实体 |
| `--type` | string | ❌ | - | 按当前类型过滤（`actor`, `artifact`, `place`, `project`, `event`, `concept`） |
| `--add` | string | ❌ | - | 添加新实体（JSON 格式） |
| `--resolve` | string | ❌ | - | 解析实体名称歧义 |
| `--audit` | flag | ❌ | false | 执行实体质量审计 |
| `--stats` | flag | ❌ | false | 输出图谱统计 |
| `--check` | flag | ❌ | false | 执行图谱完整性检查 |
| `--review` | flag | ❌ | false | 打开 Review Hub（风险优先审订队列） |
| `--unmerge` | flag | ❌ | false | 按 merge 墓碑复原实体（需 `--id` 和 `--target-id`） |
| `--propose` | string | ❌ | - | 宿主 agent 提交实体/关系假设（JSON），只写 `status=candidate` |
| `--apply-batch` | string | ❌ | - | 应用用户确认后的 JSON/YAML 批量实体/关系文件 |
| `--set-self` | flag | ❌ | false | 将 `--id` 指定的 confirmed 实体设为唯一 self 锚点；显式用户判决写路径 |
| `--unset-self` | flag | ❌ | false | 撤销当前 self 锚点，不删除实体 |
| `--preview` | flag | ❌ | false | 仅预览影响，不修改图谱（配合 `maintain --delete` / `maintain --add-relationship` / `--apply-batch` / `--review --action preview`） |
| `--id` | string | 条件必填 | - | 源实体 ID |
| `--target-id` | string | 条件必填 | - | 目标实体 ID（用于 merge） |
| `--relation` | string | 条件必填 | - | `maintain --add-relationship` 或 `--review --action add_relationship` 的关系类型 |
| `--add-alias` | string | ❌ | - | 为实体添加别名（需 `--id`） |
| `--action` | enum | ❌ | - | `merge_as_alias` / `add_relationship` / `confirm_candidate` / `reject_candidate` / `keep_separate` / `undo_keep_separate` / `skip` / `preview` |
| `--export` | enum | ❌ | - | 导出格式：`csv` / `xlsx`（配合 `--review`） |
| `--import` | string | ❌ | - | 从文件导入审订结果（配合 `--review`） |
| `--output` | string | ❌ | - | 指定输出文件路径（配合 `--review --export`） |

#### Retired top-level primitives

Owner decision on 2026-07-05: Life Index has no historical install base that
depends on these top-level flags, so the compatibility-demotion plan was
replaced by a clean cutover. Calls return `ENTITY_PRIMITIVE_REMOVED` with a
replacement command.

| Retired flag | Replacement |
|---|---|
| `--seed` | `entity build --from-journals --preview --json`, then user-authorized batch/review apply |
| `--update` | `entity --add-alias ALIAS --id ENTITY_ID` |
| `--merge` | `entity --review --action preview`, then `entity --review --action merge_as_alias` |
| `--delete` | `entity maintain --delete --id ENTITY_ID --preview --json`, then `entity maintain --delete --id ENTITY_ID --apply --backup --json` |

### 主要操作模式

#### `entity profile`

只读装配 confirmed 实体档案，用于回答“关于某人/某项目/某实体”的问题时先取
结构化上下文，再按 `mentions` 指针下钻日志。输入可用稳定 ID，或唯一名称/alias。
名称歧义时不会猜测；candidate 实体不会生成 confirmed profile。

```bash
life-index entity profile --id actor-alice --json
life-index entity profile --name Alice --json
```

若需要给宿主 agent 一个可直接阅读的持久档案目录，运行：

```bash
life-index abstract --entities --json
```

该命令将 `entity profile` 的 confirmed-only 装配结果确定性渲染到
`Entities/index.md` 和 `Entities/<entity_id>.md`，并在根 `INDEX.md` 加入口。
这些文件是派生视图；编辑它们不会回流到 `entity_graph.yaml`。

返回（标准 envelope）：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.x",
    "generated_at": "2026-07-06T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "identity": {
      "entity_id": "actor-alice",
      "primary_name": "Alice",
      "aliases": ["Ally"],
      "type": "actor",
      "kind": "human",
      "status": "confirmed",
      "is_self": true
    },
    "relationships": [
      {
        "target": "actor-bob",
        "target_name": "Bob",
        "relation": "friend_of",
        "source": "user",
        "created_at": "2026-07-01T00:00:00+00:00",
        "status": "confirmed",
        "evidence": ["Journals/2026/03/life-index_2026-03-15_001.md"]
      }
    ],
    "mentions": [
      {
        "rel_path": "Journals/2026/03/life-index_2026-03-15_001.md",
        "date": "2026-03-15",
        "title": "Primary Mention"
      }
    ],
    "evidence": ["Journals/2026/03/life-index_2026-03-15_001.md"],
    "stats": {
      "first_mention": "2026-03-15",
      "latest_mention": "2026-03-15",
      "mention_count": 1,
      "relationship_count": 1
    }
  },
  "error": null
}
```

`mentions` scans the FTS index for the entity primary name and aliases, returns
at most 20 journal pointers, and sorts newest first. `relationships` includes
confirmed outgoing edges whose target entity is also confirmed; candidate
entities or candidate edges are excluded.

#### `entity audit --json`

聚合结构检查、质量审计与统计信息，给宿主 agent 一个低认知负担的只读健康入口：

```bash
life-index entity audit --json
```

返回（标准 envelope）：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.x",
    "generated_at": "2026-07-05T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "workflow": "audit",
    "traffic_light": "yellow",
    "pending_count": 1,
    "structural_issue_count": 0,
    "quality_issue_count": 1,
    "duplicate_count": 0,
    "next_step": {
      "command": "life-index entity --review",
      "reason": "pending entity review items"
    },
    "components": {
      "check": {"total_entities": 2, "issues": [], "summary": {}},
      "audit": {"audit_date": "2026-07-05", "summary": {}, "issues": [], "facts": {}},
      "stats": {"total_entities": 2, "by_type": {"actor": 2}}
    },
    "component_errors": {}
  },
  "error": null
}
```

`traffic_light` is `green` when no pending or structural item needs attention,
`yellow` when there are pending review/quality items, and `red` when structural
or duplicate confirmed-entity issues require review. If the graph is malformed,
the facade still returns a red payload from `--check`; failing subcomponents are
reported in `component_errors` instead of crashing.

#### `entity build --from-batch`

用户已确认的结构化实体/关系批量录入 workflow facade。该入口复用
`entity --apply-batch` 原语；返回 shape 与 `--apply-batch` 保持一致。

```bash
life-index entity build --from-batch batch.yaml --preview --json
life-index entity build --from-batch batch.yaml --apply --json
```

返回（标准 envelope）：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.x",
    "generated_at": "2026-07-05T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "preview": true,
    "new_entities": 2,
    "new_relationships": 1,
    "conflicts": 0,
    "duplicates_skipped": 0,
    "conflict_items": []
  },
  "error": null
}
```

`--preview` is read-only. `--apply` writes the same confirmed graph changes as
`entity --apply-batch FILE`. Exactly one of `--preview` or `--apply` is required.
Name conflicts are not merged automatically; they are routed into the review
queue by the underlying batch primitive.

#### `entity build --from-journals`

从 journal frontmatter 生成冷启动候选计划。该 facade 当前只支持
`--preview`，用于替代旧的直接冷启动写盘入口。

```bash
life-index entity build --from-journals --preview --json
```

返回（标准 envelope）：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.x",
    "generated_at": "2026-07-05T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "preview": true,
    "source": "journals",
    "new_entities": 3,
    "added": [
      {"id": "seed_actor_alice", "primary_name": "Alice", "type": "actor", "attributes": {"kind": "human"}, "frequency": 2}
    ],
    "skipped_existing": [],
    "skipped_low_frequency": []
  },
  "error": null
}
```

`--preview` is read-only. `--apply` is intentionally unsupported for
`--from-journals`; confirmed graph writes still require user judgment through
batch authorization, review actions, or explicit advanced primitives.

#### `entity maintain --normalize`

预览或应用实体类型归一化计划。该 facade 用于从旧的
旧 `person` 图谱迁移到稳定 L1 `type` + 开放 `attributes.kind`。
普通图谱加载会对 `type: person` fail-closed 并指向本命令；该 facade 的
专用 loader 会容忍旧类型以便生成迁移计划。它不重建图谱、不改 entity ID；关系、
alias、证据、source/status/created_at、merge tombstone 与
`not_duplicate_of` 记录必须保留。

```bash
life-index entity maintain --normalize --preview --json
life-index entity maintain --normalize --apply --backup --json
```

返回（标准 envelope）：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.x",
    "generated_at": "2026-07-05T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "workflow": "maintain.normalize",
    "preview": true,
    "applied": false,
    "summary": {
      "entity_count": 4,
      "change_count": 3,
      "review_question_count": 0
    },
    "changes": [
      {
        "entity_id": "person-alice",
        "primary_name": "Alice",
        "from": {"type": "person", "kind": null},
        "to": {"type": "actor", "kind": "human"},
        "reason": "person entity maps to actor/human"
      }
    ],
    "review_questions": [],
    "backup_path": null
  },
  "error": null
}
```

`--preview` is read-only. `--apply` requires `--backup`; the backup is written
next to `entity_graph.yaml` as `entity_graph.yaml.backup_*` before the atomic
replacement. Ambiguous mappings are reported in `review_questions` instead of
being rewritten.

#### `entity --audit`

执行实体质量审计：

```bash
life-index entity --audit --json
```

返回（标准 envelope）：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "audit_date": "2026-04-09",
    "total_entities": 42,
    "issues": [
      {
        "type": "possible_duplicate",
        "severity": "high",
        "entities": ["Morgan A", "Morgan"],
        "entity_ids": ["p001", "p002"],
        "entity_refs": [
          {"entity_id": "p001", "primary_name": "Morgan A"},
          {"entity_id": "p002", "primary_name": "Morgan"}
        ],
        "confidence": 0.9,
        "evidence": "alias overlap: ...",
        "suggested_action": "merge"
      },
      {
        "type": "candidate_entity",
        "severity": "low",
        "entity_id": "p003",
        "entity_ids": ["p003"],
        "entity_refs": [{"entity_id": "p003", "primary_name": "Morgan"}],
        "primary_name": "Morgan",
        "message": "Candidate entity 'Morgan' awaits human review",
        "why": "human review required before confirmation: repeated unknown person mention",
        "evidence_paths": ["Journals/2026/07/life-index_2026-07-02_001.md"],
        "suggested_action": "review"
      }
    ],
    "summary": {"high": 1, "medium": 0, "low": 1},
    "facts": {
      "zero_journal_reference_entities": [
        {"entity_id": "p004", "primary_name": "Alice"}
      ]
    },
    "fact_annotations": {
      "zero_journal_reference_entities": {
        "classification": "neutral_fact",
        "is_issue": false,
        "message": "Zero journal references are neutral facts for observability, not an issue and not an action recommendation."
      }
    }
  },
  "workflow_hint": {
    "workflow": "audit",
    "preferred_command": "life-index entity audit --json",
    "reason": "Use the audit workflow facade for graph health; --audit is a low-level quality component."
  },
  "error": null
}
```

`zero_journal_reference_entities` is a neutral fact for observability. A
`source=user,status=confirmed` entity or relationship with `evidence=[]` is
healthy and is not an action recommendation. Questions enter review as
`candidate_entity` or `candidate_relationship` with `suggested_action: "review"`.
Pairs marked with `not_duplicate_of[]` by `keep_separate` are user judgments
and are not reported again as `possible_duplicate` unless that mark is undone.

#### `entity --stats`

输出图谱统计：

```bash
life-index entity --stats
```

返回：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "total_entities": 42,
    "by_type": {"person": 15, "place": 8, "concept": 19},
    "total_aliases": 23,
    "total_relationships": 56,
    "top_referenced": [
      {"entity_id": "p001", "primary_name": "Alice", "incoming_count": 12}
    ],
    "top_cooccurrence": [
      {
        "entities": [
          {"entity_id": "p001", "primary_name": "Alice"},
          {"entity_id": "p002", "primary_name": "Bob"}
        ],
        "cooccurrence": 5
      }
    ]
  },
  "error": null
}
```

#### `entity --check`

执行图谱完整性检查：

```bash
life-index entity --check
```

返回：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "total_entities": 42,
    "issues": [
      {
        "type": "dangling_relationship",
        "severity": "high",
        "entity_id": "p001",
        "target": "p999",
        "relation": "friend",
        "description": "Entity p001 references non-existent target p999"
      },
      {
        "type": "duplicate_lookup",
        "severity": "medium",
        "name": "小明",
        "entity_ids": ["p001", "p002"],
        "description": "Name '小明' resolves to multiple entities: ['p001', 'p002']"
      }
    ],
    "summary": {
      "dangling_relationships": 1,
      "duplicate_lookups": 1,
      "schema_issues": 0
    }
  },
  "error": null
}
```

#### `entity --review`

打开 Review Hub，返回风险优先审订队列：

```bash
life-index entity --review
```

返回：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "queue": [
      {
        "item_id": "review-1",
        "risk_level": "high",
        "category": "possible_duplicate",
        "description": "alias overlap: ...",
        "action_choices": [
          {
            "action": "merge_as_alias",
            "source_id": "p001",
            "target_id": "p002",
            "relation": null,
            "evidence": [],
            "preview_required": true,
            "label": "Same",
            "description": "Preview merging the source entity into the target entity as aliases."
          },
          {
            "action": "keep_separate",
            "source_id": "p001",
            "target_id": "p002",
            "relation": null,
            "evidence": [],
            "preview_required": true,
            "label": "Different",
            "description": "Persist a user-confirmed non-duplicate decision."
          },
          {
            "action": "skip",
            "source_id": "p001",
            "target_id": "p002",
            "relation": null,
            "evidence": [],
            "preview_required": false,
            "label": "Not-sure",
            "description": "Leave the item unchanged for later review."
          }
        ],
        "action_names": ["merge_as_alias", "keep_separate", "skip"],
        "source_id": "p001",
        "target_id": "p002",
        "entity_ids": ["p001", "p002"],
        "why": "alias overlap: ...",
        "evidence": [],
        "suggested_action": "merge"
      }
    ],
    "total": 1
  },
  "error": null
}
```

Queue items include `why`, `evidence`, and structured `action_choices`.
Each action choice is the GUI/host-agent payload: `action`, `source_id`,
`target_id`, `relation`, `evidence`, and `preview_required`. `action_names`
is a compatibility summary only; consumers that preview/apply should use the
structured `action_choices[]` payload.

Preview a specific review action with the queue item id and action payload:

```bash
life-index entity --review --action preview --review-action merge_as_alias --id review-1 --source-id p001 --target-id p002 --json
life-index entity --review --action preview --review-action keep_separate --id review-1 --source-id p001 --target-id p002 --json
life-index entity --review --action preview --review-action add_relationship --id review-2 --source-id p001 --target-id p002 --relation friend_of --json
```

Apply only after user judgment:

```bash
life-index entity --review --action merge_as_alias --id review-1 --source-id p001 --target-id p002 --json
life-index entity --review --action keep_separate --id review-1 --source-id p001 --target-id p002 --json
life-index entity --review --action confirm_candidate --id review-3 --source-id person-morgan --json
life-index entity --review --action reject_candidate --id review-3 --source-id person-morgan --json
life-index entity --review --action confirm_candidate --id review-4 --source-id person-alice --target-id person-bob --relation friend_of --json
life-index entity --review --action undo_keep_separate --id review-5 --source-id person-alan --target-id person-alen --json
```

For backwards compatibility, older calls that pass the source entity through
`--id` without `--source-id` still work. New GUI and host-agent integrations
should treat `--id` as the review item id and pass `--source-id` explicitly.

Confirming an entity candidate changes it to `status: confirmed`; confirming a
relationship candidate changes that edge to `status: confirmed`. Rejecting
removes only the candidate entity or edge. `keep_separate` writes symmetric
`not_duplicate_of[]` records with `source: user` and `created_at` so audit
respects the user's non-duplicate decision. `undo_keep_separate` removes that
mark and lets future audit runs report the pair again if it still matches a
duplicate heuristic.

#### `entity --propose`

Host agents can persist a hypothesis as a candidate. This is the agent lane of
the candidate pool and never writes confirmed graph state:

```bash
life-index entity --propose '{"kind":"entity","id":"actor-morgan","entity_type":"actor","primary_name":"Morgan","attributes":{"kind":"human"},"reason":"Host agent saw repeated evidence.","evidence":["Journals/2026/07/life-index_2026-07-02_001.md"]}'
life-index entity --propose '{"kind":"relationship","source_id":"person-alice","target_id":"person-bob","relation":"friend_of","reason":"Host agent hypothesis.","evidence":["Journals/2026/07/life-index_2026-07-03_001.md"]}'
```

Candidates are persisted with `source: agent,status: candidate` and appear in
`entity --review`. Candidate entities and relationships do not participate in
entity expansion/search until confirmed.

The deterministic write lane also promotes repeated unknown
actor/place/project frontmatter values into `source: seed,status: candidate`
after `LIFE_INDEX_ENTITY_CANDIDATE_THRESHOLD` occurrences (default `2`).

#### `entity --apply-batch`

Applies a user-confirmed JSON/YAML batch file with entities and relationships.
Run preview first, then apply:

```bash
life-index entity --apply-batch batch.json --preview
life-index entity --apply-batch batch.json
```

Input shape:

```json
{
  "entities": [
    {"id": "person-alice", "type": "actor", "primary_name": "Alice", "aliases": [], "attributes": {"kind": "human"}},
    {"id": "person-bob", "type": "actor", "primary_name": "Bob", "aliases": [], "attributes": {"kind": "human"}}
  ],
  "relationships": [
    {"source": "person-alice", "target": "person-bob", "relation": "friend_of"}
  ]
}
```

Preview/apply data reports `new_entities`, `new_relationships`, `conflicts`,
and `duplicates_skipped`. Clean batch assertions write
`source: user,status: confirmed,evidence: []`. Name conflicts are never merged
automatically; they become `status: candidate` review items while clean rows
still apply. Invalid batches fail atomically without changing the graph. Reusing
the same batch is idempotent.

#### `entity --review --action merge_as_alias`

用户确认两实体是同一对象后，通过 review action 合并。合并前应先 preview：

```bash
life-index entity --review --action preview --id p001 --target-id p002
life-index entity --review --action merge_as_alias --id p001 --target-id p002
```

返回：

```json
{
  "success": true,
  "action": "merge_as_alias",
  "source_id": "p001",
  "target_id": "p002",
  "transferred_names": ["旧名字", "别名A"]
}
```

合并是可逆的：目标实体会保存被吸收实体的完整墓碑，包括原始
`primary_name`、`aliases`、`relationships`、合并新增 alias、转移关系和反向引用改写。

#### `entity --unmerge`

按 merge 墓碑恢复被吸收实体，并移除合并产生的 alias / 转移关系：

```bash
life-index entity --unmerge --id p001 --target-id p002
```

返回：

```json
{
  "success": true,
  "action": "unmerge",
  "restored_id": "p001",
  "target_id": "p002"
}
```

#### `entity maintain --add-relationship`

用户口头或书面确认一条自由关系事实后，使用 maintain 关系原语两段式写入 confirmed 边：

```bash
life-index entity maintain --add-relationship --id actor-alice --target-id actor-bob --relation friend_of --preview --json
life-index entity maintain --add-relationship --id actor-alice --target-id actor-bob --relation friend_of --apply --json
```

返回（标准 envelope）：

```json
{
  "success": true,
  "data": {
    "workflow": "maintain.add_relationship",
    "preview": false,
    "applied": true,
    "source_id": "actor-alice",
    "source_name": "Alice",
    "target_id": "actor-bob",
    "target_name": "Bob",
    "relation": "friend_of",
    "input_relation": "friend_of",
    "operation": "add",
    "changed": true
  },
  "error": null
}
```

规则：

- `--preview` 只读，不修改 `entity_graph.yaml`。
- `--apply` 写入 `source: user,status: confirmed,created_at,evidence: []`。
- 已存在同一 `(source_id,target_id,relation)` confirmed 边时幂等，不重复写入。
- 已存在同一 candidate 边时提升为 `source: user,status: confirmed`，保留并去重既有 `evidence`。
- source/target 必须存在且是 confirmed 实体；candidate 实体 fail-closed 并指向 `entity --review`。
- `relation` 必须在受控关系词表内。已知别名会归一到 canonical relation；未知关系不落盘。

#### `entity --review --action add_relationship`

Review 队列中已有关系候选时，Agent 可用 review action 写入 confirmed 边；工具只执行确定性写入，不判断关系真伪。用户直接确认的自由关系事实应使用 `entity maintain --add-relationship`：

```bash
life-index entity --review --action preview --id p001 --target-id p002 --relation friend_of
life-index entity --review --action add_relationship --id p001 --target-id p002 --relation friend_of
```

写入的边会带 `source: review`、`status: confirmed`、`created_at` 和 `evidence` 字段。

#### `entity maintain --delete`

删除实体必须通过 maintain facade，两段式执行：先 preview，用户确认后 apply，
并强制创建 `entity_graph.yaml.backup_*`。

```bash
life-index entity maintain --delete --id p003 --preview --json
life-index entity maintain --delete --id p003 --apply --backup --json
```

返回：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.x",
    "generated_at": "2026-07-05T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "data": {
    "workflow": "maintain.delete",
    "preview": true,
    "applied": false,
    "backup_path": null,
    "deleted_id": "p003",
    "deleted_name": "Old Contact A",
    "cleaned_refs": [
      {"entity_id": "p001", "primary_name": "Alice", "relation": "colleague"}
    ]
  },
  "error": null
}
```

#### `entity --candidate-edges`

生成候选关系边报告（只读，零生产图谱写入）。扫描 journal 中的 `people` co-occurrence、`related_entries`、wikilinks `[[X]]` 与正文共现，输出去重后的候选边 JSON。

```bash
life-index entity --candidate-edges --output=json
```

返回：

```json
{
  "success": true,
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "entity",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "candidates": [
    {
      "type": "people_cooccurrence",
      "source": "Alice",
      "target": "Bob",
      "evidence_paths": ["2026/05/life-index_2026-05-10_001.md"],
      "confidence": 0.2,
      "suggested_action": "review-required-low-confidence"
    }
  ],
  "total": 1,
  "error": null
}
```

**Candidate 字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 提取器类型：`people_cooccurrence` / `related_entry` / `wikilink` / `body_cooccurrence` |
| `source` | string | 源节点名称 |
| `target` | string | 目标节点名称 |
| `evidence_paths` | array | 支撑该候选的 journal 相对路径列表（至少 1 条） |
| `confidence` | float | 置信度 0.0–1.0，基于 evidence 数量线性计算 |
| `suggested_action` | string | 建议操作：`auto-confirm-recommended`（≥3 evidence）、`review-recommended`（2 evidence）、`review-required-low-confidence`（<2 evidence） |

**行为约束**：
- **只读**：不创建、修改或删除 `entity_graph.yaml` 或任何 journal 文件
- **确定性**：不调用 LLM，纯本地确定性扫描
- **路径隐私**：`evidence_paths` 均为相对路径，使用 `/` 分隔符

### Agent 使用约束

- **review / merge / delete 是高风险操作**，必须在调用前明确目标实体和确认策略
- `--audit` 结果中的 `suggested_action` 仅为建议，最终合并/删除决策需用户确认
- 冷启动主路径必须先 `life-index entity build --from-journals --preview --json`
- 删除主路径必须先 `life-index entity maintain --delete --id ENTITY_ID --preview --json`，确认后再 `--apply --backup`
- `--check` 应在 `--audit` 之前运行，作为快速健康检查

---

## Topic 分类定义

| Topic | 含义 | 示例场景 |
|-------|------|----------|
| `work` | 工作/职业 | 项目进展、会议、职业发展 |
| `learn` | 学习/成长 | 读书笔记、课程学习、技能提升 |
| `health` | 健康/身体 | 运动、饮食、体检、医疗 |
| `relation` | 关系/社交 | 家人、朋友、社交活动 |
| `think` | 思考/反思 | 人生感悟、决策思考、复盘 |
| `create` | 创作/产出 | 文章、代码、设计作品 |
| `life` | 生活/日常 | 日常琐事、娱乐、购物 |

---

## 配置文件

配置文件位置：`~/Documents/Life-Index/.life-index/config.yaml`

详见 [config.example.yaml](../config.example.yaml)

### 当前与安装后个性化相关的配置说明

- 用户可在 `config.yaml` 中记录 `defaults.location`
- 安装完成后，agent 仅可在用户明确要求时写入该偏好
- 但是否被当前运行时写入链路自动消费，应以实际验证结果为准；Agent 不得在未验证时声称其已生效

---

## sync-skill

### Endpoint

```bash
life-index sync-skill [--json] [--host-skill-dir <path>] [--host-home <path>] [--install] [--uninstall] [--list] [--dry-run] [--source-root <path>]
```

### Purpose

- Synchronize the current `SKILL.md` and `references/` artifacts into an existing host agent skill directory.
- Preserve custom trigger phrases already present in the target `SKILL.md`.
- Report a missing or ambiguous host skill directory as a loud, non-fatal `skipped` diagnostic with `data.delivered=false`.
- Support explicit first delivery with `--install` when the caller provides a known host target.
- List and remove Life Index-managed host agent skill artifacts without touching user data.
- Surface playbook freshness (`playbook_status`) and `CHANGELOG.md` pointer so
  upgrade agents can distinguish code changes from unchanged playbook content.

### Behavior

- Bare `sync-skill` never creates or guesses a new host skill directory.
- The command does not read, write, move, or delete journal data.
- `--host-skill-dir` must resolve to the canonical Life Index skill leaf
  `<host-home>/skills/life-index`. With `--install`, if the provided path is
  the host `skills/` parent, the command normalizes it to
  `<host-home>/skills/life-index` and emits
  `HOST_SKILL_DIR_PARENT_NORMALIZED`.
- `--install --host-home <path>` creates and syncs
  `<host-home>/skills/life-index`.
- `--install --dry-run --host-home <path>` reports the planned install and any
  nested duplicate cleanup without creating, copying, or deleting files.
- During `--install`, if a prior broken install left managed Life Index
  artifacts at `<host-home>/skills/SKILL.md` and
  `<host-home>/skills/references/`, the command installs the canonical slot
  first, then removes only those parent-level artifacts and emits
  `HOST_SKILL_DIR_PARENT_STRAY_CLEANED`. If the parent artifacts contain
  non-Life Index content or cannot be proven managed, they are preserved and
  reported with `HOST_SKILL_DIR_PARENT_STRAY_PRESERVED`.
- If `--install` is run without `--host-skill-dir` or `--host-home`, the
  command may select a missing canonical slot only when a default host home has
  provably managed 1.4.2 parent-level Life Index artifacts to recover. It does
  not guess a new host target from unmanaged parent files.
- During `--install`, if the legacy double slot
  `<host-home>/skills/life-index/life-index` contains a managed Life Index
  skill tree, the command merges its custom triggers into the canonical
  `<host-home>/skills/life-index/SKILL.md` and removes the duplicate only after
  the canonical playbook is written. Symlinks, non-directories, missing
  `SKILL.md`, or trees with extra top-level files are reported in
  `data.dedupe.skipped` and are not removed.
- If `--install` is run without `--host-skill-dir` or `--host-home`, and the
  only discovery ambiguity is the canonical slot plus its managed nested
  duplicate (`skills/life-index` and `skills/life-index/life-index`), the
  command auto-selects the canonical slot, emits
  `HOST_SKILL_DIR_NESTED_DUPLICATE_AUTOCONVERGED`, and then applies the same
  safe dedupe behavior above.
- `--list` is read-only. It enumerates discovered Life Index skill directories
  under the documented host homes (`.codex`, `.agents`, `.hermes`, `.claude`)
  and matching host-home environment variables.
- `--uninstall --host-home <path>` removes only managed Life Index skill
  directories under that explicit host home: `<host-home>/skills/life-index`
  and one-level nested `<host-home>/skills/<category>/life-index` variants.
- `--uninstall --dry-run --host-home <path>` reports matching targets without
  deleting them.
- `--uninstall` without explicit `--host-home` is refused. The command never
  deletes the host home, parent `skills/` directory, source checkouts, pip
  packages, data directories, journals, or non-matching paths.
- If `--host-skill-dir` is omitted, the command checks the documented host skill
  directory environment and default locations, including flat
  `skills/life-index` and one-level nested `skills/<category>/life-index`
  layouts.
- If multiple unrelated host skill directories are found, or if the nested
  duplicate contains unmanaged top-level content, the command does not guess;
  it reports all matches and requires `--host-skill-dir`.
- `--source-root` defaults to the current installed checkout root, falling back
  to packaged wheel skill artifacts when no checkout root is present.

### JSON contract

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "synced",
    "delivered": true,
    "target_dir": "<host-skill-dir>",
    "copied": [
      "SKILL.md",
      "references/GROUNDED_QUERY_PLAYBOOK.md",
      "references/WEATHER_FLOW.md"
    ],
    "playbook_status": "updated",
    "changelog": "CHANGELOG.md",
    "dedupe": {
      "status": "not_applicable",
      "nested_dir": null,
      "removed": [],
      "skipped": []
    },
    "diagnostics": []
  }
}
```

When `--install` creates the target skill directory, `data.status` is
`"installed"` and `data.delivered` is `true`:

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "installed",
    "delivered": true,
    "target_dir": "<host-home>/skills/life-index",
    "copied": [
      "SKILL.md",
      "references/GROUNDED_QUERY_PLAYBOOK.md",
      "references/WEATHER_FLOW.md"
    ],
    "playbook_status": "installed",
    "changelog": "CHANGELOG.md",
    "dedupe": {
      "status": "not_applicable",
      "nested_dir": null,
      "removed": [],
      "skipped": []
    },
    "diagnostics": []
  }
}
```

When `--install --dry-run` previews an install or nested cleanup, no files are
created, copied, or removed:

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "dry_run",
    "delivered": false,
    "target_dir": "<host-home>/skills/life-index",
    "copied": [],
    "playbook_status": "would_install",
    "changelog": "CHANGELOG.md",
    "dedupe": {
      "status": "would_remove",
      "nested_dir": "<host-home>/skills/life-index/life-index",
      "removed": [],
      "skipped": []
    },
    "diagnostics": []
  }
}
```

When `--install` auto-converges a managed nested duplicate discovered without
an explicit target, `data.target_dir` is the canonical single-level slot and
`data.diagnostics` records the convergence:

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "synced",
    "delivered": true,
    "target_dir": "<host-home>/skills/life-index",
    "copied": [
      "SKILL.md",
      "references/GROUNDED_QUERY_PLAYBOOK.md",
      "references/WEATHER_FLOW.md"
    ],
    "playbook_status": "updated",
    "changelog": "CHANGELOG.md",
    "dedupe": {
      "status": "removed",
      "nested_dir": "<host-home>/skills/life-index/life-index",
      "removed": ["<host-home>/skills/life-index/life-index"],
      "skipped": []
    },
    "diagnostics": [
      {
        "code": "HOST_SKILL_DIR_NESTED_DUPLICATE_AUTOCONVERGED",
        "message": "Managed nested Life Index skill duplicate found; using canonical host skill directory <host-home>/skills/life-index and converging nested duplicate <host-home>/skills/life-index/life-index."
      }
    ]
  }
}
```

When no host skill directory is available:

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "skipped",
    "delivered": false,
    "target_dir": null,
    "copied": [],
    "playbook_status": "not_delivered",
    "changelog": "CHANGELOG.md",
    "dedupe": {
      "status": "not_applicable",
      "nested_dir": null,
      "removed": [],
      "skipped": []
    },
    "diagnostics": [
      {
        "code": "HOST_SKILL_DIR_NOT_FOUND",
        "message": "No existing host skill directory was found; skill artifact sync was not delivered. Checked: <candidate-list>"
      }
    ]
  }
}
```

`success=true` with `data.delivered=false` means the command completed but the
host agent playbook was not updated. Onboarding and upgrade chains must surface
that diagnostic instead of treating it as a completed delivery.

Listing discovered agent skill artifacts:

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "listed",
    "action": "list",
    "discovered": ["<host-home>/skills/life-index"],
    "removed": [],
    "skipped": [],
    "diagnostics": []
  }
}
```

Uninstalling managed agent skill artifacts:

```json
{
  "success": true,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "uninstalled",
    "action": "uninstall",
    "host_home": "<host-home>",
    "dry_run": false,
    "removed": ["<host-home>/skills/life-index"],
    "skipped": [],
    "diagnostics": []
  }
}
```

If no explicit host home is supplied for uninstall, the command fails closed:

```json
{
  "success": false,
  "schema_version": "m35.sync_skill.v0",
  "command": "sync-skill",
  "data": {
    "status": "refused",
    "action": "uninstall",
    "host_home": null,
    "dry_run": false,
    "removed": [],
    "skipped": [],
    "diagnostics": [
      {
        "code": "UNINSTALL_REQUIRES_HOST_HOME",
        "message": "--uninstall requires explicit --host-home; no data, clone, or package paths are inferred."
      }
    ]
  }
}
```

---

## CLI version / bootstrap authority

### 端点

```bash
life-index --version
life-index version
```

### 用途

- 暴露当前已安装 package version
- 暴露当前 checkout 所携带的 `bootstrap-manifest.json`
- 供 onboarding / upgrade / repair 流程做 freshness gate 使用

### 返回值

```json
{
  "package_version": "<package-version-from-pyproject>",
  "bootstrap_manifest": {
    "repo_version": "<repo-version-from-bootstrap-manifest>",
    "onboarding_schema_version": "2.0",
    "manifest_schema": 1,
    "requires_checkout_sync": true,
    "target_ref": "main",
    "release_channel": "stable",
    "required_authority_docs": [
      "bootstrap-manifest.json",
      "CHARTER.md",
      "AGENT_ONBOARDING.md",
      "SKILL.md",
      "docs/API.md",
      "docs/ARCHITECTURE.md",
      "docs/ENTITY_GRAPH.md",
      "docs/VERSIONING.md",
      "tools/lib/AGENTS.md",
      "README.md"
    ],
    "skill_artifacts": [
      "SKILL.md",
      "references/"
    ]
  }
}
```

### 说明

- `package_version` mirrors `pyproject.toml` `[project].version`
- `bootstrap_manifest.repo_version` mirrors `bootstrap-manifest.json`
- Formal releases require those two values to match
- `life-index health` 会在 `data.upgrade_freshness` 暴露会话可见的本地
  freshness 信号（installed/manifest mismatch、checkout vs upstream ref）。
- `life-index --version` 仍用于 authority/version 校验；已有程序升级使用
  `life-index upgrade --plan --json`，`bootstrap --json` 只负责首次安装、repair
  与单独授权的数据生命周期规划。
- onboarding agent 不得用 `health` 替代 `bootstrap --json` / manifest
  freshness gate；health 信号只用于提醒宿主 agent 先刷新代码/playbook。

---

## Web runtime freshness fields

### `/api/health`

- `status`
- `version`
- `bootstrap_manifest`
- `runtime`

### `/api/runtime`

- `package_version`
- `bootstrap_manifest`
- `user_data_dir`
- `journals_dir`
- `life_index_data_dir_override`
- `readonly_simulation`

### 说明

- `/api/health` 与 `/api/runtime` 现在都可用于 Web onboarding / acceptance 时确认运行实例对应的 package version 与 bootstrap authority

---

## Round 6 新增能力

### `life-index migrate` — Schema 迁移工具

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--dry-run` | flag | true | 扫描并报告，不修改文件 |
| `--apply` | flag | false | 执行确定性迁移 |
| `--version` | int | latest | 目标 schema 版本 |
| `--json` | flag | true | JSON 输出 |

**dry-run 输出**：

```json
{
  "total_scanned": 42,
  "version_distribution": {"1": 5, "2": 37},
  "needs_migration": 5,
  "outdated_files": [{"path": "...", "current_version": 2, "removed_fields": ["sentiment_score", "themes"]}]
}
```

**apply 输出**：

```json
{
  "migrated_count": 5,
  "already_current": 37,
  "failed_count": 0,
  "failed_files": [],
  "needs_agent": [{"path": "...", "items": ["abstract/summary missing — needs Agent extraction"]}],
  "deterministic_changes": [{"path": "...", "changes": ["removed sentiment_score", "removed themes"]}]
}
```

> **E08xx 状态**: Reserved / 未实现。`tools/migrate/` 当前不发射结构化 E08xx 错误码；迁移失败以非结构化日志或异常形式报告。E0800–E0803 为预留编码，未来若迁移模块统一接入 `tools/lib/errors.py` 结构化错误体系时可启用。

### `life-index entity` — 实体图谱管理

Entity 管理工具在 Round 6 引入，现已成为独立一级命令。完整参数、操作模式、返回值结构和 Agent 约束见上文 `## entity` 章节。

---

## trajectory

> **Boundary SSOT.** `trajectory` owns deterministic typed observation series:
> dated field values such as weight, sleep, mood, location, or project with
> evidence paths. It does **not** own counts, buckets, denominators, lower-bound
> semantics, or claim envelopes; use `aggregate` for those. A host agent may use
> trajectory output to interpret a trend, but the interpretation belongs to the
> host agent, not this tool.

### 端点

```bash
life-index trajectory --field {weight|sleep|mood|location|project} --range YYYY-MM..YYYY-MM
python -m tools trajectory --field weight --range 2025-01..2025-12
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| field | enum | ✅ | - | 提取字段: `weight`, `sleep`, `mood`, `location`, `project` |
| range | string | ✅ | - | 月份范围 `YYYY-MM..YYYY-MM` (含起止) |

### 返回值

```json
{
  "success": true,
  "command": "trajectory",
  "schema_version": "v1.1.1",
  "provenance": {
    "source_hash": "sha256:...",
    "tool_version": "1.1.1",
    "generated_at": "2026-05-23T10:00:00+00:00",
    "generator": "trajectory",
    "params_hash": "sha256:...",
    "fixture_version": null
  },
  "field": "weight",
  "range": ["2025-01", "2025-12"],
  "observations": [
    {
      "type": "weight",
      "value": 72.5,
      "time": "2025-01-15",
      "evidence_paths": ["Journals/2025/01/life-index_2025-01-15_001.md"]
    }
  ],
  "total": 1,
  "performance": {
    "files_scanned": 12,
    "total_time_ms": 15
  },
  "error": null
}
```

### 字段语义

- `observations`: 按时间升序排列的 typed observation 列表。
- `observations[].type`: 与 `--field` 一致。
- `observations[].value`: 提取值。`weight`/`sleep` 为数值; `mood`/`location`/`project` 为字符串。
- `observations[].time`: 来源日志的 `date` 字段 (YYYY-MM-DD)。
- `observations[].evidence_paths`: 指向来源日志文件的路径数组（相对 `LIFE_INDEX_DATA_DIR`）。
- `performance.files_scanned`: L2 `search` 返回并被 trajectory 处理的候选日志条目数；不是 trajectory 直接文件系统扫描计数。
- **只读语义**: 本命令不写入、不修改任何 L1 frontmatter 或 journal 文件。

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E2601 | 无效 field | ask_user |
| E2602 | 无效 range 格式 | ask_user |

### 说明

- `trajectory` 是确定性的 typed-observation extractor，通过 L2 `search` CLI 子进程读取候选日志内容；不直接扫描 `Journals/**`，不直接读写 L1 文件。
- 各 field 的提取策略：
  - `weight`: frontmatter `weight_kg` + 正文 `体重: XX.X kg` / `weight XX.X kg` 模式。
  - `sleep`: frontmatter `sleep_hours` + 正文 `睡了 X 小时` / `slept X hours` 模式。
  - `mood`: frontmatter `mood` 列表 + 正文 emoji 与描述词。
  - `location`: frontmatter `location` + 正文 `在 XX` / `in/at XX` 模式。
  - `project`: frontmatter `project` + tags + 正文项目名模式。
- 默认路径无 LLM 调用，全部确定性提取。
- 支持 `LIFE_INDEX_DATA_DIR` 环境变量覆盖数据目录。

---

## ACP Env Allowlist (agent bridge)

`LIFE_INDEX_ACP_ENV_ALLOWLIST` 控制哪些父进程环境变量会被传递到 ACP 子进程中。

### 安全姿态

**零配置已知 provider key 穿透**：11 个主流 LLM provider 的标准 API key 环境变量（`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY`、`KIMI_API_KEY`、`GEMINI_API_KEY`、`AZURE_OPENAI_API_KEY`、`COHERE_API_KEY`、`MISTRAL_API_KEY`、`GROQ_API_KEY`、`TOGETHER_API_KEY`、`REPLICATE_API_KEY`）默认穿透到 ACP 子进程，**无需**设置 `LIFE_INDEX_ACP_ENV_ALLOWLIST`。

**Life Index 自身密钥永不外泄**：`LIFE_INDEX_LLM_API_KEY` 属于 Life Index 自身，不属于任何 runtime provider。该密钥**始终**被剥离，即使用户尝试将其放入 allowlist。ACP 运行时不应依赖 Life Index 的密钥。

**非已知 provider 凭据默认剥离**：所有凭据样式的环境变量（名称以 `_API_KEY` / `_TOKEN` 结尾，或包含 `SECRET` / `PASSWORD`）默认被剥离，除非该变量属于已知 runtime provider 集合或通过 allowlist 显式放行。

**显式 allowlist 作为 fallback**：对于不在已知 provider 集合中的新 provider key（如 `FOO_API_KEY`），可通过 `LIFE_INDEX_ACP_ENV_ALLOWLIST` 显式放行。

### 配置方式

**零配置**（推荐）：已知 provider key 自动穿透，无需任何配置。

**显式 allowlist**（新 provider 场景）：设置 `LIFE_INDEX_ACP_ENV_ALLOWLIST` 环境变量。

#### 对象格式（兼容旧版本）

```json
{"MY_VAR": "value", "ANOTHER": "other"}
```

直接指定 key-value 对，值由调用方提供。

#### 列表格式（新增）

```json
["FOO_API_KEY", "CUSTOM_VAR"]
```

每个 key 的值从当前进程环境（`os.environ`）中自动解析。若 key 在当前环境中不存在，则静默跳过。**不会在日志中输出解析后的值。**

### 行为契约

| 场景 | 结果 |
|------|------|
| 已知 provider key（如 `DEEPSEEK_API_KEY`）存在 | 默认穿透到 ACP 子进程（零配置） |
| `LIFE_INDEX_LLM_API_KEY` 存在 | **始终剥离**（即使被 allowlist） |
| 已知 provider key（如 `OPENAI_API_KEY`）从 allowlist 中排除 | 仍然穿透（已知 provider 不受 allowlist 影响） |
| 新 provider key（如 `FOO_API_KEY`）未 allowlist | 剥离（非已知 provider，无 allowlist） |
| 新 provider key（如 `FOO_API_KEY`）被 allowlist | 穿透（显式放行生效） |
| 非凭据变量（如 `CUSTOM_CONFIG`）被 allowlist | 正常传递 |
| 凭据样式变量（如 `FAKE_TOKEN`、`MY_SECRET`） | 始终剥离（除非是已知 provider 或被 allowlist） |

---

### Response: `events` 字段

所有 CLI 命令的 JSON 响应均可包含 `events` 字段（搭便车事件通知）。

| 事件类型 | 触发条件 | 严重级 |
|---------|---------|--------|
| `no_journal_streak` | 连续 7+ 天未记日志 | info |
| `monthly_review_due` | 有日志月份缺少生成的 `index_YYYY-MM.md`；事件给出 `life-index abstract --month YYYY-MM` | info |
| `entity_audit_due` | entity_graph.yaml 30+ 天未修改 | low |
| `entity_profiles_stale` | `Entities/index.md` 缺失或其 `source_hash` 与当前 `entity_graph.yaml` 不一致；事件给出 `life-index abstract --entities` | info |
| `schema_migration_available` | 存在旧 schema 版本日志 | info |
| `index_stale` | 日志比索引更新 | low |

### Response: `_trace` 字段

运行时诊断数据（下划线前缀表示内部字段）。

```json
{
  "_trace": {
    "trace_id": "a1b2c3d4",
    "command": "write",
    "total_ms": 1823.5,
    "steps": [
      {"step": "write_journal", "ms": 1340.2, "status": "ok"},
      {"step": "auto_index", "ms": 483.3, "status": "ok", "detail": "FTS/index metadata refreshed"}
    ]
  }
}
```
- agent 仍需区分：runtime health ≠ checkout freshness；但 runtime API 现在会显式暴露 freshness 相关元数据
