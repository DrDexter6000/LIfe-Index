#!/usr/bin/env python3
"""
Unit tests for config.py core functions
"""

from pathlib import Path

import pytest

from tools.lib.config import (
    _deep_merge,
    _get_env_config,
    _load_yaml_config,
    get_index_prefixes,
    get_journal_dir,
    get_model_cache_dir,
    get_next_sequence,
    get_safe_path,
    get_search_config,
    get_weather_config,
    normalize_path,
)


class TestGetSafePath:
    """Tests for get_safe_path function"""

    def test_empty_path_returns_none(self):
        """Empty path should return None"""
        result = get_safe_path("")
        assert result is None

    def test_none_path_returns_none(self):
        """None path should return None"""
        result = get_safe_path(None)  # type: ignore
        assert result is None

    def test_absolute_path_resolved(self):
        """Absolute path should be resolved"""
        result = get_safe_path("/tmp/test.txt")
        assert result is not None
        assert isinstance(result, Path)

    def test_relative_path_with_base(self):
        """Relative path should be resolved against base_dir"""
        base = Path("/tmp")
        result = get_safe_path("test.txt", base)
        assert result is not None
        assert "test.txt" in str(result)

    def test_path_traversal_blocked(self, tmp_path):
        """Path traversal attempts should return None for safety"""
        # Create a base directory
        base = tmp_path / "safe"
        base.mkdir()

        # Try to escape with ..
        result = get_safe_path("../../../etc/passwd", base)
        # The function returns None when path escapes base_dir
        assert result is None

    def test_path_traversal_with_encoded_chars(self, tmp_path):
        """Path traversal with encoded characters should be blocked"""
        base = tmp_path / "safe"
        base.mkdir()

        result = get_safe_path("subdir/../../../etc/passwd", base)
        assert result is None

    def test_absolute_path_outside_base(self, tmp_path):
        """Absolute path outside base should return None for safety"""
        base = tmp_path / "safe"
        base.mkdir()

        # Absolute paths outside base_dir are blocked for safety
        result = get_safe_path(str(tmp_path / "other" / "file.txt"), base)
        assert result is None

    def test_invalid_path_returns_none(self):
        """Invalid path should return None"""
        result = get_safe_path("\x00invalid\x00")
        assert result is None


class TestNormalizePath:
    """Tests for normalize_path function"""

    def test_empty_path_returns_empty(self):
        """Empty path should return empty string"""
        assert normalize_path("") == ""

    def test_none_path_returns_empty(self):
        """None path should return empty string"""
        from typing import cast

        assert normalize_path(cast(str, None)) == ""

    def test_backslash_converted_to_forward_slash(self):
        """Windows backslashes should be converted"""
        result = normalize_path("C:\\Users\\test\\file.txt")
        assert "\\" not in result
        assert "/" in result

    def test_windows_long_path_prefix_removed(self):
        """Windows long path prefix should be removed"""
        result = normalize_path("\\\\?\\C:\\Users\\test\\file.txt")
        assert not result.startswith("\\\\?\\")

    def test_forward_slash_preserved(self):
        """Forward slashes should be preserved"""
        result = normalize_path("/home/user/file.txt")
        assert result == "/home/user/file.txt"

    def test_path_mapping_applied(self, monkeypatch):
        """Path mappings should be applied"""
        monkeypatch.setattr(
            "tools.lib.config.PATH_MAPPINGS",
            {"C:/Users/test": "/home/test"},
        )
        result = normalize_path("C:/Users/test/file.txt")
        assert result == "/home/test/file.txt"

    def test_no_mapping_when_not_configured(self):
        """Path should be unchanged when no mapping configured"""
        result = normalize_path("/home/user/file.txt")
        assert result == "/home/user/file.txt"


class TestGetJournalDir:
    """Tests for get_journal_dir function"""

    def test_default_returns_current_year_month(self):
        """Default call should return current year/month directory"""
        result = get_journal_dir()
        assert isinstance(result, Path)
        assert "Journals" in str(result)

    def test_explicit_year_month(self):
        """Explicit year/month should be used"""
        result = get_journal_dir(year=2025, month=6)
        assert "2025" in str(result)
        assert "06" in str(result)

    def test_month_zero_padded(self):
        """Month should be zero-padded"""
        result = get_journal_dir(year=2026, month=3)
        assert "03" in str(result)


class TestLoadYamlConfig:
    """Tests for _load_yaml_config function"""

    def test_nonexistent_file_returns_empty_dict(self):
        """Non-existent config file should return empty dict"""
        result = _load_yaml_config(Path("/nonexistent/path/config.yaml"))
        assert result == {}

    def test_yaml_with_only_comments_returns_empty_dict(self, tmp_path):
        """YAML file with only comments should return empty dict"""
        config_file = tmp_path / "comments.yaml"
        config_file.write_text("# This is a comment\n# Another comment")
        result = _load_yaml_config(config_file)
        assert result == {}

    def test_valid_yaml_loads_correctly(self, tmp_path):
        """Valid YAML file should load correctly"""
        config_file = tmp_path / "valid.yaml"
        config_file.write_text(
            "defaults:\n  location: Test City\nweather:\n  timeout: 30"
        )
        result = _load_yaml_config(config_file)
        assert result["defaults"]["location"] == "Test City"
        assert result["weather"]["timeout"] == 30

    def test_empty_file_returns_empty_dict(self, tmp_path):
        """Empty YAML file should return empty dict"""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        result = _load_yaml_config(config_file)
        assert result == {}


class TestGetEnvConfig:
    """Tests for _get_env_config function"""

    def test_no_env_vars_returns_empty_dict(self, monkeypatch):
        """No environment variables should return empty dict"""
        # Clear relevant env vars
        for key in [
            "LIFE_INDEX_DEFAULT_LOCATION",
            "LIFE_INDEX_WEATHER_API_URL",
            "LIFE_INDEX_WEATHER_TIMEOUT",
            "LIFE_INDEX_SEARCH_LEVEL",
            "LIFE_INDEX_LOG_LEVEL",
        ]:
            monkeypatch.delenv(key, raising=False)

        result = _get_env_config()
        assert result == {}

    def test_location_env_var_loaded(self, monkeypatch):
        """LIFE_INDEX_DEFAULT_LOCATION should be loaded"""
        monkeypatch.setenv("LIFE_INDEX_DEFAULT_LOCATION", "Beijing, China")
        result = _get_env_config()
        assert result["defaults"]["location"] == "Beijing, China"

    def test_weather_api_url_env_var_loaded(self, monkeypatch):
        """LIFE_INDEX_WEATHER_API_URL should be loaded"""
        monkeypatch.setenv("LIFE_INDEX_WEATHER_API_URL", "https://custom.api.com")
        result = _get_env_config()
        assert result["weather"]["api_url"] == "https://custom.api.com"

    def test_weather_timeout_env_var_loaded(self, monkeypatch):
        """LIFE_INDEX_WEATHER_TIMEOUT should be loaded"""
        monkeypatch.setenv("LIFE_INDEX_WEATHER_TIMEOUT", "20")
        result = _get_env_config()
        assert result["weather"]["timeout_seconds"] == "20"

    def test_search_level_env_var_loaded(self, monkeypatch):
        """LIFE_INDEX_SEARCH_LEVEL should be loaded"""
        monkeypatch.setenv("LIFE_INDEX_SEARCH_LEVEL", "2")
        result = _get_env_config()
        assert result["search"]["default_level"] == "2"

    def test_log_level_env_var_loaded(self, monkeypatch):
        """LIFE_INDEX_LOG_LEVEL should be loaded"""
        monkeypatch.setenv("LIFE_INDEX_LOG_LEVEL", "DEBUG")
        result = _get_env_config()
        assert result["logging"]["level"] == "DEBUG"


class TestDeepMerge:
    """Tests for _deep_merge function"""

    def test_simple_merge(self):
        """Simple dict merge should work"""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_dict_merge(self):
        """Nested dicts should be merged recursively"""
        base = {"weather": {"api_url": "default.com", "timeout": 10}}
        override = {"weather": {"timeout": 20}}
        result = _deep_merge(base, override)
        assert result["weather"]["api_url"] == "default.com"
        assert result["weather"]["timeout"] == 20

    def test_deep_nested_merge(self):
        """Deep nested dicts should be merged"""
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 3, "e": 4}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"] == 1
        assert result["a"]["b"]["d"] == 3
        assert result["a"]["b"]["e"] == 4

    def test_empty_base(self):
        """Empty base dict should return copy of override"""
        result = _deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_empty_override(self):
        """Empty override dict should return copy of base"""
        result = _deep_merge({"a": 1}, {})
        assert result == {"a": 1}

    def test_non_dict_values_replaced(self):
        """Non-dict values should be replaced, not merged"""
        base = {"a": [1, 2, 3]}
        override = {"a": [4, 5]}
        result = _deep_merge(base, override)
        assert result["a"] == [4, 5]


class TestGetWeatherConfig:
    """Tests for get_weather_config function"""

    def test_default_values(self, monkeypatch):
        """Default weather config should be returned"""
        # Clear USER_CONFIG by ensuring no config file exists
        monkeypatch.setattr("tools.lib.config.USER_CONFIG", {})
        result = get_weather_config()
        assert result["api_url"] == "https://api.open-meteo.com/v1/forecast"
        assert result["archive_url"] == "https://archive-api.open-meteo.com/v1/archive"
        assert result["timeout_seconds"] == 15
        assert result["allow_skip_on_failure"] is True

    def test_config_override(self, monkeypatch):
        """Config overrides should work"""
        monkeypatch.setattr(
            "tools.lib.config.USER_CONFIG",
            {"weather": {"timeout_seconds": 30, "custom_key": "value"}},
        )
        result = get_weather_config()
        assert result["timeout_seconds"] == 30
        assert result["custom_key"] == "value"
        # Defaults still present
        assert result["api_url"] == "https://api.open-meteo.com/v1/forecast"


class TestGetSearchConfig:
    """Tests for get_search_config function"""

    def test_default_values(self, monkeypatch):
        """Default search config should be returned"""
        monkeypatch.setattr("tools.lib.config.USER_CONFIG", {})
        result = get_search_config()
        assert result["default_level"] == 3
        assert result["semantic_weight"] == 0.4
        assert result["fts_weight"] == 0.6
        assert result["default_limit"] == 10

    def test_config_override(self, monkeypatch):
        """Config overrides should work"""
        monkeypatch.setattr(
            "tools.lib.config.USER_CONFIG",
            {"search": {"default_level": 2, "custom_param": "test"}},
        )
        result = get_search_config()
        assert result["default_level"] == 2
        assert result["custom_param"] == "test"


class TestGetIndexPrefixes:
    """Tests for get_index_prefixes function"""

    def test_default_prefixes(self, monkeypatch):
        """Default Chinese prefixes should be returned"""
        monkeypatch.setattr("tools.lib.config.USER_CONFIG", {})
        result = get_index_prefixes()
        assert result["topic"] == "主题_"
        assert result["project"] == "项目_"
        assert result["tag"] == "标签_"

    def test_custom_prefixes(self, monkeypatch):
        """Custom English prefixes should work"""
        monkeypatch.setattr(
            "tools.lib.config.USER_CONFIG",
            {"index_prefixes": {"topic": "topic_", "project": "project_"}},
        )
        result = get_index_prefixes()
        assert result["topic"] == "topic_"
        assert result["project"] == "project_"
        assert result["tag"] == "标签_"  # Default preserved


class TestGetModelCacheDir:
    """Tests for get_model_cache_dir function"""

    def test_default_cache_dir(self, monkeypatch, tmp_path):
        """Default cache directory should be in user home"""
        monkeypatch.setattr("tools.lib.config.USER_CONFIG", {})
        # Mock Path.home to use tmp_path
        original_home = Path.home()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_model_cache_dir()
        assert "life-index" in str(result)
        assert "models" in str(result)
        # Restore
        monkeypatch.setattr(Path, "home", lambda: original_home)

    def test_custom_cache_dir(self, monkeypatch, tmp_path):
        """Custom cache directory from config should be used"""
        custom_dir = tmp_path / "custom_cache"
        monkeypatch.setattr(
            "tools.lib.config.USER_CONFIG",
            {"vector_index": {"cache_dir": str(custom_dir)}},
        )
        result = get_model_cache_dir()
        assert str(result) == str(custom_dir)


class TestGetNextSequence:
    """Tests for get_next_sequence function"""

    def test_no_existing_files_returns_one(self, tmp_path, monkeypatch):
        """No existing files should return 1"""
        # Mock JOURNALS_DIR to use tmp_path
        monkeypatch.setattr("tools.lib.config.JOURNALS_DIR", tmp_path)
        year_month = tmp_path / "2026" / "03"
        year_month.mkdir(parents=True)

        result = get_next_sequence("LifeIndex", "2026-03-15")
        assert result == 1

    def test_existing_files_returns_next_seq(self, tmp_path, monkeypatch):
        """Existing files should return next sequence number"""
        monkeypatch.setattr("tools.lib.config.JOURNALS_DIR", tmp_path)
        year_month = tmp_path / "2026" / "03"
        year_month.mkdir(parents=True)

        # Create existing files
        (year_month / "LifeIndex_2026-03-15_001.md").touch()
        (year_month / "LifeIndex_2026-03-15_002.md").touch()
        (year_month / "LifeIndex_2026-03-15_005.md").touch()

        result = get_next_sequence("LifeIndex", "2026-03-15")
        assert result == 6

    def test_malformed_filenames_skipped(self, tmp_path, monkeypatch):
        """Malformed filenames should be skipped"""
        monkeypatch.setattr("tools.lib.config.JOURNALS_DIR", tmp_path)
        year_month = tmp_path / "2026" / "03"
        year_month.mkdir(parents=True)

        # Create files with malformed sequence numbers
        (year_month / "LifeIndex_2026-03-15_001.md").touch()
        (year_month / "LifeIndex_2026-03-15_abc.md").touch()  # Invalid
        (year_month / "LifeIndex_2026-03-15_.md").touch()  # Missing

        result = get_next_sequence("LifeIndex", "2026-03-15")
        assert result == 2

    def test_nonexistent_dir_returns_one(self, tmp_path, monkeypatch):
        """Non-existent directory should return 1"""
        monkeypatch.setattr("tools.lib.config.JOURNALS_DIR", tmp_path)
        # Don't create the directory

        result = get_next_sequence("LifeIndex", "2026-03-15")
        assert result == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
