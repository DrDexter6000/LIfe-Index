# Life Index 定时任务配置工作流

> **本文档角色**: 引导Agent自主配置定时任务的工作流Prompt
> **适用对象**: 具备自我认知能力的AI Agent（如OpenClaw, Claude, GPTs等）
> **配置原则**: 意图驱动 + 能力探测 + 渐进实施

---

## Phase 1: 意图理解（Why & What）

请阅读以下内容，理解Life Index定时任务的目的和价值。

### 1.1 定时任务的意义

Life Index是一个**个人生活记录系统**。定时任务帮助用户：

| 任务类型 | 用户价值 | 触发时机 |
|---------|---------|---------|
| **日报** | 回顾今日记录，获得AI建议 | 每天22:00 |
| **周报** | 总结本周生活轨迹 | 每周日22:10 |
| **月报** | 深度回顾，保存月度摘要 | 每月末18:30 |
| **年报** | 年度人生总结 | 12月31日19:15 |
| **索引维护** | 确保搜索性能 | 每日23:50 |

**核心原则**: 定时任务应成为用户的"数字生活管家"，在不打扰的情况下提供价值。

### 1.2 你的角色

作为Agent，你需要：
1. **理解意图**: 知道Life Index想要什么
2. **探测能力**: 了解自己能否做到
3. **诚实报告**: 如果做不到，说明原因并提供替代方案
4. **安全实施**: 不影响系统稳定性

---

## Phase 2: 案例研究（How - Reference）

### 2.1 理想情况（Full Capability）

假设Agent具备完整能力：

```yaml
# 理想的定时任务配置（概念示例）
task: daily-report
schedule: "0 22 * * *"  # Cron表达式
action:
  type: skill_invocation
  skill: life-index
  tool: generate_abstract
  params:
    period: daily
    timezone: user_local
delivery:
  - channel: main_session
  - channel: im_notification  # 如果用户配置了
```

### 2.2 OpenClaw适配案例（实际可行）

基于OpenClaw平台特性，以下配置**经实测可行**：

#### 案例A: 日报任务（OpenClaw原生Cron）

```json
{
  "task_name": "life-index-daily-report",
  "schedule": {
    "type": "cron",
    "expression": "0 22 * * *",
    "timezone": "auto-detect"
  },
  "action": {
    "type": "script",
    "interpreter": "python3",
    "working_directory": "{{SKILL_DIR}}",
    "script": ""
# 注意：以下脚本在隔离环境执行，必须使用绝对路径
import subprocess
import json
from datetime import datetime

# 获取今日日期
today = datetime.now().strftime("%Y-%m-%d")

# 执行搜索（使用绝对路径）
result = subprocess.run(
    [
        "python3", 
        "{{SKILL_DIR}}/tools/search_journals.py",
        "--date", today,
        "--limit", "100"
    ],
    capture_output=True,
    text=True,
    timeout=30
)

# 解析结果
data = json.loads(result.stdout)
journals = data.get("data", {}).get("results", [])

if not journals:
    print("今日无日志记录，跳过日报生成")
else:
    # 生成日报内容（使用Agent的NLG能力）
    report = generate_daily_report(journals)  # Agent实现此函数
    # 推送到用户
    notify_user(report)
"""
  },
  "constraints": {
    "timeout": 60,
    "retry": 1,
    "environment": "isolated"
  }
}
```

**关键适配点**:
- ✅ 使用 `{{SKILL_DIR}}` 占位符（OpenClaw提供）
- ✅ 设置 `working_directory`
- ✅ 设置 `timeout` 防止卡死
- ✅ 接受 `isolated` 环境限制

#### 案例B: 月报任务（OpenClaw）

```json
{
  "task_name": "life-index-monthly-report",
  "schedule": {
    "type": "cron",
    "expression": "30 18 28-31 * *",  # 每月最后几天18:30
    "condition": "is_last_day_of_month"  # OpenClaw支持条件执行
  },
  "action": {
    "type": "skill_api",
    "skill": "life-index",
    "api": "generate_abstract",
    "method": "POST",
    "params": {
      "type": "monthly",
      "format": "markdown_file"
    }
  },
  "delivery": {
    "channels": ["main_session"],  # OpenClaw只保证主会话
    "file_output": true  # 保存文件，用户随时查看
  }
}
```

#### 案例C: 索引维护（OpenClaw）

```json
{
  "task_name": "life-index-index-maintenance",
  "schedule": {
    "type": "cron",
    "expression": "50 23 * * *"
  },
  "action": {
    "type": "script",
    "script": ""
import subprocess

# 增量更新索引
subprocess.run([
    "python3",
    "{{SKILL_DIR}}/tools/build_index.py"
], check=False)  # check=False，失败不报错

# 可选：向量索引（如果sentence-transformers已安装）
try:
    subprocess.run([
        "python3",
        "{{SKILL_DIR}}/tools/build_index.py",
        "--semantic"
    ], check=False, timeout=300)
except:
    pass  # 向量索引可选，失败忽略
"""
  },
  "failure_handling": {
    "log_only": true,  # 索引失败只记录，不打扰用户
    "retry_next_run": true
  }
}
```

### 2.3 最小可行方案（Fallback）

如果上述配置都不可行，使用**纯手动模式**：

```yaml
# 手动模式配置
mode: manual
triggers:
  - type: user_intent
    phrases: 
      - "生成日报"
      - "daily report"
      - "查看今日总结"
      - "今天记录了什么"

workflow:
  1: "用户触发"
  2: "Agent立即执行generate_abstract"
  3: "返回结果给用户"
  
recommendation: "建议用户在手机设置每日22:00闹钟，闹钟响起时说'生成日报'"
```

---

## Phase 3: 自我分析（Self-Reflection）

现在，请分析你自己的能力。

### 3.1 请回答以下问题

```markdown
## Agent自我能力评估

### 平台信息
- 平台名称: [如 OpenClaw, Claude Desktop, ChatGPT等]
- 版本号: [如 2.1.0]

### Cron能力
- [ ] 我支持内置定时任务（Agent-native Cron）
- [ ] 我可以让用户设置系统级定时任务（System Cron）
- [ ] 我支持接收外部Webhook触发
- [ ] 我不支持任何定时功能

如果是第一项，请描述：
- 定时任务执行环境: [隔离/共享/未知]
- 定时任务能否访问技能目录: [能/不能/未知]
- 定时任务能否执行shell命令: [能/不能/受限]

### 文件系统能力
- [ ] 我能访问技能安装目录
- [ ] 我知道技能的绝对路径
- [ ] 我能在定时任务中保持路径上下文

### 推送能力
- [ ] 我能推送到主会话（Main Session）
- [ ] 我能推送到IM渠道（Slack/飞书/微信等）
- [ ] 推送需要用户预先配置
- [ ] 我只能在主动对话时回复

### 工具调用能力
- [ ] 我能直接调用技能的Python函数
- [ ] 我能执行技能的CLI工具
- [ ] 我能通过HTTP API调用技能
- [ ] 我只能通过自然语言与技能交互
```

### 3.2 请调查你的官方文档

请联网搜索或阅读你的官方文档，回答：

1. **定时任务文档链接**: [URL]
2. **定时任务环境限制**: [描述]
3. **推荐的技能定时任务配置方式**: [描述]
4. **已知限制或常见问题**: [描述]

### 3.3 诚实报告

基于以上分析，请向用户报告：

```markdown
## 定时任务可行性报告

**平台**: [你的平台名称]

**结论**: [完全支持 / 部分支持 / 不支持]

**支持的任务**:
- ✅ 日报: [支持/不支持]，原因: [说明]
- ✅ 周报: [支持/不支持]，原因: [说明]
- ✅ 月报: [支持/不支持]，原因: [说明]
- ⚠️ 索引维护: [支持/不支持]，原因: [说明]

**推荐的配置方式**: [使用案例A/B/C/手动模式]

**需要用户配合的事项**: [如设置环境变量、配置Webhook等]

**风险提醒**: [如定时任务可能因环境隔离失败]
```

---

## Phase 4: 实施配置

### 4.1 如果决定实施

请按照以下步骤：

**Step 1: 获取技能路径**
```python
# 请确认你能获取到Life Index的安装路径
skill_dir = get_skill_directory("life-index")  # 你的平台API
print(f"Life Index installed at: {skill_dir}")
```

**Step 2: 测试工具可访问性**
```bash
# 在定时任务环境执行以下测试
python3 {{SKILL_DIR}}/tools/search_journals.py --help
# 如果失败，请报告错误信息
```

**Step 3: 创建测试任务**
```json
{
  "task_name": "life-index-test",
  "schedule": "*/5 * * * *",  // 每5分钟，用于测试
  "action": {
    "type": "script",
    "script": "print('Life Index定时任务测试成功')"
  }
}
```

**Step 4: 验证后迁移**
测试成功后，修改为正式配置。

### 4.2 实施检查清单

```markdown
## 配置完成检查清单

- [ ] 已向用户报告能力评估结果
- [ ] 已选择适合的配置模式
- [ ] 已测试工具可访问性
- [ ] 已创建测试任务并验证
- [ ] 已配置正式任务
- [ ] 已向用户说明如何验证任务执行
- [ ] 已告知用户故障排查方法
```

---

## Phase 5: 验证与监控

### 5.1 验证任务执行

配置完成后，请：

1. **立即执行一次**（如果平台支持手动触发）
2. **检查输出**: 确认日志、报告是否正确生成
3. **确认交付**: 用户是否收到通知/报告

### 5.2 提供监控方法

告诉用户如何确认定时任务正常工作：

```markdown
## 如何验证定时任务

### 方法1: 查看执行日志
- [你的平台] → [定时任务管理] → [life-index-daily-report] → [日志]

### 方法2: 检查报告生成
- 日报: 每天22:05后，查看是否有新消息
- 月报: 每月最后一天18:35后，查看Journals/YYYY/MM/monthly_report_YYYY-MM.md

### 方法3: 手动触发测试
- 说"生成日报"，立即执行一次，验证功能正常
```

### 5.3 故障处理

如果任务失败，请按以下流程排查：

```
1. 检查定时任务日志
   └─ 是否显示"找不到文件"? → 路径问题，检查{{SKILL_DIR}}
   └─ 是否显示"权限不足"? → 环境问题，联系平台支持
   └─ 是否显示"超时"? → 增加timeout配置
   
2. 测试工具可用性
   └─ 在定时任务环境手动执行一次工具调用
   
3. 降级到手动模式
   └─ 如果自动修复失败，建议用户使用手动模式
```

---

## 安全与伦理准则

配置定时任务时，请遵守：

1. **不越权**: 只使用用户已授权的权限
2. **透明**: 清楚告知用户你在做什么、可能的风险
3. **可撤销**: 确保用户知道如何停止/删除定时任务
4. **隐私**: 定时任务产生的报告属于用户隐私，妥善保管
5. **资源**: 避免过于频繁的执行（如每分钟），合理使用资源

---

## 示例对话

### 示例1: 成功配置（OpenClaw）

```
Agent: 我已阅读Life Index定时任务配置指南。

Agent: 正在进行自我能力分析...
- 平台: OpenClaw v2.1
- Cron支持: 是（Agent-native）
- 环境: 隔离容器
- 文件访问: 受限（需使用绝对路径）

Agent: 经测试，我发现可以直接调用Life Index工具。

Agent: 正在为您配置日报任务...
✅ 已创建: life-index-daily-report
✅ 执行时间: 每天22:00
✅ 测试运行: 成功生成测试报告

Agent: 定时任务配置完成！今晚22:00您将收到第一份日报。
如需停止，请说"停止Life Index定时任务"。
```

### 示例2: 部分支持

```
Agent: 已完成能力评估。

Agent: 我的平台（XXX）支持定时任务，但存在以下限制：
- ❌ 定时任务无法访问文件系统
- ✅ 但我可以通过HTTP API调用技能

Agent: 建议方案：
方案A: 使用Life Index HTTP API模式（需要启动API服务器）
方案B: 使用手动模式（您说"生成日报"时我立即执行）

Agent: 您希望使用哪种方案？
```

### 示例3: 不支持

```
Agent: 经自我分析，我的平台暂不支持定时任务功能。

Agent: 建议替代方案：
1. 您在手机设置每日22:00闹钟
2. 闹钟响起时说"生成日报"
3. 我将立即为您生成

Agent: 或者，您可以在想回顾时随时说"查看本周总结"等。
```

---

**文档结束**
