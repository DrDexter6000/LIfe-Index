#!/usr/bin/env python3
"""
Unit tests for logger.py

Tests cover:
- JSONFormatter.format: Test with extra_data, exception info
- HumanFormatter.format: Test different log levels
- setup_logger: Test with log_file, json_format, verbose
- get_logger: Test returns configured logger
- get_default_log_file: Test cross-platform paths
- LoggerAdapter.process: Test with extra_data
- init_logging: Test initialization
"""

import json
import logging
import os
import platform
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.lib.logger import (
    JSONFormatter,
    HumanFormatter,
    setup_logger,
    get_logger,
    get_default_log_file,
    LoggerAdapter,
    init_logging,
)


class TestJSONFormatter:
    """Tests for JSONFormatter class"""

    def test_format_basic_message(self):
        """Should format basic log message as JSON"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_logger"
        assert parsed["message"] == "Test message"
        assert parsed["function"] == "test_func"
        assert parsed["line"] == 10
        assert "timestamp" in parsed

    def test_format_with_extra_data(self):
        """Should include extra_data in JSON output"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )
        record.extra_data = {"file": "test.md", "lines": 100}

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "data" in parsed
        assert parsed["data"]["file"] == "test.md"
        assert parsed["data"]["lines"] == 100

    def test_format_with_exception(self):
        """Should include exception info in JSON output"""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
            func="test_func",
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "Test exception" in parsed["exception"]

    def test_format_with_extra_data_and_exception(self):
        """Should include both extra_data and exception"""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
            func="test_func",
        )
        record.extra_data = {"file": "test.md"}

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "data" in parsed
        assert "exception" in parsed
        assert parsed["data"]["file"] == "test.md"

    def test_format_without_extra_data(self):
        """Should not include data field when extra_data is empty"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )
        record.extra_data = {}

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "data" not in parsed

    def test_format_unicode_message(self):
        """Should handle unicode characters in message"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="测试消息 🔬",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["message"] == "测试消息 🔬"


class TestHumanFormatter:
    """Tests for HumanFormatter class"""

    def test_format_info_level(self):
        """Should format INFO level concisely"""
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test info message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)

        assert result == "[INFO] Test info message"
        assert "test_logger" not in result

    def test_format_debug_level(self):
        """Should format DEBUG level concisely"""
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=10,
            msg="Test debug message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)

        assert result == "[DEBUG] Test debug message"

    def test_format_warning_level(self):
        """Should format WARNING level with logger name"""
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=10,
            msg="Test warning message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)

        assert result == "[WARNING] test_logger: Test warning message"

    def test_format_error_level(self):
        """Should format ERROR level with logger name"""
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Test error message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)

        assert result == "[ERROR] test_logger: Test error message"

    def test_format_critical_level(self):
        """Should format CRITICAL level with logger name"""
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.CRITICAL,
            pathname="test.py",
            lineno=10,
            msg="Test critical message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)

        assert result == "[CRITICAL] test_logger: Test critical message"


class TestSetupLogger:
    """Tests for setup_logger function"""

    def test_setup_logger_basic(self):
        """Should create logger with basic configuration"""
        logger = setup_logger(name="test_basic")

        assert logger.name == "test_basic"
        assert len(logger.handlers) > 0
        assert logger.level == logging.INFO

    def test_setup_logger_custom_level(self):
        """Should set custom log level"""
        logger = setup_logger(name="test_level", level=logging.DEBUG)

        assert logger.level == logging.DEBUG

    def test_setup_logger_verbose_mode(self):
        """Should set DEBUG level in verbose mode"""
        logger = setup_logger(name="test_verbose", verbose=True)

        assert logger.level == logging.DEBUG

    def test_setup_logger_json_format(self):
        """Should use JSONFormatter when json_format=True"""
        logger = setup_logger(name="test_json", json_format=True)

        console_handler = logger.handlers[0]
        assert isinstance(console_handler.formatter, JSONFormatter)

    def test_setup_logger_human_format(self):
        """Should use HumanFormatter by default"""
        logger = setup_logger(name="test_human", json_format=False)

        console_handler = logger.handlers[0]
        assert isinstance(console_handler.formatter, HumanFormatter)

    def test_setup_logger_with_log_file(self, tmp_path):
        """Should create file handler when log_file provided"""
        log_file = tmp_path / "test.log"
        logger = setup_logger(name="test_file", log_file=log_file)

        assert len(logger.handlers) == 2  # console + file

        file_handler = logger.handlers[1]
        assert isinstance(file_handler, logging.FileHandler)
        assert isinstance(file_handler.formatter, JSONFormatter)
        assert log_file.exists()

    def test_setup_logger_creates_parent_dirs(self, tmp_path):
        """Should create parent directories for log file"""
        log_file = tmp_path / "nested" / "dir" / "test.log"
        logger = setup_logger(name="test_nested", log_file=log_file)

        assert log_file.parent.exists()
        assert log_file.exists()

    def test_setup_logger_file_creation_failure(self, tmp_path):
        """Should handle file creation failure gracefully"""
        log_file = tmp_path / "test.log"

        with patch.object(Path, "mkdir", side_effect=PermissionError("No permission")):
            logger = setup_logger(name="test_fail", log_file=log_file)

        # Should still have console handler
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_setup_logger_clears_existing_handlers(self):
        """Should clear existing handlers to avoid duplicates"""
        logger = setup_logger(name="test_clear")
        initial_count = len(logger.handlers)

        logger = setup_logger(name="test_clear")

        assert len(logger.handlers) == initial_count

    def test_setup_logger_console_outputs_to_stderr(self):
        """Should output console to stderr, not stdout"""
        logger = setup_logger(name="test_stderr")

        console_handler = logger.handlers[0]
        # Verify it's a StreamHandler and outputs to stderr
        assert isinstance(console_handler, logging.StreamHandler)
        assert hasattr(console_handler, "stream")
        assert console_handler.stream is sys.stderr


class TestGetLogger:
    """Tests for get_logger function"""

    def test_get_logger_creates_new_if_not_configured(self):
        """Should create and configure new logger if not exists"""
        logger = get_logger("test_new")

        assert logger.name == "test_new"
        assert len(logger.handlers) > 0

    def test_get_logger_returns_existing(self):
        """Should return existing logger if already configured"""
        logger1 = setup_logger(name="test_existing")
        logger2 = get_logger("test_existing")

        assert logger1 is logger2

    def test_get_logger_default_name(self):
        """Should use 'life-index' as default name"""
        logger = get_logger()

        assert logger.name == "life-index"


class TestGetDefaultLogFile:
    """Tests for get_default_log_file function"""

    def test_returns_path_object(self):
        """Should return a Path object"""
        result = get_default_log_file()
        assert isinstance(result, Path)

    def test_contains_life_index_directory(self):
        """Should contain Life-Index in path"""
        result = get_default_log_file()
        assert "Life-Index" in str(result)

    def test_contains_logs_subdirectory(self):
        """Should contain .logs subdirectory"""
        result = get_default_log_file()
        assert ".logs" in str(result)

    def test_ends_with_log_filename(self):
        """Should end with life-index.log"""
        result = get_default_log_file()
        assert result.name == "life-index.log"

    @patch("sys.platform", "win32")
    def test_windows_path(self):
        """Should use correct path on Windows"""
        result = get_default_log_file()
        assert "Documents" in str(result)
        assert "Life-Index" in str(result)

    @patch("sys.platform", "darwin")
    def test_macos_path(self):
        """Should use correct path on macOS"""
        result = get_default_log_file()
        assert "Documents" in str(result)
        assert "Life-Index" in str(result)

    @patch("sys.platform", "linux")
    def test_linux_path(self):
        """Should use correct path on Linux"""
        result = get_default_log_file()
        assert "Documents" in str(result)
        assert "Life-Index" in str(result)


class TestLoggerAdapter:
    """Tests for LoggerAdapter class"""

    def test_process_without_extra_data(self):
        """Should return message unchanged without extra_data"""
        adapter = LoggerAdapter(logging.getLogger("test"), {"module": "test_module"})
        msg, kwargs = adapter.process("Test message", {})

        assert msg == "Test message"
        # LoggerAdapter always includes extra from context if it exists
        assert "extra" in kwargs
        assert kwargs["extra"]["extra_data"]["module"] == "test_module"

    def test_process_with_extra_data(self):
        """Should merge extra_data into kwargs"""
        adapter = LoggerAdapter(logging.getLogger("test"), {"module": "test_module"})
        # extra_data is passed inside kwargs dict
        msg, kwargs = adapter.process(
            "Test message", {"extra_data": {"file": "test.md", "lines": 100}}
        )

        assert msg == "Test message"
        assert "extra" in kwargs
        assert kwargs["extra"]["extra_data"]["file"] == "test.md"
        assert kwargs["extra"]["extra_data"]["lines"] == 100
        assert kwargs["extra"]["extra_data"]["module"] == "test_module"

    def test_process_merges_context_and_extra(self):
        """Should merge context and extra_data (context takes precedence via update)"""
        adapter = LoggerAdapter(
            logging.getLogger("test"), {"module": "test_module", "version": "1.0"}
        )
        msg, kwargs = adapter.process(
            "Test message", {"extra_data": {"file": "test.md", "module": "override"}}
        )

        assert kwargs["extra"]["extra_data"]["file"] == "test.md"
        # Context values are updated into extra_data, so module becomes test_module
        assert kwargs["extra"]["extra_data"]["module"] == "test_module"
        assert kwargs["extra"]["extra_data"]["version"] == "1.0"

    def test_process_without_context(self):
        """Should work without context extra"""
        adapter = LoggerAdapter(logging.getLogger("test"), None)
        msg, kwargs = adapter.process(
            "Test message", {"extra_data": {"file": "test.md"}}
        )

        assert kwargs["extra"]["extra_data"]["file"] == "test.md"

    def test_process_no_extra_data_no_context(self):
        """Should return unchanged kwargs when no extra data"""
        adapter = LoggerAdapter(logging.getLogger("test"), {})
        msg, kwargs = adapter.process("Test message", {})

        assert "extra" not in kwargs


class TestInitLogging:
    """Tests for init_logging function"""

    def test_init_logging_basic(self):
        """Should initialize logging and return logger"""
        logger = init_logging()

        assert logger is not None
        assert logger.name == "life-index"
        assert len(logger.handlers) > 0

    def test_init_logging_verbose(self):
        """Should set DEBUG level in verbose mode"""
        logger = init_logging(verbose=True)

        assert logger.level == logging.DEBUG

    def test_init_logging_with_log_file(self, tmp_path):
        """Should create file handler when log_file provided"""
        log_file = tmp_path / "test.log"
        logger = init_logging(log_file=log_file)

        assert len(logger.handlers) == 2  # console + file
        assert log_file.exists()

    def test_init_logging_sets_global_logger(self):
        """Should set the global _default_logger"""
        from tools.lib.logger import _default_logger

        # Reset global state
        import tools.lib.logger as logger_module

        logger_module._default_logger = None

        logger = init_logging()

        assert logger_module._default_logger is not None
        assert logger_module._default_logger is logger


class TestIntegration:
    """Integration tests for logger module"""

    def test_logger_outputs_to_stderr(self, capsys):
        """Should output to stderr, not stdout"""
        logger = setup_logger(name="test_stderr_output", level=logging.INFO)
        logger.info("Test message")

        captured = capsys.readouterr()
        assert "Test message" in captured.err
        assert captured.out == ""

    def test_json_formatter_produces_valid_json(self):
        """JSONFormatter should produce valid JSON"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
            func="test",
        )
        record.extra_data = {"key": "value"}

        result = formatter.format(record)

        # Should not raise
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_logger_adapter_with_actual_logging(self, capsys):
        """LoggerAdapter should work with actual logging"""
        logger = setup_logger(name="test_adapter", level=logging.INFO)
        adapter = LoggerAdapter(logger, {"component": "test"})

        adapter.info("Test message", extra_data={"file": "test.md"})

        captured = capsys.readouterr()
        assert "Test message" in captured.err

    def test_full_logging_workflow(self, tmp_path, capsys):
        """Test complete logging workflow"""
        log_file = tmp_path / "workflow.log"

        # Initialize - init_logging uses verbose and log_file params
        logger = init_logging(verbose=True, log_file=log_file)

        # Log various levels
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        # Use adapter
        adapter = LoggerAdapter(logger, {"module": "workflow"})
        adapter.info("Adapter message", extra_data={"step": 1})

        # Verify file exists and has content
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert len(content) > 0

        # Verify JSON format in file
        lines = content.strip().split("\n")
        for line in lines:
            if line.strip():
                parsed = json.loads(line)
                assert "timestamp" in parsed
                assert "level" in parsed
                assert "message" in parsed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
