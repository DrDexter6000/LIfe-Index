# Life Index 定时任务指南

> **版本**: v3.0 | **更新**: 2026-03-13  
> **本文档**: 同时作为**配置手册**（人类阅读）和**执行指令**（Agent定时任务使用）

---

## 📋 快速判断：你的 Agent 支持哪种模式？

| 如果你的 Agent 支持... | 使用模式 | 跳转章节 |
|---------------------|---------|---------|
| 内置定时任务（Cron/Scheduler）+ 可访问技能目录 | **自动模式** | [模式一：定时任务自动配置](#模式一-定时任务自动配置) |
| 不支持定时任务，或完全隔离环境 | **手动模式** | [模式二：手动定期执行](#模式二-手动定期执行) |

---

## 模式一：定时任务自动配置

### 1.1 OpenClaw 平台配置（推荐）

**路径说明**：假设 Life Index 技能安装在 OpenClaw 工作目录下，相对路径为：
```
openclaw/workspace/skills/life-index/
```
（实际路径如：`Z:\home\dexter\.openclaw\workspace\skills\life-index`）

#### 任务 1：日报推送
```
名称: life-index-daily-report
时间: 0 22 * * * (每天 22:00)
指令:
```

```bash
cd openclaw/workspace/skills/life-index && python -m tools.search_journals --date $(date +%Y-%m-%d) --limit 100 --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not data.get('l2_results') and not data.get('merged_results'):
    print('📭 今日暂无日志记录')
    sys.exit(0)

results = data.get('merged_results', data.get('l2_results', []))
if not results:
    print('📭 今日暂无日志记录')
    sys.exit(0)

print(f'📊 Life Index 日报 ({$(date +%Y-%m-%d)})')
print(f'今日记录 {len(results)} 篇日志\\n')
for r in results[:3]:
    print(f'• {r.get(\"title\", \"无标题\")}')
if len(results) > 3:
    print(f'... 还有 {len(results)-3} 篇')
"
```

#### 任务 2：周报推送
```
名称: life-index-weekly-report
时间: 10 22 * * 0 (每周日 22:10)
指令:
```

```bash
cd openclaw/workspace/skills/life-index && python -m tools.search_journals --date-from $(date -d '6 days ago' +%Y-%m-%d) --date-to $(date +%Y-%m-%d) --limit 500 --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('merged_results', data.get('l2_results', []))

week_start = '$(date -d '6 days ago' +%Y-%m-%d)'
week_end = '$(date +%Y-%m-%d)'

if not results:
    print(f'📭 {week_start} ~ {week_end} 本周暂无日志')
    sys.exit(0)

print(f'📊 Life Index 周报 ({week_start} ~ {week_end})')
print(f'本周共记录 {len(results)} 篇日志\\n')

topics = {}
for r in results:
    topic = r.get('metadata', {}).get('topic', ['未分类'])
    if isinstance(topic, list):
        topic = topic[0] if topic else '未分类'
    topics[topic] = topics.get(topic, 0) + 1

print('📈 主题分布:')
for t, c in sorted(topics.items(), key=lambda x: -x[1])[:3]:
    print(f'  {t}: {c}篇')
"
```

#### 任务 3：月报生成
```
名称: life-index-monthly-report
时间: 30 18 28-31 * * (每月末 18:30)
指令:
```

```bash
cd openclaw/workspace/skills/life-index && python tools/generate_abstract.py --month $(date +%Y-%m) --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list) and len(data) > 0:
    d = data[0]
    print(f'📄 月报已生成: {d.get(\"abstract_path\", \"unknown\")}')
    print(f'   包含 {d.get(\"journal_count\", 0)} 篇日志')
elif isinstance(data, dict) and data.get('abstract_path'):
    print(f'📄 月报已生成: {data.get(\"abstract_path\")}')
    print(f'   包含 {data.get(\"journal_count\", 0)} 篇日志')
else:
    print('⚠️ 月报生成可能失败，请检查')
"
```

#### 任务 4：索引维护
```
名称: life-index-index-maintenance
时间: 50 23 * * * (每天 23:50)
指令:
```

```bash
cd openclaw/workspace/skills/life-index && python tools/build_index.py 2>/dev/null && echo "✓ 索引更新完成" || echo "✗ 索引更新失败"
```

---

### 1.2 其他 Agent 平台配置

如果你的 Agent 不是 OpenClaw，请按以下步骤配置：

#### Step 1: 确定技能路径
```bash
# 在你的 Agent 环境中执行，找到 Life Index 安装位置
find ~ -name "life-index" -type d 2>/dev/null | head -5
# 或使用 which 找到工具位置
which python  # 确认 Python 路径
```

#### Step 2: 测试基础命令
在定时任务中先测试是否能执行：
```bash
cd [你的技能路径] && python -m tools.search_journals --help
```
如果失败，说明路径或 Python 环境问题。

#### Step 3: 修改上述模板
将 `openclaw/workspace/skills/life-index` 替换为你的实际路径。

---

## 模式二：手动定期执行

如果你的 Agent **不支持定时任务**，或环境**完全隔离**，请使用手动模式：

### 2.1 日报查看（每天睡前）

**用户说**: "查看今日日志" / "今天有什么记录"

**Agent 执行**:
```bash
python -m tools.search_journals --date $(date +%Y-%m-%d) --limit 100
```

### 2.2 周报生成（每周日）

**用户说**: "生成本周报告"

**Agent 执行**:
```bash
# 获取本周一到今天
python -m tools.search_journals --date-from $(date -d '6 days ago' +%Y-%m-%d) --date-to $(date +%Y-%m-%d) --limit 500
```

### 2.3 月报生成（每月末）

**用户说**: "生成本月总结"

**Agent 执行**:
```bash
python tools/generate_abstract.py --month $(date +%Y-%m)
```

**输出文件位置**:
- `Journals/YYYY/MM/monthly_report_YYYY-MM.md`

### 2.4 索引维护（偶尔手动）

当搜索变慢或数据不完整时执行：

```bash
python tools/build_index.py
```

---

## 🔧 故障排查

### 问题 1："找不到工具" / "No module named tools"

**原因**: 定时任务的执行目录不对

**解决**:
1. 在指令开头加上 `cd` 命令：
   ```bash
   cd openclaw/workspace/skills/life-index && python ...
   ```
2. 或者使用绝对路径（从你的实际路径修改）：
   ```bash
   python /home/dexter/.openclaw/workspace/skills/life-index/tools/search_journals.py ...
   ```

### 问题 2：Channel 推送失败

**原因**: Agent 不知道推送到哪个 Channel

**解决**:
1. **OpenClaw**: 在定时任务设置中选择要推送的 Channel
2. **其他平台**: 查看平台文档，确认推送方式
3. **备用方案**: 不依赖推送，改为生成文件并记录路径，用户下次对话时主动告知

### 问题 3："没有今日日志" 但用户说记录过

**原因**: 时区问题，定时任务认为的"今天"和用户时区不同

**解决**:
- 检查你的 Agent 时区设置
- 尝试调整定时任务时间（如从 22:00 改为 14:00 测试）

### 问题 4：Cron 表达式不生效

**常见错误**:
```
# 错误：秒级精度（Cron 是分钟级）
0 0 22 * * *  # 6个字段，最后一个是年（可选），秒不支持

# 正确
0 22 * * *    # 每天 22:00
```

**验证工具**: 使用在线 Cron 解析器验证表达式。

---

## 📊 任务速查表

| 任务 | 频率 | Cron | 指令核心 |
|------|------|------|---------|
| 日报 | 每天 | `0 22 * * *` | `search_journals --date TODAY` |
| 周报 | 每周日 | `10 22 * * 0` | `search_journals --date-from 6天前 --date-to 今天` |
| 月报 | 每月末 | `30 18 28-31 * *` | `generate_abstract --month YYYY-MM` |
| 索引维护 | 每天 | `50 23 * * *` | `build_index.py` |

**Token 预算参考**:
- 日报: ~200 tokens
- 周报: ~500 tokens
- 月报: ~1000 tokens（只推送摘要，完整内容在文件）

---

## 📁 相关文档

- **日报详细指南**: [scenarios/daily-report.md](./scenarios/daily-report.md)
- **周报详细指南**: [scenarios/weekly-report.md](./scenarios/weekly-report.md)
- **月报详细指南**: [scenarios/monthly-report.md](./scenarios/monthly-report.md)
- **年报详细指南**: [scenarios/yearly-report.md](./scenarios/yearly-report.md)
- **索引维护指南**: [scenarios/index-update.md](./scenarios/index-update.md)

---

**文档结束**
