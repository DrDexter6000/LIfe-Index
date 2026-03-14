#!/usr/bin/env python3
"""
Life Index - Write Journal Tool - Attachments
附件处理模块
"""

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

# 导入配置
import sys

TOOLS_DIR = Path(__file__).parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from lib.config import ATTACHMENTS_DIR
except ImportError:
    # 回退到项目目录（用于开发测试）
    PROJECT_ROOT = Path(__file__).parent.parent
    ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"

from .utils import get_year_month, convert_path_for_platform


def looks_like_file_path(path: str) -> bool:
    """
    判断路径是否看起来像文件路径（有扩展名）
    """
    if not path:
        return False

    # 检查是否有文件扩展名
    name = os.path.basename(path)
    if "." in name:
        ext = name.split(".")[-1].lower()
        # 常见文件扩展名
        valid_exts = {
            "txt",
            "md",
            "doc",
            "docx",
            "pdf",
            "xls",
            "xlsx",
            "ppt",
            "pptx",
            "jpg",
            "jpeg",
            "png",
            "gif",
            "bmp",
            "svg",
            "webp",
            "ico",
            "mp4",
            "avi",
            "mov",
            "mkv",
            "flv",
            "wmv",
            "mp3",
            "wav",
            "flac",
            "aac",
            "ogg",
            "zip",
            "rar",
            "7z",
            "tar",
            "gz",
            "py",
            "js",
            "ts",
            "html",
            "css",
            "json",
            "xml",
            "yaml",
            "yml",
            "exe",
            "msi",
            "dmg",
            "pkg",
            "deb",
            "rpm",
            "psd",
            "ai",
            "sketch",
            "fig",
            "db",
            "sqlite",
            "db3",
        }
        if ext in valid_exts:
            return True

    return False


def extract_file_paths_from_content(content: str) -> List[str]:
    """
    从内容中提取本地文件路径

    支持的格式：
    - Windows 绝对路径: C:\\Users\\...\\file.txt, C:/Users/.../file.txt
    - 网络路径: \\\\server\\share\\file.txt
    - UNC 路径: //server/share/file.txt

    Returns:
        文件路径列表（去重）
    """
    if not content:
        return []

    paths = []

    # 匹配 Windows 绝对路径 (C:\... 或 C:/...)
    # 使用更严格的模式：必须以盘符开头，后跟反斜杠或斜杠，然后是路径组件
    # 路径组件不能包含非法字符 :*?"<>|
    windows_pattern = r'[A-Za-z]:[\\/](?:[^\\/:*?"<>|\r\n]*[\\/])*[^\\/:*?"<>|\r\n]*\.[^\\/:*?"<>|\r\n\s]+'
    for match in re.finditer(windows_pattern, content):
        path = match.group(0)
        # 验证是否是有效文件路径（有扩展名）
        if looks_like_file_path(path):
            paths.append(path)

    # 匹配 UNC 路径 (\\server\share\... 或 //server/share/...)
    unc_pattern = r'(?:\\\\|//)[^\\/:*?"<>|\r\n]+(?:[\\/][^\\/:*?"<>|\r\n]+)*\\/[^\\/:*?"<>|\r\n]*\.[^\\/:*?"<>|\r\n\s]+'
    for match in re.finditer(unc_pattern, content):
        path = match.group(0)
        if looks_like_file_path(path):
            paths.append(path)

    # 去重并保持顺序
    seen = set()
    unique_paths = []
    for p in paths:
        normalized = os.path.normpath(p).lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(p)

    return unique_paths


def process_attachments(
    attachments: List[Dict[str, str]],
    date_str: str,
    dry_run: bool = False,
    auto_detected_paths: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    处理附件复制

    Args:
        attachments: 附件列表，每项包含 source_path 和可选的 description
        date_str: 日期字符串，用于确定附件存储路径
        dry_run: 是否为模拟运行
        auto_detected_paths: 从内容中自动检测到的文件路径

    Returns:
        处理后的附件列表，包含 filename 和 description
    """
    processed = []
    year, month = get_year_month(date_str)
    att_dir = ATTACHMENTS_DIR / str(year) / f"{month:02d}"

    # 合并显式附件和自动检测的附件
    all_attachments = []

    # 添加显式附件
    if attachments:
        for att in attachments:
            if isinstance(att, dict):
                all_attachments.append(att)
            elif isinstance(att, str):
                all_attachments.append({"source_path": att, "description": ""})

    # 添加自动检测的附件（去重）
    existing_paths = {
        os.path.normpath(a.get("source_path", "")).lower() for a in all_attachments
    }
    if auto_detected_paths:
        for path in auto_detected_paths:
            normalized = os.path.normpath(path).lower()
            if normalized not in existing_paths:
                all_attachments.append(
                    {"source_path": path, "description": "", "auto_detected": "true"}
                )
                existing_paths.add(normalized)

    if not all_attachments:
        return []

    for idx, att in enumerate(all_attachments):
        source_path = att.get("source_path", "")
        description = att.get("description", "")
        auto_detected = att.get("auto_detected", False)

        if not source_path:
            continue

        # 安全检查：防止路径遍历攻击
        # NOTE: 当前实现允许访问任何可读文件。如需限制访问范围，
        # 请使用 lib.config.get_safe_path() 验证路径是否在允许的目录内。
        # 例如：限制只能访问用户文档目录下的文件
        # from lib.config import get_safe_path, USER_DATA_DIR
        # safe_path = get_safe_path(source_path, USER_DATA_DIR)
        # if safe_path is None:
        #     processed.append({"filename": f"[访问被拒绝: {source_path}]", ...})
        #     continue

        # 尝试跨平台路径转换
        converted_path = convert_path_for_platform(source_path)

        # 优先使用转换后的路径，如果原路径不存在的话
        if os.path.exists(converted_path):
            source_path = converted_path
        elif not os.path.exists(source_path):
            processed.append(
                {
                    "filename": f"[未找到: {source_path}]",
                    "description": description,
                    "error": "源文件不存在",
                    "auto_detected": auto_detected,
                    "converted_path": converted_path
                    if converted_path != source_path
                    else None,
                }
            )
            continue

        # 跳过目录
        if os.path.isdir(source_path):
            continue

        # 生成目标文件名（处理重名）
        source_name = Path(source_path).name
        base_name = Path(source_name).stem
        ext = Path(source_name).suffix

        if dry_run:
            target_name = source_name
        else:
            # 检查是否已存在同名文件
            target_name = source_name
            counter = 1
            while (att_dir / target_name).exists():
                target_name = f"{base_name}_{counter:03d}{ext}"
                counter += 1

            # 复制文件
            att_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, att_dir / target_name)

        # 生成相对路径 (../../../Attachments/YYYY/MM/filename)
        rel_path = f"../../../Attachments/{year}/{month:02d}/{target_name}"

        processed.append(
            {
                "filename": target_name,
                "rel_path": rel_path,
                "description": description,
                "original_name": source_name,
                "auto_detected": auto_detected,
            }
        )

    return processed
