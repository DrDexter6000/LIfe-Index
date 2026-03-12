# Life Index 定时任务设置指南

> **本文档角色**: 指导 Agent 为 Life Index 技能配置定时任务  
> **阅读对象**: AI Agent（OpenClaw / Claude Desktop / 其他支持定时任务的平台）  
> **版本**: v3.1 Agent-Native Edition | **更新**: 2026-03-13
> ⚠️ **重要**: Step 2 的 OpenClaw 模板基于通用 Cron 语法和假设格式编写，未经 OpenClaw 官方文档验证。实际使用前请测试验证并根据错误调整。

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

## Step 2: 查看参考模板 — OpenClaw 平台

以下是为 **OpenClaw** 平台设计的 6 个定时任务模板。

**路径假设**：
```
技能目录: openclaw/workspace/skills/life-index/
```
（实际路径需要根据你的系统调整）

---

### 任务 1: 日报 (life-index-daily-report)

```yaml
名称: life-index-daily-report
时间: 0 22 * * *
指令: |
  cd openclaw/workspace/skills/life-index
  TODAY=$(date +%Y-%m-%d)
  
  # 获取今日日志
  RESULT=$(python -m tools.search_journals --date $TODAY --limit 100 --json 2>/dev/null)
  
  # 解析结果
  COUNT=$(echo $RESULT | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d.get('merged_results',[])))" 2>/dev/null || echo "0")
  
  if [ "$COUNT" -eq 0 ]; then
    echo "📭 $TODAY 暂无日志记录"
    exit 0
  fi
  
  # 生成日报
  echo "【Life Index 日报】$TODAY"
  echo "今日共记录 $COUNT 篇日志"
  echo ""
  echo $RESULT | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('merged_results', [])[:3]
for r in results:
    print(f'• {r.get(\"title\", \"无标题\")}')
if len(data.get('merged_results', [])) > 3:
    print(f'... 还有 {len(data.get(\"merged_results\", []))-3} 篇')
"
推送渠道: 
  - main-session
  - im-channels  # 如已配置 Slack/飞书等
```

---

### 任务 2: 周报 (life-index-weekly-report)

```yaml
名称: life-index-weekly-report
时间: 10 22 * * 0
指令: |
  cd openclaw/workspace/skills/life-index
  WEEK_START=$(date -d '6 days ago' +%Y-%m-%d)
  WEEK_END=$(date +%Y-%m-%d)
  
  # 获取本周日志
  RESULT=$(python -m tools.search_journals --date-from $WEEK_START --date-to $WEEK_END --limit 500 --json 2>/dev/null)
  
  COUNT=$(echo $RESULT | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d.get('merged_results',[])))" 2>/dev/null || echo "0")
  
  if [ "$COUNT" -eq 0 ]; then
    echo "📭 $WEEK_START ~ $WEEK_END 本周暂无日志"
    exit 0
  fi
  
  echo "【Life Index 周报】$WEEK_START ~ $WEEK_END"
  echo "本周共记录 $COUNT 篇日志"
  echo ""
  echo $RESULT | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('merged_results', [])
topics = {}
for r in results:
    topic = r.get('metadata', {}).get('topic', ['未分类'])
    if isinstance(topic, list) and topic:
        topic = topic[0]
    topics[topic] = topics.get(topic, 0) + 1
print('主题分布:')
for t, c in sorted(topics.items(), key=lambda x: -x[1])[:3]:
    print(f'  {t}: {c}篇')
"
推送渠道:
  - main-session
  - im-channels
```

---

### 任务 3: 月报 (life-index-monthly-report)

```yaml
名称: life-index-monthly-report
时间: 30 18 28-31 * *
条件: 仅在本月最后一天执行
指令: |
  cd openclaw/workspace/skills/life-index
  YEAR=$(date +%Y)
  MONTH=$(date +%m)
  
  # 生成本月摘要文件
  RESULT=$(python tools/generate_abstract.py --month $YEAR-$MONTH --json 2>/dev/null)
  
  # 提取文件路径
  ABSTRACT_PATH=$(echo $RESULT | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0].get('abstract_path','unknown') if isinstance(d,list) and d else d.get('abstract_path','unknown'))" 2>/dev/null)
  JOURNAL_COUNT=$(echo $RESULT | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0].get('journal_count',0) if isinstance(d,list) and d else d.get('journal_count',0))" 2>/dev/null || echo "0")
  
  echo "【Life Index 月报】$YEAR年$MONTH月"
  echo "生成文件: $ABSTRACT_PATH"
  echo "包含 $JOURNAL_COUNT 篇日志"
  echo ""
  
  # 读取摘要内容推送
  if [ -f "$ABSTRACT_PATH" ]; then
    head -50 "$ABSTRACT_PATH"
    echo "..."
    echo "(完整内容请查看文件)"
  fi
推送渠道:
  - main-session
  - im-channels
输出文件: Journals/{YYYY}/{MM}/monthly_report_{YYYY}-{MM}.md
```

---

### 任务 4: 年报 (life-index-yearly-report)

```yaml
名称: life-index-yearly-report
时间: 15 19 31 12 *
指令: |
  cd openclaw/workspace/skills/life-index
  YEAR=$(date +%Y)
  
  # 生成本年度摘要
  RESULT=$(python tools/generate_abstract.py --year $YEAR --json 2>/dev/null)
  
  ABSTRACT_PATH=$(echo $RESULT | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0].get('abstract_path','unknown') if isinstance(d,list) and d else d.get('abstract_path','unknown'))" 2>/dev/null)
  JOURNAL_COUNT=$(echo $RESULT | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0].get('journal_count',0) if isinstance(d,list) and d else d.get('journal_count',0))" 2>/dev/null || echo "0")
  
  echo "【Life Index 年报】$YEAR"
  echo "全年共记录 $JOURNAL_COUNT 篇日志"
  echo "生成文件: $ABSTRACT_PATH"
  echo ""
  echo "年度回顾已生成，请查看完整报告。"
推送渠道:
  - main-session
输出文件: Journals/{YYYY}/yearly_report_{YYYY}.md
```

---

### 任务 5: 每日索引维护 (life-index-daily-index)

```yaml
名称: life-index-daily-index
时间: 50 23 * * *
指令: |
  cd openclaw/workspace/skills/life-index
  
  # 更新 FTS 索引
  python tools/build_index.py 2>/dev/null && echo "✓ FTS索引更新完成" || echo "✗ FTS索引更新失败"
  
  # 更新向量索引（如果可用）
  python tools/build_index.py --semantic 2>/dev/null && echo "✓ 向量索引更新完成" || echo "- 向量索引跳过"
推送渠道: 无（静默执行）
```

---

### 任务 6: 每月索引重建 (life-index-monthly-rebuild)

```yaml
名称: life-index-monthly-rebuild
时间: 30 3 1 * *
指令: |
  cd openclaw/workspace/skills/life-index
  
  # 全量重建索引
  python tools/build_index.py --rebuild 2>/dev/null && echo "✓ 索引全量重建完成" || echo "✗ 索引重建失败"
推送渠道: 无（静默执行）
```

---

## Step 3: 自我分析 — 了解你的定时任务能力

在采用上述模板前，请先分析你自己的系统。

### 3.1 回答以下问题

**Q1: 你的平台支持定时任务吗？**
- [ ] 支持内置定时任务（Cron/Scheduler）
- [ ] 不支持，需要用户手动执行

**Q2: 如果支持，定时任务的格式是什么？**
- [ ] Cron 表达式 + 自然语言指令（如 OpenClaw）
- [ ] Cron 表达式 + Shell 脚本
- [ ] 其他格式: ___________

**Q3: 你的定时任务可以访问技能目录吗？**
- [ ] 可以，且可以获取技能路径变量（如 `{{SKILL_DIR}}`）
- [ ] 可以，但路径固定（如 `openclaw/workspace/skills/life-index/`）
- [ ] 不可以，完全隔离环境

**Q4: 你能主动推送消息给用户吗？**
- [ ] 可以推送到主会话
- [ ] 可以推送到 IM 渠道（Slack/飞书/微信等）
- [ ] 不能主动推送，只能生成文件

**Q5: 定时任务执行有 Token 限制吗？**
- [ ] 无限制
- [ ] 有限制，单任务最大约 ______ tokens

### 3.2 查阅你的官方文档

搜索关键词: `[你的平台名称] 定时任务 cron 配置官方文档`

重点关注：
- 时间格式（Cron 表达式语法）
- 执行环境（能否访问文件系统）
- 变量替换（支持哪些占位符）
- 推送能力（如何发送通知）

---

## Step 4: 判断与决策

基于 Step 3 的分析，决定如何使用 Step 2 的模板。

### 决策流程

```
你的平台支持定时任务吗？
│
├─ 否 → 进入【手动模式】（见下方）
│
└─ 是 → 可以访问技能目录吗？
        │
        ├─ 否 → 需要用户设置环境变量或改用 HTTP API 方案
        │       （超出本文档范围，询问用户如何处理）
        │
        └─ 是 → 路径格式与模板一致吗？
                │
                ├─ 完全一致（OpenClaw 风格）
                │   → 使用 Step 2 的 6 个任务模板作为起点，根据实际测试调整
                │
                └─ 不一致（路径或变量格式不同）
                    → 修改模板中的路径和变量格式
                    → 保持任务逻辑不变
```

### 常见调整

**场景 A: 路径不同**
```
模板: openclaw/workspace/skills/life-index/
你的平台: /home/user/.config/agent/skills/life-index/

→ 修改所有 cd 命令中的路径
```

**场景 B: 变量格式不同**
```
模板: $(date +%Y-%m-%d)
你的平台: {{date "YYYY-MM-DD"}}

→ 替换为你平台支持的日期变量格式
```

**场景 C: 不支持多行指令**
```
模板: 使用 | 符号的多行 YAML
你的平台: 只接受单行

→ 将所有指令合并为一行，用 && 连接
```

---

## Step 5: 执行设置

### 5.1 如果你是 OpenClaw

参考使用 Step 2 的 6 个 YAML 模板，在 OpenClaw 定时任务设置中创建，并根据实际测试结果调整。

**创建清单**（完成一项勾一项）：
- [ ] 任务 1: life-index-daily-report (0 22 * * *)
- [ ] 任务 2: life-index-weekly-report (10 22 * * 0)
- [ ] 任务 3: life-index-monthly-report (30 18 28-31 * *)
- [ ] 任务 4: life-index-yearly-report (15 19 31 12 *)
- [ ] 任务 5: life-index-daily-index (50 23 * * *)
- [ ] 任务 6: life-index-monthly-rebuild (30 3 1 * *)

**验证步骤**（设置后执行）：
1. 等待下一个日报时间（或手动触发测试）
2. 检查是否能正常获取日志
3. 检查推送是否正常收到

### 5.2 如果你是其他平台

1. 根据 Step 4 的调整指南，修改 6 个任务模板
2. 在你平台的定时任务设置界面逐一创建
3. 首次创建后，手动触发测试每个任务
4. 根据测试结果微调指令

### 5.3 如果你的平台不支持定时任务

**进入手动模式**：

当用户找你时，主动询问是否需要生成报告：

```
用户: "查看今日日志"
你: 执行日报逻辑（获取今日日志 + 生成摘要 + 推送）

用户: "本周总结"
你: 执行周报逻辑（获取本周日志 + 生成报告 + 推送）

每月最后一天用户上线时:
你: "本月即将结束，要我生成本月总结吗？"
```

**关键**：虽然无法定时自动执行，但你可以在用户主动对话时**代劳**。

---

## 故障排查

### 问题 1: "找不到工具" / "python: command not found"

**原因**: 定时任务的执行目录或 Python 路径不对

**解决**:
1. 在指令开头加上 `cd` 切换到技能目录
2. 使用 `python` 或 `python3` 全路径（如 `/usr/bin/python3`）
3. 确认技能目录路径正确

### 问题 2: 推送失败 / 用户收不到消息

**原因**: Channel 配置问题或推送权限问题

**解决**:
1. 检查推送渠道配置（main-session 是否选中）
2. IM 渠道（Slack/飞书）需要预先配置 webhook
3. 尝试只推送到 main-session 测试

### 问题 3: "没有日志" 但用户说记录过

**原因**: 时区不匹配，定时任务认为的"今天"和用户时区不同

**解决**:
- 调整定时任务时间（提前或延后几小时）
- 在指令中使用用户时区的日期计算

### 问题 4: Cron 时间不生效

**常见错误**:
```
# 错误（秒级精度，Cron 不支持）
0 0 22 * * *

# 正确（分钟 小时 日 月 星期）
0 22 * * *
```

使用在线 Cron 解析器验证: https://crontab.guru/

---

## 附录

### A. 相关文档

- **日报详细指南**: [scenarios/daily-report.md](./scenarios/daily-report.md)
- **周报详细指南**: [scenarios/weekly-report.md](./scenarios/weekly-report.md)
- **月报详细指南**: [scenarios/monthly-report.md](./scenarios/monthly-report.md)
- **年报详细指南**: [scenarios/yearly-report.md](./scenarios/yearly-report.md)
- **索引维护指南**: [scenarios/index-update.md](./scenarios/index-update.md) / [scenarios/index-rebuild.md](./scenarios/index-rebuild.md)

### B. 任务速查表

| 任务 | Cron | 核心指令 |
|------|------|---------|
| 日报 | `0 22 * * *` | `search_journals --date TODAY` |
| 周报 | `10 22 * * 0` | `search_journals --date-from 6天前 --date-to 今天` |
| 月报 | `30 18 28-31 * *` | `generate_abstract --month YYYY-MM` |
| 年报 | `15 19 31 12 *` | `generate_abstract --year YYYY` |
| 每日索引 | `50 23 * * *` | `build_index.py` |
| 每月重建 | `30 3 1 * *` | `build_index.py --rebuild` |

---

**文档结束** — 请完成 Step 1-5，为 Life Index 配置定时任务。
