# Life Index 定时任务配置工作流（基于OpenClaw官方文档）

> **本文档角色**: 引导Agent配置OpenClaw定时任务的交互式Prompt
> **依据**: OpenClaw官方文档 https://docs.openclaw.ai/zh-CN/automation/cron-jobs
> **版本**: 基于OpenClaw 2026.2+

---

## Step 1: 理解意图（Why & What）

### 1.1 Life Index定时任务的目的

Life Index通过定时任务成为用户的**数字生活管家**：

| 任务 | 时间 | 价值 | 实现方式 |
|------|------|------|---------|
| **日报** | 每天22:00 | 回顾今日记录，获得AI建议 | OpenClaw Cron |
| **周报** | 每周日22:10 | 总结本周生活轨迹 | OpenClaw Cron |
| **月报** | 每月末18:30 | 深度回顾，生成摘要文件 | OpenClaw Cron |
| **年报** | 12月31日19:15 | 年度人生总结 | OpenClaw Cron |
| **索引维护** | 每天23:50 | 保持搜索性能 | OpenClaw Cron |

---

## Step 2: OpenClaw定时任务标准格式

### 2.1 官方配置结构

```json
{
  "name": "任务名称",
  "schedule": {
    "kind": "cron",
    "expr": "分 时 日 月 星期",
    "tz": "时区"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "自然语言指令",
    "timeoutSeconds": 300,
    "model": "haiku"
  },
  "delivery": {
    "mode": "announce"
  }
}
```

### 2.2 关键字段说明（官方）

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 任务名称，唯一标识 |
| `schedule.kind` | ✅ | `cron`/`at`/`every` |
| `schedule.expr` | ✅ | Cron表达式（如`0 22 * * *`） |
| `schedule.tz` | ⚠️ | **必须设置**，否则默认UTC！常用：`Asia/Shanghai` |
| `sessionTarget` | ✅ | `isolated`（推荐）或`main` |
| `payload.kind` | ✅ | `agentTurn`（isolated模式） |
| `payload.message` | ✅ | **发给Agent的自然语言指令** |
| `payload.timeoutSeconds` | ❌ | 超时时间，默认可能不够 |
| `payload.model` | ❌ | 指定模型，如`haiku`降成本 |
| `delivery.mode` | ✅ | `announce`（推送到主会话） |

### 2.3 官方存储位置

定时任务保存在：
```
~/.openclaw/cron/jobs.json
```

⚠️ **注意**: Gateway运行时会加载到内存，**仅在Gateway停止时手动编辑才安全**。

**推荐操作方式**:
- 使用CLI: `openclaw cron add/edit`
- 或使用Agent对话让AI帮你创建

---

## Step 3: Life Index定时任务模板（OpenClaw官方格式）

### 模板A: 日报任务

```json
{
  "name": "life-index-daily-report",
  "schedule": {
    "kind": "cron",
    "expr": "0 22 * * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行Life Index日报生成任务。\n\n步骤：\n1. 进入Life Index技能目录\n2. 执行：python tools/search_journals.py --date $(date +%Y-%m-%d) --limit 100\n3. 如果有日志，生成日报并推送给用户\n4. 如果无日志，告知用户今日无记录\n\n日报格式：\n【Life Index 日报】日期\n📝 今日概要：[2-3句话总结]\n⚡ 要点速览：[3-5个要点]\n💡 AI建议：[1-3条建议]",
    "timeoutSeconds": 120,
    "model": "haiku"
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**Cron表达式**: `0 22 * * *`（每天22:00）

**关键点**:
- `sessionTarget: "isolated"` - 独立执行，不干扰主对话
- `payload.message` - 完整的自然语言指令
- `delivery.mode: "announce"` - 完成后推送到主会话
- `model: "haiku"` - 使用便宜模型降低成本

---

### 模板B: 周报任务

```json
{
  "name": "life-index-weekly-report",
  "schedule": {
    "kind": "cron",
    "expr": "10 22 * * 0",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行Life Index周报生成任务。\n\n步骤：\n1. 计算本周日期范围（周一至周日）\n2. 执行：python tools/search_journals.py --date-from [本周一] --date-to [本周日] --limit 500\n3. 基于本周日志生成周报并推送给用户\n\n周报格式：\n【Life Index 周报】日期范围\n📊 本周概览：[N篇日志，主题分布]\n🎯 核心主题：[2-3个主题]\n⚡ 高光时刻：[3-5条要点]\n📈 趋势观察：[AI洞察]",
    "timeoutSeconds": 180,
    "model": "sonnet"
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**Cron表达式**: `10 22 * * 0`（每周日22:10）

---

### 模板C: 月报任务

```json
{
  "name": "life-index-monthly-report",
  "schedule": {
    "kind": "cron",
    "expr": "30 18 28-31 * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行Life Index月报生成任务。仅在今天是本月最后一天时执行。\n\n步骤：\n1. 检查今天是否是本月最后一天，如果不是则跳过\n2. 执行：python tools/generate_abstract.py --month $(date +%Y-%m)\n3. 读取生成的摘要文件\n4. 生成月报推送给用户，并告知文件保存位置\n\n月报格式：\n【Life Index 月报】YYYY年MM月\n📊 数据概览：[N篇日志，主题分布]\n📝 月度精选：[3-5篇重要日志]\n🎯 核心洞察：[基于数据的洞察]\n💡 下月建议：[AI建议]\n📄 详细报告已保存至：Journals/YYYY/MM/monthly_report_YYYY-MM.md",
    "timeoutSeconds": 300,
    "model": "sonnet"
  },
  "delivery": {
    "mode": "announce"
  }
}
```

**Cron表达式**: `30 18 28-31 * *`（每月最后几天18:30）

**注意**: 需要在message中判断是否是本月最后一天，或者使用外部脚本。

---

### 模板D: 索引维护任务

```json
{
  "name": "life-index-index-maintenance",
  "schedule": {
    "kind": "cron",
    "expr": "50 23 * * *",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "执行Life Index索引维护任务。此任务静默执行，无需通知用户。\n\n步骤：\n1. 进入Life Index技能目录\n2. 执行：python tools/build_index.py\n3. 可选：尝试更新向量索引（如果可用）\n4. 记录执行结果，失败则下次重试\n\n约束：\n- 不向用户推送结果\n- 失败时记录错误日志\n- 下次执行时重试",
    "timeoutSeconds": 600,
    "model": "haiku"
  },
  "delivery": {
    "mode": "none"
  }
}
```

**Cron表达式**: `50 23 * * *`（每天23:50）

**关键点**: `delivery.mode: "none"` - 静默执行，不推送

---

## Step 4: OpenClaw能力自检（基于官方文档）

### 4.1 OpenClaw已确认的能力

根据官方文档，OpenClaw支持：

✅ **定时任务**: 原生支持Cron调度器
✅ **隔离执行**: `sessionTarget: "isolated"`模式
✅ **自然语言指令**: `payload.message`接收Prompt
✅ **结果推送**: `delivery.mode: "announce"`推送到主会话
✅ **时区设置**: `schedule.tz`字段
✅ **超时控制**: `payload.timeoutSeconds`
✅ **模型选择**: `payload.model`字段

### 4.2 需要确认的事项

**问题1**: Life Index技能目录变量
- 模板中使用`$(date +%Y-%m-%d)`可以工作（shell命令替换）
- 但技能目录路径如何获取？
- **解决方案**: 在message中写死绝对路径，或询问用户

**问题2**: 日期计算（周报、月报）
- OpenClaw Cron不支持复杂条件判断
- **解决方案**: 在`payload.message`中让Agent自行计算日期

**问题3**: 推送渠道
- 官方支持`delivery.mode: "announce"`（主会话）
- 飞书/Slack等需要额外配置`delivery.channel`
- **解决方案**: 先使用主会话推送，确认可行后再配置渠道

### 4.3 官方推荐实践

根据OpenClaw文档：

> **推荐`isolated`模式处理定时任务**
> - 不污染主会话上下文
> - 可独立指定模型（降成本）
> - 失败不影响主对话

> **必须设置`schedule.tz`**
> - 不设置则默认UTC
> - 会导致定时任务在用户非预期时间执行

> **任务内容要具体**
> - 不要写"发送简报"
> - 要写"发送简报：包含天气、日程、新闻"

---

## Step 5: 实施步骤（OpenClaw CLI）

### 5.1 通过CLI添加任务

```bash
# 方法1: 使用openclaw cron add（推荐）
openclaw cron add \
  --name "life-index-daily-report" \
  --cron "0 22 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index日报生成任务..." \
  --announce \
  --timeout 120

# 方法2: 直接编辑配置文件（Gateway停止时）
# 编辑 ~/.openclaw/cron/jobs.json，添加上述JSON
```

### 5.2 验证任务

```bash
# 查看所有任务
openclaw cron list

# 手动触发测试（立即执行）
openclaw cron run life-index-daily-report

# 查看执行历史
openclaw cron runs --id life-index-daily-report
```

### 5.3 管理任务

```bash
# 暂停任务
openclaw cron pause life-index-daily-report

# 恢复任务
openclaw cron resume life-index-daily-report

# 删除任务
openclaw cron rm life-index-daily-report
```

---

## Step 6: 故障排查（基于官方文档）

### 6.1 常见问题

**问题1: 任务没有按时执行**
- 检查: `openclaw cron list`确认任务状态是`enabled`
- 检查: 时区是否正确设置（`schedule.tz`）
- 检查: Gateway是否正在运行

**问题2: 执行失败但没有通知**
- 检查: `openclaw cron runs --id <job-id>`查看执行日志
- 可能: `timeoutSeconds`太短，任务超时
- 可能: 技能目录路径错误

**问题3: 推送失败**
- 检查: `delivery.mode`是否正确设置
- 检查: 如果是飞书/Slack等渠道，是否已配置channel

### 6.2 官方调试命令

```bash
# 查看下次执行时间
openclaw cron next life-index-daily-report --count 5

# 强制运行（不等待计划时间）
openclaw cron run life-index-daily-report --force

# 检查调度器状态
openclaw cron status
```

---

## 关键修正（相对于旧版文档）

| 旧版错误理解 | 官方文档证实 |
|-------------|-------------|
| OpenClaw定时任务无法访问文件 | ✅ **可以访问**，隔离session但有文件系统权限 |
| 需要bash脚本 | ✅ **自然语言Prompt**，`payload.message` |
| 需要HTTP API适配层 | ❌ **不需要**，原生支持 |
| 无法指定模型 | ✅ **可以指定**，`payload.model`降成本 |
| 时区可选 | ⚠️ **必须设置**，否则UTC |

---

## 参考文档

1. **OpenClaw官方文档**: https://docs.openclaw.ai/zh-CN/automation/cron-jobs
2. **Cron表达式工具**: https://crontab.guru
3. **社区最佳实践**: https://openclaw-docs.dx3n.cn/tutorials/automation/cron-jobs

---

**文档结束**
