# Life Index 定时任务指南 v3

> **核心理念**: 意图驱动（Intention-Driven），能力适配（Capability-Adaptive）
> **版本**: v3.0 | **更新**: 2026-03-12

---

## 一、架构变革说明

### 1.1 问题背景

v2版本的定时任务设计假设Agent具备以下能力：
- 文件系统访问（执行`python tools/...`）
- 环境上下文保持（知道技能安装位置）
- 渠道推送能力（直接推送到IM软件）

**实际验证**（OpenClaw平台）：
- ❌ 4/5定时任务因"隔离环境"失败
- ❌ 渠道推送因"缺乏配置上下文"失败

### 1.2 v3核心变革

| 维度 | v2（失败） | v3（目标） |
|------|-----------|-----------|
| **任务描述** | 详细bash命令 | 意图声明（做什么） |
| **执行方式** | Agent执行shell | Agent选择适配模式 |
| **推送渠道** | 硬编码渠道名 | 标准消息格式 |
| **泛用性** | 假设Agent能力强 | 探测Agent实际能力 |

---

## 二、意图契约层（Intent Contract）

Life Index只声明**"做什么"**和**"何时做"**，不规定**"怎么做"**。

### 2.1 日报任务意图

```yaml
# Life Index 日报 - 意图契约
task_id: daily-report
intent: "每日晚间向用户汇报今日日志记录情况"
triggers:
  - type: time
    value: "22:00"  # 建议时间，Agent可调整
    timezone: user_local
  - type: user_request
    phrases: ["日报", "daily report", "今日总结"]

data_requirements:
  - source: today_journals
    description: "今日（0:00-当前时间）的所有日志"
    fields: [title, content, topic, tags, abstract]

output_spec:
  format: "结构化日报"
  sections:
    - summary: "2-3句话总结今日核心"
    - highlights: "3-5个要点，每点≤15字"
    - suggestions: "1-3条AI建议"
  token_budget: 200
  
delivery:
  priority: ["user_visible", "persistent"]  # 必须用户可见，建议持久化
  channels: []  # Agent自行决定可用渠道
```

### 2.2 关键原则

**Agent的责任**:
1. 解析意图（理解"日报"是什么）
2. 探测能力（我能访问文件吗？我有定时器吗？）
3. 选择模式（原生Cron/外部触发/手动）
4. 适配执行（用我能做到的方式实现意图）

**Life Index不提供**:
- ❌ bash命令
- ❌ 具体文件路径
- ❌ 渠道Webhook配置
- ❌ 环境变量要求

---

## 三、执行适配层（Execution Modes）

Agent根据**自身能力检测报告**选择执行模式。

### 3.1 模式A: 原生Cron模式

**适用Agent**: OpenClaw, Claude Desktop（带Cron插件）, 其他支持Agent级定时任务的平台

**能力要求**:
- ✅ Agent内置Cron/定时器API
- ✅ 定时任务可访问技能工具
- ✅ 保持执行上下文

**Agent实现方式**:
```
Agent: "我支持原生Cron，我将：
1. 解析daily-report意图
2. 注册定时任务：每天22:00
3. 任务执行时调用Life Index工具链"
```

### 3.2 模式B: 外部触发模式

**适用Agent**: 无内置Cron，但支持Webhook/事件触发

**能力要求**:
- ✅ 支持接收外部HTTP请求
- ✅ 或支持操作系统级定时任务（用户自己设置）

**Agent实现方式**:
```
用户: "我的Agent没有Cron，怎么办？"

Agent: "我将提供两种外部触发方案：

方案1 - 系统Cron + Webhook:
- 你设置系统Cron: 0 22 * * * curl {webhook_url}
- 我暴露HTTP端点接收触发
- 收到触发后执行日报生成

方案2 - 日历提醒 + 手动触发:
- 你在日历设置每日22:00提醒
- 点击提醒时对我说'生成日报'
- 我立即执行日报生成"
```

### 3.3 模式C: 纯手动模式

**适用Agent**: 无定时能力，也无Webhook能力

**能力要求**:
- ✅ 仅需基础对话能力

**Agent实现方式**:
```
Agent: "我的平台不支持任何定时功能。
建议方案：
1. 你设置手机闹钟每天22:00
2. 闹钟响起时对我说'生成日报'
3. 我立即为你生成

或者：
- 你想看日报时随时说'生成日报'"
```

---

## 四、消息标准格式（Delivery Abstraction）

不直接推送到特定渠道，而是生成**标准结构化消息**，由Agent决定如何投递。

### 4.1 标准消息结构

```json
{
  "message_type": "life_index_report",
  "report_type": "daily",
  "timestamp": "2026-03-12T22:00:00",
  "content": {
    "title": "【Life Index 日报】2026-03-12",
    "sections": [
      {
        "type": "summary",
        "emoji": "📝",
        "title": "今日概要",
        "content": "今日专注 Life Index 架构优化..."
      },
      {
        "type": "highlights",
        "emoji": "⚡",
        "title": "要点速览",
        "items": ["完成定时任务架构重构", "新增能力探测层设计"]
      }
    ]
  },
  "delivery_hints": {
    "priority": "normal",
    "persist": true,
    "target_user": true,
    "avoid_channels": []  // Agent可根据策略排除某些渠道
  }
}
```

### 4.2 Agent投递决策

```
收到标准消息后，Agent决策：

IF 我有IM推送能力 AND 用户配置了渠道:
  → 推送到IM + 主会话展示
  
ELSE IF 我有主会话:
  → 在主会话展示
  → 建议用户："日报已生成，建议固定时间查看"
  
ELSE:
  → 保存到文件
  → 下次用户活跃时主动展示："你有一条未读日报"
```

---

## 五、能力探测协议（Capability Discovery）

Agent首次加载Life Index时，执行能力自检并报告。

### 5.1 能力报告格式

```json
{
  "agent_platform": "OpenClaw",
  "version": "2.1.0",
  "capabilities": {
    "cron": {
      "available": true,
      "type": "agent_native",
      "constraints": ["max_10_tasks", "no_subminute"]
    },
    "file_system": {
      "available": true,
      "access": "sandboxed",
      "working_directory": "/app/skills/life-index"
    },
    "shell": {
      "available": false
    },
    "push_notification": {
      "available": true,
      "channels": ["main_session", "webhook"],
      "webhook_configurable": true
    },
    "persistent_storage": {
      "available": true,
      "type": "key_value_store"
    }
  },
  "selected_mode": "native_cron",
  "adaptations": [
    "using_absolute_paths",
    "using_wrapper_script",
    "webhook_for_external_push"
  ]
}
```

### 5.2 Life Index的适配响应

根据能力报告，Life Index提供适配方案：

| 能力组合 | 推荐模式 | 适配措施 |
|---------|---------|---------|
| Cron✅ File✅ Shell❌ | 原生Cron | 提供Python API调用方式，无需shell |
| Cron❌ File✅ Webhook✅ | 外部触发 | 提供webhook端点，用户设置系统cron |
| Cron❌ File❌ | 纯手动 | 优化手动触发体验，提供快捷指令 |

---

## 六、OpenClaw专项适配方案

基于实测失败案例，为OpenClaw提供具体适配。

### 6.1 OpenClaw能力画像

```yaml
platform: OpenClaw
tested_version: "2.x"

capabilities:
  cron: 
    available: true
    notes: "Agent级Cron，隔离环境执行"
  file_system:
    available: true
    notes: "沙箱内可访问技能目录"
  shell:
    available: false
    notes: "定时任务上下文无法直接执行bash"
  environment:
    persistence: "limited"
    notes: "定时任务缺少安装时环境变量"

failures_observed:
  - "指令不清晰（隔离环境）"
  - "channel推送错误"
```

### 6.2 适配方案：Wrapper API模式

**核心问题**: OpenClaw的定时任务无法直接执行`python tools/search_journals.py`

**解决方案**: Life Index提供HTTP Wrapper API

```python
# Life Index提供内置API服务器（可选组件）
# 当Agent报告"shell: false"时启用

# Agent定时任务只需发送HTTP请求
POST /api/v1/tasks/daily-report
Headers: {"Authorization": "Bearer {skill_token}"}
Body: {"date": "2026-03-12", "timezone": "Asia/Shanghai"}

# Life Index内部执行工具链，返回标准消息格式
Response: {message_object}

# Agent接收响应，决定如何展示
```

**优势**:
- ✅ 无需shell访问
- ✅ 环境变量在API服务器中保持
- ✅ 统一入口，简化定时任务配置
- ✅ Agent只需配置HTTP调用

### 6.3 OpenClaw配置示例

```yaml
# Agent视角的配置（不再是自然语言描述）
skill: life-index
tasks:
  - id: daily-report
    enabled: true
    trigger:
      type: cron
      schedule: "0 22 * * *"
    action:
      type: http
      endpoint: "http://localhost:{port}/api/v1/tasks/daily-report"
      method: POST
    delivery:
      channels: [main_session]  # OpenClaw只支持主会话
      persist: true
```

---

## 七、实施路线图

### Phase 1: 文档重构（立即）
- [ ] 重写SCHEDULE.md，分离意图与机制
- [ ] 创建能力探测协议规范
- [ ] 定义标准消息格式

### Phase 2: 运行时适配层（1-2周）
- [ ] 实现Agent能力探测接口
- [ ] 为OpenClaw提供Wrapper API
- [ ] 实现三种执行模式适配器

### Phase 3: 生态集成（2-4周）
- [ ] 与OpenClaw官方对接适配方案
- [ ] 为其他主流Agent平台提供适配
- [ ] 建立Agent能力数据库

---

## 八、设计原则坚持

本次变革**不违背**Agent-first原则：

| 原则 | v3如何坚持 |
|------|-----------|
| **Agent自主** | Agent选择执行模式，Life Index只声明意图 |
| **不硬编码** | 无特定Agent配置，只有能力探测响应 |
| **单层透明** | 新增API层是可选适配器，非强制中间层 |
| **极简主义** | 纯手动模式依然可用，功能渐进增强 |

---

**文档结束**
