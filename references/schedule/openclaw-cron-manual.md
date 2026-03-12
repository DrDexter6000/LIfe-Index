# Life Index OpenClaw 定时任务 - 手动配置指南

> **适用**: OpenClaw 2026.3.8 + Ubuntu
> **状态**: 已验证基础功能

---

## 前置确认

请确认以下信息：

```bash
# 1. OpenClaw版本
openclaw --version
# 预期输出: 2026.3.8 或更高

# 2. Life Index路径
# 请替换为实际路径，例如:
# /home/username/openclaw/skills/life-index
# /app/skills/life-index
LIFE_INDEX_PATH="[你的实际路径]"
```

---

## 任务1: 日报 (每天22:00)

**执行命令**:

```bash
openclaw cron add \
  --name "life-index-daily-report" \
  --cron "0 22 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index日报生成任务。

步骤：
1. 进入目录: cd /path/to/life-index
2. 查询今日日志: python tools/search_journals.py --date $(date +%Y-%m-%d) --limit 100
3. 如果有日志，生成日报推送给用户
4. 如果无日志，告知用户今日无记录

日报格式：
【Life Index 日报】日期
📝 今日概要：[2-3句话总结]
⚡ 要点速览：[3-5个要点]
💡 AI建议：[1-3条建议]" \
  --announce \
  --timeout 120
```

**注意**: 将 `/path/to/life-index` 替换为实际路径

---

## 任务2: 周报 (每周日22:10)

**执行命令**:

```bash
openclaw cron add \
  --name "life-index-weekly-report" \
  --cron "10 22 * * 0" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index周报生成任务。

步骤：
1. 进入目录: cd /path/to/life-index
2. 计算本周日期范围
3. 查询本周日志: python tools/search_journals.py --date-from [周一] --date-to [周日] --limit 500
4. 生成周报推送给用户

周报格式：
【Life Index 周报】日期范围
📊 本周概览：[N篇日志]
🎯 核心主题：[2-3个主题]
⚡ 高光时刻：[3-5条要点]" \
  --announce \
  --timeout 180
```

---

## 任务3: 月报 (每月末18:30)

**执行命令**:

```bash
openclaw cron add \
  --name "life-index-monthly-report" \
  --cron "30 18 28-31 * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index月报生成任务。

步骤：
1. 检查是否是本月最后一天，不是则跳过
2. 进入目录: cd /path/to/life-index
3. 生成本月摘要: python tools/generate_abstract.py --month $(date +%Y-%m)
4. 生成月报推送给用户，告知文件位置

月报格式：
【Life Index 月报】YYYY年MM月
📊 数据概览：[N篇日志]
📝 月度精选：[3-5篇重要日志]
🎯 核心洞察：[AI洞察]
📄 详细报告已保存至Journals/YYYY/MM/monthly_report_YYYY-MM.md" \
  --announce \
  --timeout 300
```

---

## 任务4: 索引维护 (每天23:50)

**执行命令**:

```bash
openclaw cron add \
  --name "life-index-index-maintenance" \
  --cron "50 23 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index索引维护。

步骤：
1. 进入目录: cd /path/to/life-index
2. 更新FTS索引: python tools/build_index.py
3. 尝试更新向量索引: python tools/build_index.py --semantic 2>/dev/null || echo '跳过'

约束：静默执行，无需通知用户" \
  --timeout 600
```

**注意**: 索引维护任务没有 `--announce`，静默执行

---

## 验证和管理

### 查看所有任务

```bash
openclaw cron list
```

### 手动触发测试

```bash
# 测试日报
openclaw cron run life-index-daily-report

# 测试周报
openclaw cron run life-index-weekly-report

# 测试月报
openclaw cron run life-index-monthly-report

# 测试索引维护
openclaw cron run life-index-index-maintenance
```

### 查看执行历史

```bash
# 查看特定任务的历史
openclaw cron runs --id life-index-daily-report

# 查看所有历史
openclaw cron history --limit 20
```

### 暂停/恢复任务

```bash
# 暂停日报
openclaw cron pause life-index-daily-report

# 恢复日报
openclaw cron resume life-index-daily-report
```

### 删除任务

```bash
# 删除单个任务
openclaw cron rm life-index-daily-report

# 删除所有Life Index任务
openclaw cron rm life-index-daily-report
openclaw cron rm life-index-weekly-report
openclaw cron rm life-index-monthly-report
openclaw cron rm life-index-index-maintenance
```

---

## 故障排查

### 问题1: 任务未按时执行

检查：
```bash
# 确认任务存在且启用
openclaw cron list

# 检查Gateway状态
openclaw cron status

# 查看下次执行时间
openclaw cron next life-index-daily-report --count 3
```

### 问题2: 执行失败

查看日志：
```bash
openclaw cron runs --id life-index-daily-report
```

常见原因：
- 路径错误 → 检查 `LIFE_INDEX_PATH`
- 超时 → 增加 `--timeout` 值
- 权限 → 确认定时任务可访问技能目录

### 问题3: 未收到推送

检查：
- 是否添加了 `--announce` 参数
- 如果是索引维护任务，正常行为就是不推送
- 检查OpenClaw通知渠道配置

---

## 快速检查清单

配置完成后，确认：

- [ ] 4个任务都出现在 `openclaw cron list` 中
- [ ] 任务状态为 `enabled`
- [ ] 手动测试 `openclaw cron run life-index-daily-report` 成功
- [ ] 收到测试日报
- [ ] 日报内容符合预期格式

---

## 路径替换示例

假设Life Index安装在 `/home/dexter/openclaw/skills/life-index`：

将所有命令中的：
```
cd /path/to/life-index
```

替换为：
```
cd /home/dexter/openclaw/skills/life-index
```

---

**配置完成后，建议等待第一个定时任务触发（或手动测试），确认一切正常。**
