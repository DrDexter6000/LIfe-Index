# Life Index API 规范

> **本文档职责**: 工具接口规范 SSOT，所有工具的参数、返回值、错误码定义
> **目标读者**: Agent、开发者
> **SSOT 引用**: SKILL.md、AGENTS.md 应引用本文档，不重复定义参数

---

## 通用规范

### 调用方式

所有工具通过 Bash CLI 调用，返回 JSON 格式：

```bash
python tools/{tool_name}.py --data '{json_data}'
```

### 通用返回格式

```json
{
  "success": true|false,
  "data": { ... },
  "error": {
    "code": "E0000",
    "message": "错误信息",
    "details": { ... },
    "recovery_strategy": "ask_user|skip_optional|continue_empty|fail"
  }
}
```

### 错误码分类

| 模块 | 代码范围 | 说明 |
|------|----------|------|
| 通用 | E00xx | 输入错误、权限错误 |
| 文件 | E01xx | 文件不存在、路径错误 |
| 写入 | E02xx | 写入失败、格式错误 |
| 搜索 | E03xx | 索引错误、查询错误 |
| 天气 | E04xx | API 失败、超时 |
| 编辑 | E05xx | 日志不存在、冲突 |
| 索引 | E06xx | 构建失败、损坏 |

---

## write_journal

### 端点

```bash
python tools/write_journal.py --data '<json>'
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| title | string | ✅ | - | 日志标题（≤20字） |
| content | string | ✅ | - | 日志正文（原样保留） |
| date | string | ✅ | - | 日期（ISO 8601: YYYY-MM-DD） |
| location | string | ❌ | "Chongqing, China" | 地点 |
| weather | string | ❌ | 自动查询 | 天气描述 |
| mood | array | ❌ | [] | 心情标签 |
| people | array | ❌ | [] | 相关人物 |
| topic | array | ❌ | [] | 主题分类 |
| project | string | ❌ | "" | 关联项目 |
| tags | array | ❌ | [] | 标签 |
| abstract | string | ❌ | "" | 摘要（≤100字，**Agent生成**） |
| links | array | ❌ | [] | 相关链接 |
| attachments | array | ❌ | [] | 附件列表 |

### 附件对象格式

```json
{
  "source_path": "C:/Users/xxx/file.png",
  "description": "附件说明"
}
```

### 返回值

```json
{
  "success": true,
  "data": {
    "journal_path": "Journals/2026/03/life-index_2026-03-10_001.md",
    "updated_indices": ["主题_work.md", "项目_Life-Index.md"],
    "attachments_processed": [...],
    "location_used": "Beijing, China",
    "location_auto_filled": false,
    "weather_used": "Sunny 25°C",
    "weather_auto_filled": true,
    "needs_confirmation": true,
    "confirmation_message": "日志已保存。地点：Beijing, China；天气：Sunny 25°C。请确认以上信息是否正确？"
  }
}
```

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0001 | 必填参数缺失 | ask_user |
| E0203 | content 为空 | ask_user |
| E0204 | 日期格式无效 | ask_user |
| E0205 | 附件复制失败 | continue |
| E0400 | 天气 API 失败 | skip_optional |

---

## search_journals

### 端点

```bash
python tools/search_journals.py [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | string | ❌ | - | 搜索关键词 |
| topic | string | ❌ | - | 按主题过滤 |
| project | string | ❌ | - | 按项目过滤 |
| tags | string | ❌ | - | 按标签过滤（逗号分隔） |
| date_from | string | ❌ | - | 起始日期 (YYYY-MM-DD) |
| date_to | string | ❌ | - | 结束日期 (YYYY-MM-DD) |
| location | string | ❌ | - | 按地点过滤 |
| weather | string | ❌ | - | 按天气过滤 |
| mood | string | ❌ | - | 按心情过滤（逗号分隔） |
| people | string | ❌ | - | 按人物过滤（逗号分隔） |
| level | int | ❌ | 3 | 搜索层级: 1=索引, 2=元数据, 3=全文 |
| use-index | flag | ❌ | false | 使用 FTS 索引加速 |
| semantic | flag | ❌ | false | 启用语义搜索 |
| semantic-weight | float | ❌ | 0.4 | 语义搜索权重 (0-1) |
| fts-weight | float | ❌ | 0.6 | FTS 搜索权重 (0-1) |
| limit | int | ❌ | 10 | 返回结果数量限制 |

### 返回值

```json
{
  "success": true,
  "data": {
    "query": "重构",
    "total": 5,
    "results": [
      {
        "path": "Journals/2026/03/life-index_2026-03-06_001.md",
        "title": "搜索功能重构",
        "date": "2026-03-06",
        "location": "Chongqing, China",
        "abstract": "完成了搜索架构的重构...",
        "score": 0.85
      }
    ],
    "search_level": 3,
    "search_time_ms": 45
  }
}
```

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0302 | 查询为空 | ask_user |
| E0303 | 无结果 | continue_empty |
| E0300 | 索引不存在 | continue |

---

## edit_journal

### 端点

```bash
python tools/edit_journal.py --journal "<path>" [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| journal | string | ✅ | - | 日志文件路径 |
| set-title | string | ❌ | - | 设置标题 |
| set-date | string | ❌ | - | 设置日期 |
| set-location | string | ❌ | - | 设置地点 |
| set-weather | string | ❌ | - | 设置天气 |
| set-mood | string | ❌ | - | 设置心情（逗号分隔） |
| set-people | string | ❌ | - | 设置人物（逗号分隔） |
| set-tags | string | ❌ | - | 设置标签（逗号分隔） |
| set-project | string | ❌ | - | 设置项目 |
| set-topic | string | ❌ | - | 设置主题（逗号分隔） |
| set-abstract | string | ❌ | - | 设置摘要 |
| append-content | string | ❌ | - | 追加内容到正文 |
| replace-content | string | ❌ | - | 替换整个正文 |
| dry-run | flag | ❌ | false | 模拟运行 |

### 返回值

```json
{
  "success": true,
  "data": {
    "journal_path": "Journals/2026/03/life-index_2026-03-10_001.md",
    "changes": {
      "location": {"old": "Chongqing, China", "new": "Beijing, China"},
      "weather": {"old": "Sunny", "new": "Cloudy"}
    }
  }
}
```

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0500 | 日志不存在 | ask_user |
| E0502 | 字段不识别 | ask_user |
| E0503 | 无变更 | ask_user |

---

## query_weather

### 端点

```bash
python tools/query_weather.py --location "<location>" [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| location | string | ❌ | "Chongqing, China" | 地点名称 |
| lat | float | ❌ | - | 纬度 |
| lon | float | ❌ | - | 经度 |
| date | string | ❌ | "today" | 日期 (YYYY-MM-DD) |

### 返回值

```json
{
  "success": true,
  "data": {
    "location": "Beijing, China",
    "date": "2026-03-10",
    "weather": "Partly cloudy",
    "temperature": {
      "max": 18.5,
      "min": 8.2,
      "unit": "celsius"
    },
    "description": "Partly cloudy 18.5°C/8.2°C"
  }
}
```

### 错误码

| 代码 | 说明 | 恢复策略 |
|------|------|----------|
| E0400 | API 请求失败 | skip_optional |
| E0401 | API 超时 | skip_optional |
| E0402 | 地点未找到 | ask_user |

---

## generate_abstract

### 端点

```bash
python tools/generate_abstract.py [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| month | string | ❌ | - | 生成月度摘要 (YYYY-MM) |
| year | int | ❌ | - | 生成年度摘要 (YYYY) |
| all-months | flag | ❌ | false | 与 year 一起使用，批量生成全年 |
| dry-run | flag | ❌ | false | 预览模式 |

### 返回值

```json
{
  "success": true,
  "data": {
    "type": "monthly",
    "period": "2026-03",
    "output_path": "Journals/2026/03/monthly_abstract.md",
    "stats": {
      "total_journals": 15,
      "by_topic": {"work": 8, "life": 5, "learn": 2}
    }
  }
}
```

---

## build_index

### 端点

```bash
python tools/build_index.py [options]
```

### 参数

| 名称 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| rebuild | flag | ❌ | false | 全量重建索引 |
| validate | flag | ❌ | false | 验证索引完整性 |

### 返回值

```json
{
  "success": true,
  "data": {
    "journals_indexed": 45,
    "index_path": ".vector_index/journals_fts.db",
    "build_time_ms": 1200,
    "validation": {
      "status": "passed",
      "issues": []
    }
  }
}
```

---

## Topic 分类定义

| Topic | 含义 | 示例场景 |
|-------|------|----------|
| `work` | 工作/职业 | 项目进展、会议、职业发展 |
| `learn` | 学习/成长 | 读书笔记、课程学习、技能提升 |
| `health` | 健康/身体 | 运动、饮食、体检、医疗 |
| `relation` | 关系/社交 | 家人、朋友、社交活动 |
| `think` | 思考/反思 | 人生感悟、决策思考、复盘 |
| `create` | 创作/产出 | 文章、代码、设计作品 |
| `life` | 生活/日常 | 日常琐事、娱乐、购物 |

---

## 配置文件

配置文件位置：`~/Documents/Life-Index/.life-index/config.yaml`

详见 [config.example.yaml](../../config.example.yaml)