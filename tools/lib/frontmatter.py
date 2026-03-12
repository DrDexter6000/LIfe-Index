#!/usr/bin/env python3
"""
Life Index - Frontmatter Utilities
统一 YAML frontmatter 解析/格式化模块（SSOT）

所有工具应使用此模块处理 frontmatter，避免重复实现。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


# 标准字段顺序（与历史日志保持一致）
FIELD_ORDER = [
    "title",
    "date",
    "location",
    "weather",
    "mood",
    "people",
    "tags",
    "project",
    "topic",
    "abstract",
    "links",
    "attachments",
]

# 字段类型定义
LIST_FIELDS = {"mood", "people", "tags", "topic", "links", "attachments"}
STRING_FIELDS = {"title", "date", "location", "weather", "project", "abstract"}


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    解析 YAML frontmatter
    
    Args:
        content: 完整的文件内容
        
    Returns:
        (metadata_dict, body_content)
    """
    if not content.startswith("---"):
        return {}, content
    
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    
    fm_content = parts[1].strip()
    body = parts[2].strip()
    
    metadata = _parse_yaml_content(fm_content)
    return metadata, body


def parse_journal_file(file_path: Path) -> Dict[str, Any]:
    """
    解析日志文件，返回完整元数据（包含 _body 和 _file）
    
    Args:
        file_path: 日志文件路径
        
    Returns:
        包含 frontmatter、正文、文件路径的字典
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(content)
        
        # 提取标题（第一个 # 标题）
        title_match = re.search(r"^# (.+)$", body, re.MULTILINE)
        metadata["_title"] = title_match.group(1) if title_match else file_path.stem
        
        # 提取摘要（第一个非空非标题段落）
        abstract_match = re.search(r"\n\n([^#\n].*?)(?=\n\n|\Z)", body, re.DOTALL)
        if abstract_match:
            abstract = abstract_match.group(1).strip()[:100]
            metadata["_abstract"] = abstract + "..." if len(abstract) == 100 else abstract
        else:
            metadata["_abstract"] = "(无摘要)"
        
        metadata["_body"] = body
        metadata["_file"] = str(file_path)
        
        return metadata
    except Exception as e:
        return {"_error": str(e), "_file": str(file_path)}


def _parse_yaml_content(content: str) -> Dict[str, Any]:
    """
    解析 YAML 内容（简化版，不依赖外部库）
    支持基本类型：字符串、数字、布尔值、列表
    """
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: List[Any] = []
    in_list = False
    
    for line in content.split("\n"):
        stripped = line.strip()
        
        # 跳过空行和注释
        if not stripped or stripped.startswith("#"):
            continue
        
        # 列表项
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            value = _unquote_string(value)
            current_list.append(value)
            in_list = True
            continue
        
        # 键值对
        if ":" in stripped:
            # 保存之前的列表
            if in_list and current_key:
                result[current_key] = current_list
                current_list = []
                in_list = False
            
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            
            # 空值表示开始一个列表
            if not value:
                current_key = key
                current_list = []
                in_list = True
                continue
            
            # 解析值
            result[key] = _parse_yaml_value(value)
            current_key = None
    
    # 保存最后的列表
    if in_list and current_key:
        result[current_key] = current_list
    
    return result


def _parse_yaml_value(value: str) -> Any:
    """解析单个 YAML 值"""
    # 布尔值
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    
    # null
    if value.lower() in ("null", "~", ""):
        return None
    
    # 数字
    try:
        if "." in value and value.replace(".", "").replace("-", "").isdigit():
            return float(value)
        if value.replace("-", "").isdigit():
            return int(value)
    except ValueError:
        pass
    
    # 字符串（去除引号）
    value = _unquote_string(value)
    
    # 数组表示法 [item1, item2]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items = inner.split(",")
        return [_parse_yaml_value(item.strip()) for item in items if item.strip()]
    
    return value


def _unquote_string(value: str) -> str:
    """去除字符串引号"""
    if len(value) >= 2:
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
    return value


def format_frontmatter(data: Dict[str, Any]) -> str:
    """
    格式化 frontmatter 为标准 YAML
    保持字段顺序与历史日志一致
    """
    import json
    
    lines = ["---"]
    
    # 按标准顺序输出已知字段
    for key in FIELD_ORDER:
        if key in data and data[key] is not None:
            value = data[key]
            lines.append(_format_field(key, value))
    
    # 输出其他字段
    for key, value in data.items():
        if key not in FIELD_ORDER and not key.startswith("_"):
            lines.append(_format_field(key, value))
    
    lines.append("---")
    return "\n".join(lines)


def _format_field(key: str, value: Any) -> str:
    """格式化单个字段"""
    import json
    
    if isinstance(value, list):
        # 列表使用 JSON 格式
        return f"{key}: {json.dumps(value, ensure_ascii=False)}"
    elif isinstance(value, str):
        # 字符串加引号（除了特定字段）
        if key in ("date",):
            return f"{key}: {value}"
        return f'{key}: "{value}"'
    elif isinstance(value, bool):
        return f"{key}: {str(value).lower()}"
    elif value is None:
        return f"{key}:"
    else:
        return f"{key}: {value}"


def format_journal_content(data: Dict[str, Any]) -> str:
    """
    格式化完整日志内容（frontmatter + 正文）
    
    Args:
        data: 包含 frontmatter 和 content 的字典
        
    Returns:
        完整的日志文件内容
    """
    frontmatter = format_frontmatter(data)
    
    lines = []
    
    # 标题
    title = data.get("title", "")
    if title:
        lines.append(f"# {title}")
        lines.append("")
    
    # 正文
    content = data.get("content", "")
    if content:
        lines.append(content)
        lines.append("")
    
    # 附件引用
    attachments = data.get("attachments", [])
    if attachments:
        lines.append("## Attachments")
        for att in attachments:
            if isinstance(att, dict):
                filename = att.get("filename", "")
                rel_path = att.get("rel_path", "")
                description = att.get("description", "")
                path = rel_path or f"../../../Attachments/{filename}"
                lines.append(f"- [{filename}]({path}) - {description}")
            elif isinstance(att, str):
                lines.append(f"- [{att}]({att})")
        lines.append("")
    
    body = "\n".join(lines)
    return f"{frontmatter}\n\n{body}"


def update_frontmatter_fields(
    file_path: Path, 
    updates: Dict[str, Any],
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    更新日志文件的 frontmatter 字段
    
    Args:
        file_path: 日志文件路径
        updates: 要更新的字段字典
        dry_run: 是否模拟运行
        
    Returns:
        包含变更信息的字典
    """
    result = {
        "success": False,
        "changes": {},
        "error": None,
    }
    
    try:
        content = file_path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(content)
        
        # 记录变更
        for key, new_value in updates.items():
            old_value = metadata.get(key)
            if old_value != new_value:
                result["changes"][key] = {"old": old_value, "new": new_value}
                metadata[key] = new_value
        
        if dry_run:
            result["success"] = True
            return result
        
        # 写入文件
        new_content = format_frontmatter(metadata) + "\n\n" + body
        file_path.write_text(new_content, encoding="utf-8")
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def get_required_fields() -> List[str]:
    """获取必需字段列表"""
    return ["title", "date"]


def get_recommended_fields() -> List[str]:
    """获取推荐字段列表"""
    return ["location", "weather", "mood", "people", "abstract", "topic"]


def validate_metadata(metadata: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    验证元数据完整性
    
    Returns:
        问题列表，每项包含 level, field, message
    """
    issues = []
    required = get_required_fields()
    
    for field in required:
        if field not in metadata or not metadata[field]:
            issues.append({
                "level": "error",
                "field": field,
                "message": f"缺少必填字段: {field}",
            })
    
    # 日期格式验证
    if "date" in metadata and metadata["date"]:
        date_str = str(metadata["date"])
        if not re.match(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$", date_str):
            issues.append({
                "level": "warning",
                "field": "date",
                "message": f"日期格式可能不正确: {date_str}",
            })
    
    return issues
