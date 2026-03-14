#!/usr/bin/env python3
"""
Life Index - Write Journal Tool - Core
核心协调模块
"""

from pathlib import Path
from typing import Any, Dict

# 导入配置
import sys

TOOLS_DIR = Path(__file__).parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from lib.config import JOURNALS_DIR
    from lib.file_lock import FileLock, LockTimeoutError, get_journals_lock_path
    from lib.errors import ErrorCode, create_error_response
    from lib.timing import Timer
except ImportError:
    # 回退到项目目录（用于开发测试）
    PROJECT_ROOT = Path(__file__).parent.parent
    JOURNALS_DIR = PROJECT_ROOT / "journals"
    # 文件锁和错误模块的回退导入
    from tools.lib.file_lock import FileLock, LockTimeoutError, get_journals_lock_path
    from tools.lib.errors import ErrorCode, create_error_response
    from tools.lib.timing import Timer

# 导入子模块
from .utils import get_year_month, generate_filename, get_next_sequence
from .frontmatter import format_frontmatter, format_content
from .attachments import extract_file_paths_from_content, process_attachments
from .weather import query_weather_for_location, normalize_location
from .index_updater import (
    update_topic_index,
    update_project_index,
    update_tag_indices,
    update_monthly_abstract,
)


def write_journal(data: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    写入日志的主函数
    自动处理默认值和天气查询

    Returns:
        {
            "success": bool,
            "journal_path": str,
            "updated_indices": [str],
            "attachments_processed": [dict],
            "location_used": str,
            "weather_used": str,
            "weather_auto_filled": bool,
            "needs_confirmation": bool,
            "confirmation_message": str,
            "metrics": {"total_ms": float, "weather_query_ms": float, ...},
            "error": str (optional)
        }
    """
    # 性能计时器
    timer = Timer().start()

    result: Dict[str, Any] = {
        "success": False,
        "journal_path": None,
        "updated_indices": [],
        "attachments_processed": [],
        "location_used": "",
        "weather_used": "",
        "weather_auto_filled": False,
        "needs_confirmation": False,
        "confirmation_message": "",
        "error": None,
        "metrics": {},
    }

    try:
        # 验证必需字段
        date_str = data.get("date")
        if not date_str:
            raise ValueError("缺少必需字段: date")

        # ===== 第一层：用户提及为准 =====
        # 如果用户提供了地点和天气，直接使用

        # ===== 第二层：自动填充 =====
        # 处理地点：如果未提供，使用默认值
        location = data.get("location", "").strip()
        if not location:
            location = "Chongqing, China"  # 默认地点
            result["location_used"] = location
            # 天气查询用同一格式
            location_for_weather = normalize_location("")
        else:
            # 规范化地点（处理城市级别输入）
            location_for_weather = normalize_location(location)
            result["location_used"] = location
        data["location"] = location

        # 处理天气：如果未提供，自动查询
        weather = data.get("weather", "").strip()
        if not weather:
            # 尝试获取天气（使用英文格式的地点）
            with timer.measure("weather_query"):
                queried_weather = query_weather_for_location(
                    location_for_weather, date_str
                )
            if queried_weather:
                weather = queried_weather
                result["weather_used"] = weather
                result["weather_auto_filled"] = True
            else:
                weather = ""
                result["weather_used"] = ""
        else:
            result["weather_used"] = weather

        data["weather"] = weather

        # ===== 文件锁保护 =====
        # 使用文件锁保护序列号生成和写入操作，防止并发冲突
        with timer.measure("lock_acquire"):
            lock = FileLock(get_journals_lock_path(), timeout=30.0)

        try:
            with lock:
                # ===== 原子写入（带重试）=====
                # 处理并发写入时的序列号冲突（现在有锁保护，主要用于健壮性）
                max_retries = 3
                year = 0
                month = 0
                journal_path = None
                month_dir = None

                with timer.measure("sequence_gen"):
                    for retry in range(max_retries):
                        # 获取年月和序列号
                        year, month = get_year_month(date_str)
                        sequence = get_next_sequence(date_str)

                        # 构建路径
                        month_dir = JOURNALS_DIR / str(year) / f"{month:02d}"
                        filename = generate_filename(date_str, sequence)
                        journal_path = month_dir / filename

                        # 如果文件已存在且不是最后一次重试，重新获取序列号
                        if journal_path.exists() and retry < max_retries - 1:
                            continue  # 重试
                        break  # 文件不存在，或最后一次重试直接使用

                # 类型安全断言（循环必定至少执行一次）
                assert journal_path is not None
                assert month_dir is not None

                # 从内容中自动检测文件路径
                content = data.get("content", "")
                auto_detected_paths = extract_file_paths_from_content(content)

                # 处理附件（显式附件 + 自动检测附件）
                attachments = data.get("attachments", [])
                with timer.measure("attachments"):
                    processed_attachments = process_attachments(
                        attachments, date_str, dry_run, auto_detected_paths
                    )
                result["attachments_processed"] = processed_attachments

                # 更新数据中的附件信息（用于生成内容）
                data["attachments"] = processed_attachments

                # 生成内容
                frontmatter = format_frontmatter(data)
                content = format_content(data)
                full_content = f"{frontmatter}\n\n{content}"

                if dry_run:
                    result["journal_path"] = str(journal_path)
                    result["content_preview"] = full_content[:500]
                    result["success"] = True
                    timer.stop()
                    result["metrics"] = timer.to_dict()
                    return result

                # ===== 事务性写入 =====
                # 1. 准备所有索引更新所需数据
                topic = data.get("topic")
                project = data.get("project")
                tags = data.get("tags", [])

                # 2. 使用临时文件进行原子写入
                month_dir.mkdir(parents=True, exist_ok=True)
                temp_path = journal_path.with_suffix(".tmp")
                try:
                    with timer.measure("file_write"):
                        with open(temp_path, "w", encoding="utf-8") as f:
                            f.write(full_content)

                    # 3. 更新月度摘要
                    with timer.measure("abstract_update"):
                        abstract_result = None
                        abstract_error = None
                        try:
                            abstract_result = update_monthly_abstract(
                                year, month, dry_run
                            )
                        except (OSError, IOError, RuntimeError) as e:
                            abstract_error = str(e)

                    # 4. 更新索引
                    updated_indices = []
                    with timer.measure("index_update"):
                        try:
                            if topic:
                                indices = update_topic_index(topic, journal_path, data)
                                updated_indices.extend([str(i) for i in indices])

                            if project:
                                idx = update_project_index(project, journal_path, data)
                                if idx:
                                    updated_indices.append(str(idx))

                            if tags:
                                indices = update_tag_indices(tags, journal_path, data)
                                updated_indices.extend([str(i) for i in indices])

                        except (OSError, IOError, RuntimeError) as e:
                            # 索引更新失败，清理临时文件
                            if temp_path.exists():
                                temp_path.unlink()
                            raise RuntimeError(f"索引更新失败，事务已回滚: {e}")

                    # 5. 所有操作成功，原子性重命名临时文件
                    temp_path.replace(journal_path)

                    # 记录结果
                    result["journal_path"] = str(journal_path)
                    result["monthly_abstract_updated"] = abstract_result
                    if abstract_error:
                        result["monthly_abstract_error"] = abstract_error
                    result["updated_indices"] = updated_indices

                except (OSError, IOError, RuntimeError):
                    # 确保临时文件被清理
                    if temp_path.exists():
                        temp_path.unlink()
                    raise

        except LockTimeoutError as e:
            # 锁超时，返回结构化错误
            return create_error_response(
                ErrorCode.LOCK_TIMEOUT,
                f"无法获取写入锁，请稍后重试: {e}",
                {"lock_path": str(get_journals_lock_path()), "timeout": 30.0},
                "等待几秒后重试，或检查是否有其他进程正在写入",
            )

        result["success"] = True

        # ===== 第三层：写入后确认 =====
        result["needs_confirmation"] = True
        result["confirmation_message"] = (
            f"日志已保存至：{journal_path}\n\n"
            f"当前记录信息：\n"
            f"- 地点：{location}\n"
            f"- 天气：{weather if weather else '（未获取）'}\n\n"
            f"请确认以上信息是否正确。如需修改，请告诉我新的地点或天气信息，"
            f"我将为您更新日志文件。"
        )

    except (ValueError, IOError, RuntimeError, OSError) as e:
        result["error"] = str(e)
        result["error"] = str(e)

    # 添加性能指标
    timer.stop()
    result["metrics"] = timer.to_dict()

    return result
