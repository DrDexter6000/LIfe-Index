#!/usr/bin/env python3
"""
Life Index - Write Journal Tool - Utilities
通用工具函数模块
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Tuple

# 导入配置 - 使用绝对导入确保正确的 USER_DATA_DIR
import sys

TOOLS_LIB_DIR = Path(__file__).parent.parent / "lib"
if str(TOOLS_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_LIB_DIR))

from config import JOURNALS_DIR, PATH_MAPPINGS, USER_DATA_DIR


def get_year_month(date_str: str) -> Tuple[int, int]:
    """从日期字符串提取年和月"""
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return dt.year, dt.month


def convert_path_for_platform(source_path: str) -> str:
    """
    跨平台路径转换（双向）

    根据配置的 PATH_MAPPINGS 将路径转换为当前平台可访问的格式。
    支持：
    - Windows → Linux/macOS (如 C:\\Users\\xxx → /home/xxx 或 /Users/xxx)
    - Linux/macOS → Windows (如 /home/xxx → C:\\Users\\xxx)
    - 任意平台间的映射

    Args:
        source_path: 原始路径

    Returns:
        转换后的路径（如果匹配映射），否则返回原路径
    """
    if not source_path or not PATH_MAPPINGS:
        return source_path

    # 检测当前平台
    import platform

    current_system = platform.system()  # 'Windows', 'Linux', 'Darwin' (macOS)

    # 规范化源路径用于匹配
    normalized_source = source_path.replace("\\", "/")

    for from_prefix, to_prefix in PATH_MAPPINGS.items():
        # 规范化映射前缀
        normalized_from = from_prefix.replace("\\", "/")
        normalized_to = to_prefix.replace("\\", "/")

        # 检查是否匹配
        if normalized_source.lower().startswith(normalized_from.lower()):
            # 替换前缀
            converted = normalized_to + normalized_source[len(normalized_from) :]
            # 根据当前平台调整路径分隔符
            if current_system == "Windows":
                converted = converted.replace("/", "\\")
            return converted

    return source_path


def generate_filename(date_str: str, sequence: int = 1) -> str:
    """生成日志文件名: life-index_YYYY-MM-DD_XXX.md"""
    date_part = date_str[:10]  # YYYY-MM-DD
    return f"life-index_{date_part}_{sequence:03d}.md"


def get_next_sequence(date_str: str) -> int:
    """获取指定日期的下一个序列号"""
    year, month = get_year_month(date_str)
    month_dir = JOURNALS_DIR / str(year) / f"{month:02d}"

    if not month_dir.exists():
        return 1

    date_part = date_str[:10]
    pattern = f"life-index_{date_part}_*.md"
    existing = list(month_dir.glob(pattern))

    if not existing:
        return 1

    # 提取最大序列号
    max_seq = 0
    for f in existing:
        match = re.search(rf"life-index_{date_part}_(\d+)\.md$", f.name)
        if match:
            max_seq = max(max_seq, int(match.group(1)))

    return max_seq + 1
