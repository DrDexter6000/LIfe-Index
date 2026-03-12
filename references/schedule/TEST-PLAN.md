# Life Index OpenClaw 定时任务测试计划

> **测试目标**: 验证基于官方文档的定时任务配置在OpenClaw中的实际可行性
> **参与者**: 你（OpenClaw用户）+ 我（文档设计者）
> **测试方式**: 分阶段测试，每步确认后再下一步

---

## Phase 1: 环境验证（5分钟）

### 测试1.1: 确认OpenClaw版本和功能

**请执行**:
```bash
# 检查OpenClaw版本
openclaw --version

# 检查cron功能是否可用
openclaw cron status

# 查看当前定时任务列表
openclaw cron list
```

**请反馈**:
- OpenClaw版本: ___
- `openclaw cron`命令是否可用: ✅/❌
- 当前是否有定时任务: 有___个 / 无

---

## Phase 2: 基础功能测试（10分钟）

### 测试2.1: 创建最简单的测试任务

**请执行**:
```bash
# 创建一个5分钟后执行的测试任务
openclaw cron add \
  --name "test-life-index" \
  --at "5m" \
  --session isolated \
  --message "测试消息：Life Index定时任务配置成功！如果收到这条消息，说明配置有效。" \
  --announce
```

**验证**:
```bash
# 查看任务是否创建成功
openclaw cron list
```

**请反馈**:
- 命令是否执行成功: ✅/❌
- 错误信息（如有）: ___
- `openclaw cron list`是否显示新任务: ✅/❌

---

### 测试2.2: 手动触发测试

**请执行**:
```bash
# 立即执行测试任务（不等待5分钟）
openclaw cron run test-life-index
```

**请反馈**:
- 命令是否执行成功: ✅/❌
- 是否收到"测试消息": ✅/❌
- 消息内容是否正确: ✅/❌

---

### 测试2.3: 清理测试任务

**请执行**:
```bash
# 删除测试任务
openclaw cron rm test-life-index

# 确认已删除
openclaw cron list
```

---

## Phase 3: Life Index集成测试（15分钟）

### 测试3.1: 验证Life Index工具可访问性

**请先确认**:
- Life Index技能已安装: ✅/❌
- 技能安装路径: ___（如 `/app/skills/life-index` 或用户目录下的路径）

**请执行测试**:

在OpenClaw主会话中，说：
```
请执行以下命令测试Life Index工具是否可用：
cd [Life Index路径]
python tools/search_journals.py --help
```

或直接执行：
```bash
# 使用绝对路径测试
python [Life Index路径]/tools/search_journals.py --help
```

**请反馈**:
- 工具是否能正常响应: ✅/❌
- 错误信息（如有）: ___

---

### 测试3.2: 手动生成日报测试

**请执行**:

在OpenClaw主会话中，说：
```
请为我生成今天的Life Index日报：
1. 进入Life Index技能目录
2. 执行 search_journals.py --date [今天日期] --limit 100
3. 如果有日志，生成日报
4. 如果无日志，告知我今天无记录
```

**或提供具体路径**:
```
Life Index安装在：[你的路径]
请用该路径执行上述步骤
```

**请反馈**:
- Agent是否理解任务: ✅/❌
- 是否能找到并执行工具: ✅/❌
- 输出结果: 成功生成日报 / 今天无日志 / 执行失败

---

## Phase 4: 定时任务配置测试（核心）

### 测试4.1: 创建日报定时任务

**请根据你的Life Index路径**，修改以下命令中的`[LIFE_INDEX_PATH]`：

```bash
openclaw cron add \
  --name "life-index-daily-report" \
  --cron "0 22 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index日报生成任务。\n\n步骤：\n1. 进入目录：cd [LIFE_INDEX_PATH]\n2. 获取今天日期：TODAY=\$(date +%Y-%m-%d)\n3. 执行：python tools/search_journals.py --date \$TODAY --limit 100\n4. 如果有日志，生成日报并推送给用户\n5. 如果无日志，告知用户今日无记录\n\n日报格式：\n【Life Index 日报】\$TODAY\n📝 今日概要：[2-3句话总结]\n⚡ 要点速览：[3-5个要点]\n💡 AI建议：[1-3条建议]" \
  --announce \
  --timeout 120
```

**注意**:
- 将`[LIFE_INDEX_PATH]`替换为实际路径
- 如果路径中有空格，需要转义

**请反馈**:
- 命令是否执行成功: ✅/❌
- 错误信息（如有）: ___

---

### 测试4.2: 手动触发日报任务

**请执行**:
```bash
openclaw cron run life-index-daily-report
```

**观察**:
- 任务是否开始执行（可能需要等待几秒到几十秒）
- 是否收到日报消息

**请反馈**:
- 任务是否成功执行: ✅/❌
- 执行时间: 约___秒
- 是否收到日报: ✅/❌
- 日报内容是否符合预期: ✅/❌

---

### 测试4.3: 检查执行日志

**请执行**:
```bash
# 查看日报任务的执行历史
openclaw cron runs --id life-index-daily-report

# 或者查看所有任务的执行历史
openclaw cron history --limit 10
```

**请反馈**:
- 是否能查看执行历史: ✅/❌
- 最后一次执行状态: 成功 / 失败
- 失败原因（如有）: ___

---

## Phase 5: 完整配置测试（可选，如果前面都成功）

如果Phase 4成功，继续配置其他任务：

### 测试5.1: 周报任务

```bash
openclaw cron add \
  --name "life-index-weekly-report" \
  --cron "10 22 * * 0" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index周报生成任务。\n\n步骤：\n1. 计算本周一和周日日期\n2. 进入目录：cd [LIFE_INDEX_PATH]\n3. 执行：python tools/search_journals.py --date-from [周一] --date-to [周日] --limit 500\n4. 生成周报并推送给用户" \
  --announce \
  --timeout 180
```

---

### 测试5.2: 索引维护任务

```bash
openclaw cron add \
  --name "life-index-index-maintenance" \
  --cron "50 23 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行Life Index索引维护。\n\n步骤：\n1. 进入目录：cd [LIFE_INDEX_PATH]\n2. 执行：python tools/build_index.py\n3. 静默完成，无需通知用户" \
  --timeout 600
```

**注意**: 索引维护任务不需要`--announce`，静默执行

---

## 问题记录模板

如果在测试中遇到问题，请按以下格式记录：

```markdown
## 问题记录

**Phase**: ___（如 4.1）

**现象**: ___（描述发生了什么）

**错误信息**: ___（完整的错误输出）

**已尝试的解决方案**: ___

**需要帮助**: ___（需要我提供什么支持）
```

---

## 测试完成标准

| 检查项 | 状态 |
|--------|------|
| OpenClaw cron功能正常 | ⬜ |
| 能创建定时任务 | ⬜ |
| 能手动触发任务 | ⬜ |
| Life Index工具可访问 | ⬜ |
| 日报定时任务配置成功 | ⬜ |
| 日报任务能生成并推送 | ⬜ |

---

## 下一步行动

根据测试结果：

- **如果全部通过**: 我们将文档标记为"已验证"，并推广给其他用户
- **如果部分失败**: 我将根据错误信息优化模板
- **如果完全失败**: 我们需要重新评估方案

---

**请从Phase 1开始测试，每完成一个阶段请反馈结果，我们再决定如何继续。**
