# Life Index 定时任务设置指南

> **本文档角色**: 指导 Agent 为 Life Index 技能配置定时任务  
> **阅读对象**: AI Agent（OpenClaw / Claude Desktop / 其他支持定时任务的平台）  
> **版本**: v3.2 | **基于**: OpenClaw 官方文档 v2026.3  
> **参考**: [OpenClaw Cron Jobs 官方文档](https://openclawlab.com/en/docs/automation/cron-jobs/)

---

## Step 1: 理解任务 — 为什么需要定时任务？

### 1.1 Life Index 是什么

Life Index 是一个**个人生活日志系统**：
- 用户通过自然语言记录日常、工作、思考
- 你作为 Agent 协助记录和检索
- 日志存储在本地，支持多维度索引

### 1.2 为什么需要定时任务？

当前你能做的是**被动响应**（用户找你时才处理）。但以下场景**必须主动**：

| 场景 | 用户状态 | 定时任务价值 |
|------|---------|-------------|
| 晚间回顾 | 可能忘记查看今日记录 | 22:00 自动推送日报，主动提醒 |
| 周末总结 | 周末可能不打开应用 | 周日自动推送周报，持续追踪 |
| 月末归档 | 可能忘记生成月度摘要 | 月末自动生成并保存月报文件 |
| 搜索性能 | 用户无感知，但需要维护 | 深夜自动维护索引，保持搜索速度 |

### 1.3 你的任务

**核心目标**: 为 Life Index 配置 6 个定时任务，让用户获得"数字生活管家"体验。

**任务清单**：

| # | 任务名称 | 触发时间 | 工作内容 | 输出 |
|---|---------|---------|---------|------|
| 1 | **日报** | 每天 22:00 | 汇总今日日志，生成摘要 | 推送消息 |
| 2 | **周报** | 每周日 22:10 | 总结本周轨迹，含洞察 | 推送消息 |
| 3 | **月报** | 每月最后一天 18:30 | 深度回顾，生成摘要文件 | 文件+推送 |
| 4 | **年报** | 12月31日 19:15 | 年度人生总结 | 文件+推送 |
| 5 | **每日索引维护** | 每天 23:50 | 增量更新搜索索引 | 静默执行 |
| 6 | **每月索引重建** | 每月1日 03:30 | 全量检查+重建索引 | 静默执行 |

**Token 预算**：
- 日报: ~200 tokens
- 周报: ~500 tokens  
- 月报: ~1000 tokens
- 年报: ~3000 tokens
- 索引任务: 无输出，不计 Token

---

## Step 2: OpenClaw 定时任务参考模板

以下 6 个任务模板基于 **OpenClaw 官方文档** 和 **社区最佳实践** 编写。

### OpenClaw 定时任务核心概念

**调度类型**:
- `cron`: 标准 Cron 表达式（5字段：分 时 日 月 星期）
- `every`: 固定间隔（毫秒）
- `at`: 一次性任务（ISO 8601 时间戳）

**会话类型**:
- `isolated`（推荐）: 干净上下文，无对话历史
- `main`: 带完整对话历史

**推送方式**:
- `announce`: 推送到活跃聊天频道
- `webhook`: POST 到指定 URL
- `none`: 静默执行（无推送）

**存储位置**: `~/.openclaw/cron/jobs.json`

**CLI 命令**:
```bash
openclaw cron add     # 创建任务
openclaw cron list    # 列出任务
openclaw cron run     # 立即运行（测试）
openclaw cron edit    # 编辑任务
openclaw cron rm      # 删除任务
```

---

### 任务 1: 日报 (life-index-daily-report)

**OpenClaw CLI 配置**:
```bash
openclaw cron add \
  --name "Life Index 日报" \
  --cron "0 22 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行 Life Index 日报任务：使用 tools/search_journals 查询今日（$(date +%Y-%m-%d)）的日志，生成 200 tokens 以内的摘要推送。如果今日无日志，推送'今日暂无记录'。" \
  --announce
```

**或 JSON 配置**（添加到 `~/.openclaw/cron/jobs.json`）:
```json
{
  "id": "life-index-daily-report",
  "name": "Life Index 日报",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "0 22 * * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 Life Index 日报任务：使用 tools/search_journals 查询今日日志（--date $(date +%Y-%m-%d)），生成约 200 tokens 的摘要推送。如果今日无日志，只推送'今日暂无记录'。摘要格式：【Life Index 日报】日期 + 要点速览（3-5条）+ AI建议（1-3条）。",
    "timeoutSeconds": 300
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**详细场景指南**: [scenarios/daily-report.md](./scenarios/daily-report.md)

---

### 任务 2: 周报 (life-index-weekly-report)

**OpenClaw CLI 配置**:
```bash
openclaw cron add \
  --name "Life Index 周报" \
  --cron "10 22 * * 0" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行 Life Index 周报任务：查询本周（周一至周日）的日志，生成本周总结推送。包含：主题分布、核心洞察、高光时刻、趋势观察。约 500 tokens。" \
  --announce
```

**或 JSON 配置**:
```json
{
  "id": "life-index-weekly-report",
  "name": "Life Index 周报",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "10 22 * * 0",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 Life Index 周报任务：使用 tools/search_journals 查询本周日志（--date-from 本周一 --date-to 今天），生成约 500 tokens 的周报推送。包含：本周概览、核心主题（2-3个）、高光时刻、趋势观察。",
    "timeoutSeconds": 300
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**详细场景指南**: [scenarios/weekly-report.md](./scenarios/weekly-report.md)

---

### 任务 3: 月报 (life-index-monthly-report)

**OpenClaw CLI 配置**:
```bash
openclaw cron add \
  --name "Life Index 月报" \
  --cron "30 18 28-31 * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行 Life Index 月报任务：使用 tools/generate_abstract 生成本月摘要文件，并推送摘要内容告知用户文件位置。约 1000 tokens。" \
  --announce
```

**或 JSON 配置**:
```json
{
  "id": "life-index-monthly-report",
  "name": "Life Index 月报",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "30 18 28-31 * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 Life Index 月报任务：使用 tools/generate_abstract.py --month $(date +%Y-%m) 生成本月摘要文件。读取生成的文件（Journals/YYYY/MM/monthly_report_YYYY-MM.md），推送约 1000 tokens 的月报摘要给用户，并告知文件完整路径。",
    "timeoutSeconds": 600
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**详细场景指南**: [scenarios/monthly-report.md](./scenarios/monthly-report.md)

---

### 任务 4: 年报 (life-index-yearly-report)

**OpenClaw CLI 配置**:
```bash
openclaw cron add \
  --name "Life Index 年报" \
  --cron "15 19 31 12 *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行 Life Index 年报任务：生成本年度摘要文件，推送年度总结。约 3000 tokens。" \
  --announce
```

**或 JSON 配置**:
```json
{
  "id": "life-index-yearly-report",
  "name": "Life Index 年报",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "15 19 31 12 *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 Life Index 年报任务：使用 tools/generate_abstract.py --year $(date +%Y) 生成本年度摘要文件。读取生成的文件（Journals/YYYY/yearly_report_YYYY.md），推送约 3000 tokens 的年度总结，包含：全年概览、核心主题分析、高光时刻、年度洞察。",
    "timeoutSeconds": 900
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**详细场景指南**: [scenarios/yearly-report.md](./scenarios/yearly-report.md)

---

### 任务 5: 每日索引维护 (life-index-daily-index)

**OpenClaw CLI 配置**:
```bash
openclaw cron add \
  --name "Life Index 每日索引维护" \
  --cron "50 23 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行 Life Index 索引维护：运行 tools/build_index.py 更新 FTS 索引和向量索引。此任务静默执行，无需推送。"
```

**或 JSON 配置**:
```json
{
  "id": "life-index-daily-index",
  "name": "Life Index 每日索引维护",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "50 23 * * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 Life Index 索引维护任务：运行 tools/build_index.py 增量更新 FTS 搜索索引。如果向量搜索可用，同时更新向量索引。此任务静默执行，无需输出。",
    "timeoutSeconds": 300
  },
  "delivery": {
    "mode": "none"
  }
}
```

**详细场景指南**: [scenarios/index-update.md](./scenarios/index-update.md)

---

### 任务 6: 每月索引重建 (life-index-monthly-rebuild)

**OpenClaw CLI 配置**:
```bash
openclaw cron add \
  --name "Life Index 每月索引重建" \
  --cron "30 3 1 * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行 Life Index 全量索引重建：运行 tools/build_index.py --rebuild 全量重建索引。此任务静默执行，无需推送。"
```

**或 JSON 配置**:
```json
{
  "id": "life-index-monthly-rebuild",
  "name": "Life Index 每月索引重建",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "30 3 1 * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行 Life Index 全量索引重建任务：运行 tools/build_index.py --rebuild 全量重建所有索引。此任务静默执行，无需输出。",
    "timeoutSeconds": 600
  },
  "delivery": {
    "mode": "none"
  }
}
```

**详细场景指南**: [scenarios/index-rebuild.md](./scenarios/index-rebuild.md)

---

## Step 3: 自我系统分析

在配置前，请先确认你的 OpenClaw 版本和能力。

### 3.1 检查 OpenClaw 版本和功能

**执行以下命令**:
```bash
# 检查 OpenClaw 版本
openclaw --version

# 检查 cron 功能是否可用
openclaw cron status

# 查看当前定时任务列表
openclaw cron list
```

**记录结果**:
- OpenClaw 版本: ___________
- `openclaw cron` 命令是否可用: ✅ / ❌
- 当前是否有定时任务: 有 ___ 个 / 无

### 3.2 确认技能路径

Life Index 技能在你的系统中的实际路径：
```bash
# 查找 Life Index 安装位置
find ~ -name "life-index" -type d 2>/dev/null | head -5

# 或根据常见路径检查
ls -la ~/.openclaw/skills/life-index/ 2>/dev/null || \
ls -la ~/openclaw/skills/life-index/ 2>/dev/null || \
ls -la /app/skills/life-index/ 2>/dev/null
```

**记录结果**:
- 技能路径: ___________

### 3.3 查阅官方文档

**必读文档**（根据搜索结果整理）：
1. [OpenClaw Cron Jobs 官方文档](https://openclawlab.com/en/docs/automation/cron-jobs/)
2. [Stack Junkie: 8 个自动化模板](https://www.stack-junkie.com/blog/openclaw-cron-jobs-automation-guide)
3. [Cron vs Heartbeat 对比](https://openclawlab.com/en/docs/automation/cron-vs-heartbeat/)

**重点关注**:
- Cron 表达式时区设置（使用 `--tz` 或 `tz` 字段）
- Isolated vs Main session 的区别
- Delivery mode 配置（announce/webhook/none）
- Token 成本控制

---

## Step 4: 判断与决策

基于 Step 3 的分析结果，决定如何配置。

### 决策流程

```
OpenClaw 版本是否 ≥ 2026.2？
│
├─ 否 → 升级 OpenClaw 到最新版本
│
└─ 是 → cron 命令是否可用？
        │
        ├─ 否 → 检查 gateway 配置，确保 cron.enabled 为 true
        │
        └─ 是 → 技能路径是否正确？
                │
                ├─ 路径与模板一致
                │   → 直接执行 Step 2 的 CLI 命令
                │
                └─ 路径不同
                    → 修改命令中的技能路径，保持其他配置不变
```

### 路径调整示例

**如果技能路径不同**:
```bash
# 模板使用（相对路径）
cd openclaw/workspace/skills/life-index

# 你的实际路径（示例）
cd /home/dexter/.openclaw/skills/life-index
# 或
cd ~/.openclaw/skills/life-index
```

**只需修改 `cd` 后的路径，其他配置保持不变**。

---

## Step 5: 执行设置

### 5.1 配置步骤

**方式一：通过 CLI 逐一创建（推荐）**

按顺序执行 Step 2 中的 6 个 CLI 命令：

```bash
# 1. 日报
openclaw cron add --name "Life Index 日报" --cron "0 22 * * *" ...

# 2. 周报
openclaw cron add --name "Life Index 周报" --cron "10 22 * * 0" ...

# 3. 月报
openclaw cron add --name "Life Index 月报" --cron "30 18 28-31 * *" ...

# 4. 年报
openclaw cron add --name "Life Index 年报" --cron "15 19 31 12 *" ...

# 5. 每日索引
openclaw cron add --name "Life Index 每日索引维护" --cron "50 23 * * *" ...

# 6. 每月重建
openclaw cron add --name "Life Index 每月索引重建" --cron "30 3 1 * *" ...
```

**方式二：通过 Agent 聊天创建**

告诉你的 OpenClaw Agent：
```
请为我创建 6 个 Life Index 定时任务。

任务配置如下：

1. 日报：每天 22:00，isolated session，announce 推送
   任务内容：查询今日日志，生成 200 tokens 摘要

2. 周报：每周日 22:10，isolated session，announce 推送
   任务内容：查询本周日志，生成 500 tokens 周报

3. 月报：每月最后一天 18:30，isolated session，announce 推送
   任务内容：生成本月摘要文件，推送约 1000 tokens

4. 年报：12月31日 19:15，isolated session，announce 推送
   任务内容：生成本年度摘要文件，推送约 3000 tokens

5. 每日索引：每天 23:50，isolated session，无推送
   任务内容：运行 build_index.py 增量更新索引

6. 每月重建：每月1日 03:30，isolated session，无推送
   任务内容：运行 build_index.py --rebuild 全量重建索引

时区：Asia/Shanghai
技能路径：（根据实际路径填写）
```

### 5.2 验证配置

**创建后检查**:
```bash
openclaw cron list
```

**测试运行**（不等待定时触发）:
```bash
# 获取任务 ID
openclaw cron list

# 立即运行测试
openclaw cron run <job-id>
```

**检查推送**:
- 确认是否能收到推送消息
- 检查推送内容是否符合预期

### 5.3 完成清单

- [ ] 6 个任务全部创建成功
- [ ] `openclaw cron list` 显示所有任务
- [ ] 手动测试每个任务都能正常运行
- [ ] 推送渠道配置正确（main session + IM channels）
- [ ] 等待首次定时触发，确认自动执行成功

---

## 故障排查

### 问题 1: "openclaw cron 命令不可用"

**原因**: Gateway 未启用 cron 功能

**解决**:
```bash
# 检查 gateway 配置
cat ~/.openclaw/config/config.json | grep -A5 cron

# 确保配置包含：
{
  "cron": {
    "enabled": true
  }
}

# 重启 gateway
openclaw gateway restart
```

### 问题 2: "任务运行但无输出"

**原因**: Delivery mode 配置错误或 session 类型错误

**解决**:
- 检查是否使用了 `--announce` 或 `"mode": "announce"`
- 确认 session 是 `isolated`（不是 `main`）
- 检查推送渠道是否配置正确

### 问题 3: "找不到工具"

**原因**: 技能路径错误或当前工作目录不对

**解决**:
- 确认 payload 中使用了正确的技能路径
- 在指令开头添加 `cd [技能路径]`
- 使用 `python -m tools.xxx` 而不是直接调用脚本

### 问题 4: "定时任务不触发"

**原因**: 时区设置错误或 cron 表达式格式错误

**解决**:
- 使用 `--tz "Asia/Shanghai"` 明确指定时区
- 使用 [crontab.guru](https://crontab.guru/) 验证表达式
- 检查系统时间是否正确

### 问题 5: "推送失败 / 收不到消息"

**原因**: Channel 未配置或 pairing 问题

**解决**:
- 检查 OpenClaw pairing 状态
- 确认推送渠道（Telegram/Slack/飞书）已正确配置
- 尝试只推送到 main session 测试

---

## 附录

### A. 相关文档

- **日报详细指南**: [scenarios/daily-report.md](./scenarios/daily-report.md)
- **周报详细指南**: [scenarios/weekly-report.md](./scenarios/weekly-report.md)
- **月报详细指南**: [scenarios/monthly-report.md](./scenarios/monthly-report.md)
- **年报详细指南**: [scenarios/yearly-report.md](./scenarios/yearly-report.md)
- **索引维护指南**: [scenarios/index-update.md](./scenarios/index-update.md)
- **索引重建指南**: [scenarios/index-rebuild.md](./scenarios/index-rebuild.md)

### B. 外部参考

- [OpenClaw Cron Jobs 官方文档](https://openclawlab.com/en/docs/automation/cron-jobs/)
- [Cron vs Heartbeat 对比](https://openclawlab.com/en/docs/automation/cron-vs-heartbeat/)
- [Stack Junkie: 8 个自动化模板](https://www.stack-junkie.com/blog/openclaw-cron-jobs-automation-guide)
- [Cron 表达式验证工具](https://crontab.guru/)

### C. 任务速查表

| 任务 | Cron 表达式 | Session | Delivery | 核心指令 |
|------|------------|---------|----------|---------|
| 日报 | `0 22 * * *` | isolated | announce | `search_journals --date TODAY` |
| 周报 | `10 22 * * 0` | isolated | announce | `search_journals --date-from 周一 --date-to 今天` |
| 月报 | `30 18 28-31 * *` | isolated | announce | `generate_abstract --month YYYY-MM` |
| 年报 | `15 19 31 12 *` | isolated | announce | `generate_abstract --year YYYY` |
| 每日索引 | `50 23 * * *` | isolated | none | `build_index.py` |
| 每月重建 | `30 3 1 * *` | isolated | none | `build_index.py --rebuild` |

---

**文档结束** — 请完成 Step 1-5，为 Life Index 配置定时任务。
