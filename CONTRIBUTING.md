# Contributing to Life Index

[English](#english-version) | [简体中文](#中文版本)

---

<a name="english-version"></a>
## English Version

Thank you for your interest in contributing to Life Index!

### Project Overview

Life Index is an Agent-first personal journaling system that provides Agent Skill capabilities for OpenClaw. Before contributing, please read the following documents to understand the project philosophy:

- **[docs/HANDBOOK.md](docs/HANDBOOK.md)** - Project vision and core principles
- **[AGENTS.md](AGENTS.md)** - Project context and development conventions
- **[docs/AGENT.md](docs/AGENT.md)** - Agent execution instructions

### Development Environment Setup

#### System Requirements

- **Python 3.11+**
- **Git**
- Cross-platform support: Windows / macOS / Linux

#### Setup Steps

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/Life-Index.git
cd Life-Index

# 2. Install dependencies (optional: semantic search)
pip install -r tools/requirements.txt

# 3. Run tests
python -m pytest tests/unit/ -v
```

### Development Guidelines

#### Agent-First Principle

Before developing a new feature, ask yourself:

> **Is a specialized tool necessary? Can the Agent accomplish this through natural language?**

Conditions for developing specialized tools:
1. **Atomicity requirement**: Operation must succeed completely or fail completely
2. **Accuracy requirement**: Requires precise calculation or validation
3. **Repeatability requirement**: High-frequency deterministic operations

See [HANDBOOK.md - Agent-First Principle](docs/HANDBOOK.md) for details.

#### Code Style

- **Python**: Use type annotations, follow PEP 8
- **Path handling**: Use `pathlib.Path` consistently
- **Encoding**: All files use UTF-8
- **Naming**: Functions/variables use `snake_case`, classes use `PascalCase`

See [AGENTS.md - Code Style Guide](AGENTS.md) for details.

#### Tool Development Standards

1. **Tool location**: `tools/` directory
2. **Invocation method**: CLI interface (argparse)
3. **Return format**: Standard JSON
4. **Documentation update**: Sync update `SKILL.md` and `docs/API.md`

```python
# Standard tool template
#!/usr/bin/env python3
"""
Tool description docstring
"""
import argparse
import json
from typing import Dict, Any

def main():
    parser = argparse.ArgumentParser(description='Tool description')
    parser.add_argument('--data', type=str, help='JSON data')
    args = parser.parse_args()
    
    result = {"success": True, "data": {}}
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

#### Documentation Maintenance

This project follows the **SSOT (Single Source of Truth)** principle. When modifying code, please update related documentation:

| Modification Type | Documents to Update |
|-------------------|---------------------|
| Workflow logic | `docs/AGENT.md` |
| Tool interface | `SKILL.md` + `docs/API.md` + `docs/CHANGELOG.md` |
| Architecture/Principles | `docs/HANDBOOK.md` + `docs/CHANGELOG.md` |
| Architecture decisions | `docs/adr/` (create new ADR) |

### Submitting Code

#### Branch Naming

- `feature/feature-name` - New features
- `fix/issue-description` - Bug fixes
- `docs/doc-update` - Documentation changes

#### Commit Message Format

```
<type>: <subject>

<body>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation update
- `refactor`: Code refactoring
- `test`: Test related
- `chore`: Build/tooling

Example:
```
feat: add automatic attachment detection

- Extract file paths from content automatically
- Validate file existence
- Copy files to attachments directory
```

#### Pull Request Process

1. Create a feature branch
2. Write code and tests
3. Update related documentation
4. Submit PR with change description
5. Wait for code review

### Testing

#### Unit Tests

```bash
# Run all unit tests
python -m pytest tests/unit/ -v

# Run specific test file
python -m pytest tests/unit/test_write_journal.py -v
```

#### E2E Tests

E2E tests are executed by the Agent, reading test cases from `tests/e2e/*.yaml`.

### Getting Help

- **Discussions**: [GitHub Discussions](https://github.com/DrDexter6000/Life-Index/discussions)
- **Bug Reports**: [GitHub Issues](https://github.com/DrDexter6000/Life-Index/issues)
- **Feature Requests**: [GitHub Issues](https://github.com/DrDexter6000/Life-Index/issues/new?template=feature_request.md)

### License

By submitting code, you agree that your contributions will be licensed under the Apache-2.0 License.

---

<a name="中文版本"></a>
## 中文版本

感谢您有兴趣为 Life Index 做出贡献！

### 项目概述

Life Index 是一个 Agent-first 的个人日志系统，为 OpenClaw 提供 Agent Skill 能力。在开始贡献之前，请先阅读以下文档了解项目理念：

- **[docs/HANDBOOK.md](docs/HANDBOOK.md)** - 项目愿景和核心原则
- **[AGENTS.md](AGENTS.md)** - 项目上下文和开发约定
- **[docs/AGENT.md](docs/AGENT.md)** - Agent 执行指令

### 开发环境设置

#### 系统要求

- **Python 3.11+**
- **Git**
- 跨平台支持：Windows / macOS / Linux

#### 设置步骤

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/YOUR_USERNAME/Life-Index.git
cd Life-Index

# 2. 安装依赖（可选：语义搜索）
pip install -r tools/requirements.txt

# 3. 运行测试
python -m pytest tests/unit/ -v
```

### 开发指南

#### Agent-First 原则

在开发新功能前，请先问自己：

> **这个功能是否必须开发专用工具？Agent 能否通过自然语言完成？**

开发专用工具的条件：
1. **原子性要求**：操作必须全部成功或全部失败
2. **准确性要求**：需要精确计算或验证
3. **重复性要求**：高频调用的确定性操作

详见 [HANDBOOK.md - Agent-First 原则](docs/HANDBOOK.md)。

#### 代码风格

- **Python**: 使用类型注解，遵循 PEP 8
- **路径处理**: 统一使用 `pathlib.Path`
- **编码**: 所有文件使用 UTF-8
- **命名**: 函数/变量用 `snake_case`，类用 `PascalCase`

详见 [AGENTS.md - 代码风格指南](AGENTS.md)。

#### 工具开发规范

1. **工具位置**: `tools/` 目录
2. **调用方式**: CLI 接口（argparse）
3. **返回格式**: 标准 JSON
4. **文档更新**: 同步更新 `SKILL.md` 和 `docs/API.md`

```python
# 标准工具模板
#!/usr/bin/env python3
"""
工具说明文档字符串
"""
import argparse
import json
from typing import Dict, Any

def main():
    parser = argparse.ArgumentParser(description='工具描述')
    parser.add_argument('--data', type=str, help='JSON 数据')
    args = parser.parse_args()
    
    result = {"success": True, "data": {}}
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

#### 文档维护

本项目遵循 **SSOT（单一事实来源）** 原则。修改代码时，请同步更新相关文档：

| 修改类型 | 需更新文档 |
|---------|-----------|
| 工作流逻辑 | `docs/AGENT.md` |
| 工具接口 | `SKILL.md` + `docs/API.md` + `docs/CHANGELOG.md` |
| 架构/原则 | `docs/HANDBOOK.md` + `docs/CHANGELOG.md` |
| 架构决策 | `docs/adr/` (新建 ADR) |

### 提交代码

#### 分支命名

- `feature/功能名称` - 新功能
- `fix/问题描述` - Bug 修复
- `docs/文档更新` - 文档修改

#### Commit 消息格式

```
<type>: <subject>

<body>
```

类型：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建/工具

示例：
```
feat: 添加附件自动检测功能

- 从 content 自动提取文件路径
- 验证文件存在性
- 自动复制到 attachments 目录
```

#### Pull Request 流程

1. 创建功能分支
2. 编写代码和测试
3. 更新相关文档
4. 提交 PR，描述变更内容
5. 等待代码审查

### 测试

#### 单元测试

```bash
# 运行所有单元测试
python -m pytest tests/unit/ -v

# 运行特定测试文件
python -m pytest tests/unit/test_write_journal.py -v
```

#### E2E 测试

E2E 测试由 Agent 执行，读取 `tests/e2e/*.yaml` 测试用例。

### 获取帮助

- **问题讨论**: [GitHub Discussions](https://github.com/DrDexter6000/Life-Index/discussions)
- **Bug 报告**: [GitHub Issues](https://github.com/DrDexter6000/Life-Index/issues)
- **功能建议**: [GitHub Issues](https://github.com/DrDexter6000/Life-Index/issues/new?template=feature_request.md)

### 许可证

提交代码即表示您同意您的贡献将在 Apache-2.0 许可证下授权。