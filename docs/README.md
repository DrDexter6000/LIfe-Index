# Life Index v3

> 一个 Agent-first 的个人日志系统，通过自然语言交互实现数字化人生记录。

⚠️ **系统边界**: 本项目是赋能 Agent 协助**用户**记录日志的工具，与 Agent 自身的核心记忆体系无关。Agent 不应将本项目的文件用于自身记忆管理。

---

## 快速导航

| 文档 | 用途 | 读者 |
|------|------|------|
| [HANDBOOK.md](./HANDBOOK.md) | 项目全貌：愿景、原则、架构、术语 | 人类（开发者、用户） |
| [AGENT.md](./AGENT.md) | Agent 指令：工作流、工具接口、示例 | AI Agent（直接执行） |
| [CHANGELOG.md](./CHANGELOG.md) | 决策变更历史 | 所有协作者 |
| [Development-Roadmap-v1.md](./Development-Roadmap-v1.md) | 开发阶段与里程碑 | 项目经理 |

---

## 一分钟开始

### 作为用户

开启新对话并提供：
```
请阅读 docs/AGENT.md，作为我的 Life Index 日志助手。
```

### 作为开发者

阅读顺序：
1. [HANDBOOK.md](./HANDBOOK.md) - 理解设计哲学
2. [CHANGELOG.md](./CHANGELOG.md) - 了解最新决策
3. [AGENT.md](./AGENT.md) - 查看具体实现

---

## 当前状态

- **版本**: v0.1.0
- **阶段**: Phase 5 - 体验优化（已完成）
- **最后更新**: 2026-03-08
- **最新变更**: [2026-03-08] 天气自动填充与确认流程

### 文档职责说明（SSOT）

| 信息类型 | 单一真相来源 | 说明 |
|---------|-------------|------|
| 项目版本/阶段 | **本文件** | 其他文档引用，不重复声明 |
| 架构规范/工具列表 | [HANDBOOK.md](./HANDBOOK.md) | 设计原则、目录结构、接口定义 |
| 工作流/CLI示例 | [AGENT.md](./AGENT.md) | Agent 直接执行的指令 |
| 当前任务/下一步 | [dev-progress.md](./dev-progress.md) | 动态更新，记录进行中任务 |
| 决策历史 | [CHANGELOG.md](./CHANGELOG.md) | 变更记录，不重复技术细节 |
| 里程碑规划 | [Development-Roadmap-v1.md](./Development-Roadmap-v1.md) | 阶段目标，不重复当前状态 |

---

## 核心原则（摘自 HANDBOOK）

- **Agent-first**: 能由 Agent 完成的，不开发专用工具
- **数据主权**: 100% 本地存储，人可读的开放格式
- **单层透明**: 用户 ↔ Agent ↔ 文件系统，无中间层

---

**Life Index** © 2026 | 数字人生，可靠记录
