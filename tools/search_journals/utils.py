#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - Utilities
通用工具函数模块
"""

from typing import Any, Dict, Tuple

# SSOT: 使用 lib/frontmatter 进行 frontmatter 解析 (relative imports)
from ..lib.frontmatter import parse_frontmatter as _parse_frontmatter


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """解析 YAML frontmatter，返回 (metadata, body)

    此函数是 lib.frontmatter.parse_frontmatter 的包装，用于保持向后兼容。
    """
    return _parse_frontmatter(content)
