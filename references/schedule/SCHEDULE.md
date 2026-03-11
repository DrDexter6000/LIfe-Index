# Life Index 定时任务指南

> **权威文档**：定义基础概念、核心约束、原则规范，并导航至各场景文档。
> **版本**：v2.1 | **更新**：2026-03-11
---

## 一、核心约束

| 约束 | 说明 |
|------|------|
| **Cron 能力** | 仅使用 Agent 内置 Cron，禁止 OS 级别定时任务 |
| **时区** | 所有时间使用用户本地时区，非 UTC |
| **默认行为** | "无数据则跳过" 是所有报告任务的默认行为 |

---

## 二、基础概念

### 2.1 触发词三级制

| 类型 | 触发条件 | 行为 |
|------|---------|------|
| **Immediate** | 系统时间到达 + 数据条件满足 | 自动执行，无需确认 |
| **Manual** | 用户明确请求（触发词匹配） | 执行，可选确认 |
| **Soft** | 用户间接提及 | 询问用户，等待确认 |

### 2.2 STOP 点机制

```
⛔ STOP = 前置检查 + 后置记录
```

**应用场景**：
- 推送消息前：验证报告内容完整性
- 保存文件前：验证路径和格式
- 执行关键工具前：确认参数

### 2.3 Token 预算制

| 报告类型 | Token 预算 | 说明 |
|---------|-----------|------|
| 日报 | ~200 | 轻量级，快速阅读 |
| 周报 | ~500 | 中等规模，含热点 |
| 月报 | ~1000 | 详细报告，保存文件 |
| 年报 | ~3000 | 深度分析，多维度 |

---

## 三、任务清单

### 3.1 报告类任务

| 任务 | 执行时间 | Token 预算 | 输出 | 场景文档 |
|------|---------|-----------|------|---------|
| **日报** | 每天 22:00 | ~200 | 推送（主会话+IM渠道） | [daily-report.md](./scenarios/daily-report.md) |
| **周报** | 每周日 22:10 | ~500 | 推送（主会话+IM渠道） | [weekly-report.md](./scenarios/weekly-report.md) |
| **月报** | 每月末 18:30 | ~1000 | 文件+推送 | [monthly-report.md](./scenarios/monthly-report.md) |
| **年报** | 12月31日 19:15 | ~3000 | 文件+推送 | [yearly-report.md](./scenarios/yearly-report.md) |
### 3.2 索引类任务

| 任务 | 执行时间 | 说明 | 场景文档 |
|------|---------|------|---------|
| **每日索引维护** | 每天 23:50 | 检查一致性 + 修复（如需） + 向量增量 | [index-update.md](./scenarios/index-update.md) |
| **每月索引维护** | 每月1日 03:30 | 全量检查 + 重建（如需） + 向量全量 | [index-rebuild.md](./scenarios/index-rebuild.md) |
---

## 四、场景导航

**根据当前场景，阅读对应的详细文档**：

### 4.1 报告生成场景

```
用户说："生成日报" / "daily report" / "今日总结"
  → 阅读 [daily-report.md](./scenarios/daily-report.md)
用户说："生成周报" / "weekly report" / "本周总结"
  → 阅读 [weekly-report.md](./scenarios/weekly-report.md)
用户说："生成月报" / "monthly report"
  → 阅读 [monthly-report.md](./scenarios/monthly-report.md)
用户说："生成年报" / "yearly report" / "年度总结"
  → 阅读 [yearly-report.md](./scenarios/yearly-report.md)

### 4.2 索引维护场景

```
到达 23:50（索引增量更新时间）
  → 阅读 [index-update.md](./scenarios/index-update.md)
到达 03:30（每月1日，索引全量重建时间）
  → 阅读 [index-rebuild.md](./scenarios/index-rebuild.md)

---

## 五、工具速查

| 工具 | 命令 | 用途 |
|------|------|------|
| **搜索日志** | `python tools/search_journals.py --date {DATE}` | 按日期检索 |
| | `python tools/search_journals.py --month {YYYY-MM}` | 按月份检索 |
| | `python tools/search_journals.py --year {YYYY}` | 按年份检索 |
| **生成摘要** | `python tools/generate_abstract.py --month {YYYY-MM}` | 月度摘要 |
| | `python tools/generate_abstract.py --year {YYYY}` | 年度摘要 |
| **索引构建** | `python tools/build_index.py` | 增量更新 |
| | `python tools/build_index.py --rebuild` | 全量重建 |

---

## 六、错误处理

| 场景 | 处理方式 | 重试策略 |
|------|---------|---------|
| 无数据 | 保留元数据占位，报告后询问用户是否补充 | 不重试 |
| API 失败 | 记录错误，使用默认值 | 下次执行重试 |
| 文件写入失败 | 先推送内容，提示检查 | 不重试 |
| 推送失败 | 保存到文件，用户上线展示 | 下次会话展示 |
| 热点获取失败 | 省略热点部分 | 不重试 |

---

## 七、文档结构

```
references/schedule/
├── SCHEDULE.md                   ← 本文档（Router）
└── scenarios/                    ← 场景文档（含输出格式）
    ├── daily-report.md           ← 日报详细指南
    ├── weekly-report.md          ← 周报详细指南
    ├── monthly-report.md         ← 月报详细指南
    ├── yearly-report.md          ← 年报详细指南
    ├── index-update.md           ← 每日索引维护指南
    └── index-rebuild.md          ← 每月索引维护指南
```
---

**文档结束**