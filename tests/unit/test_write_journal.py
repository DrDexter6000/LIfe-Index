#!/usr/bin/env python3
"""
Unit tests for write_journal.py core functions
"""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from tools.write_journal.utils import (
    generate_filename,
    get_next_sequence,
    convert_path_for_platform,
    get_year_month,
)
from tools.write_journal.weather import normalize_location
from tools.lib.frontmatter import format_frontmatter


class TestGenerateFilename:
    """Tests for generate_filename function"""

    def test_basic_filename(self):
        """Test basic filename generation"""
        result = generate_filename("2026-03-10", 1)
        assert result == "life-index_2026-03-10_001.md"

    def test_sequence_padding(self):
        """Test sequence number is zero-padded to 3 digits"""
        assert generate_filename("2026-03-10", 1) == "life-index_2026-03-10_001.md"
        assert generate_filename("2026-03-10", 10) == "life-index_2026-03-10_010.md"
        assert generate_filename("2026-03-10", 100) == "life-index_2026-03-10_100.md"

    def test_date_format(self):
        """Test date format in filename"""
        result = generate_filename("2026-12-25", 5)
        assert "2026-12-25" in result


class TestNormalizeLocation:
    """Tests for normalize_location function"""

    def test_empty_location_returns_default(self):
        """Empty location should return default"""
        result = normalize_location("")
        assert result == "Chongqing, China"

    def test_none_location_returns_default(self):
        """None location should return default"""
        result = normalize_location(None)  # type: ignore
        assert result == "Chongqing, China"

    def test_chinese_city_name(self):
        """Chinese city name should be converted to English"""
        assert normalize_location("重庆") == "Chongqing, China"
        assert normalize_location("北京") == "Beijing, China"
        assert normalize_location("上海") == "Shanghai, China"

    def test_chinese_city_with_country(self):
        """Chinese city with country should be normalized"""
        assert normalize_location("重庆，中国") == "Chongqing, China"
        assert normalize_location("北京，中国") == "Beijing, China"

    def test_english_format_unchanged(self):
        """Already English format should be unchanged"""
        assert normalize_location("Tokyo, Japan") == "Tokyo, Japan"
        assert normalize_location("New York, USA") == "New York, USA"

    def test_unknown_chinese_city(self):
        """Unknown Chinese city should add ', China'"""
        result = normalize_location("苏州")
        assert ", China" in result


class TestFormatFrontmatter:
    """Tests for format_frontmatter function"""

    def test_basic_frontmatter(self):
        """Test basic frontmatter generation"""
        data = {
            "date": "2026-03-10",
            "time": "14:30",
            "location": "Beijing, China",
            "weather": "Sunny",
            "topic": ["work"],
            "project": "Life-Index",
            "tags": ["test"],
            "seq": 1,
            "content": "Test content",
        }
        result = format_frontmatter(data)
        assert "---" in result
        assert "date: 2026-03-10" in result
        assert "location: " in result
        assert '"Beijing, China"' in result

    def test_array_format(self):
        """Test arrays are formatted as JSON arrays"""
        data = {
            "date": "2026-03-10",
            "topic": ["work", "life"],
            "tags": ["tag1", "tag2"],
            "seq": 1,
            "content": "",
        }
        result = format_frontmatter(data)
        assert '["work", "life"]' in result or '["work","life"]' in result
        assert '["tag1", "tag2"]' in result or '["tag1","tag2"]' in result

    def test_date_no_quotes(self):
        """Date field should not have quotes"""
        data = {"date": "2026-03-10", "seq": 1, "content": ""}
        result = format_frontmatter(data)
        assert '"date": "2026-03-10"' not in result
        assert "date: 2026-03-10" in result


class TestGetYearMonth:
    """Tests for get_year_month function - lines 15-18"""

    def test_basic_date(self):
        """Test basic date parsing"""
        year, month = get_year_month("2026-03-15")
        assert year == 2026
        assert month == 3

    def test_date_with_time(self):
        """Test date with time component"""
        year, month = get_year_month("2026-03-15T14:30:00")
        assert year == 2026
        assert month == 3

    def test_date_with_timezone(self):
        """Test date with timezone (Z suffix)"""
        year, month = get_year_month("2026-03-15T14:30:00Z")
        assert year == 2026
        assert month == 3

    def test_december(self):
        """Test December date"""
        year, month = get_year_month("2025-12-31")
        assert year == 2025
        assert month == 12


class TestConvertPathForPlatform:
    """Tests for convert_path_for_platform function - lines 21-62"""

    def test_empty_path_returns_empty(self):
        """Empty path should return empty"""
        result = convert_path_for_platform("")
        assert result == ""

    def test_none_path_returns_none(self):
        """None path should return None"""
        result = convert_path_for_platform(None)  # type: ignore
        assert result is None

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {})
    def test_empty_path_mappings_returns_original(self):
        """Empty PATH_MAPPINGS should return original path"""
        result = convert_path_for_platform("C:\\Users\\test")
        assert result == "C:\\Users\\test"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    @patch("platform.system", return_value="Linux")
    def test_windows_to_linux(self, mock_platform):
        """Test Windows to Linux path conversion"""
        result = convert_path_for_platform("C:\\Users\\test\\file.txt")
        assert result == "/home/user/test/file.txt"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    @patch("platform.system", return_value="Darwin")
    def test_windows_to_macos(self, mock_platform):
        """Test Windows to macOS path conversion"""
        result = convert_path_for_platform("C:\\Users\\test\\file.txt")
        assert result == "/home/user/test/file.txt"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"/home/user": "C:\\Users"})
    @patch("platform.system", return_value="Windows")
    def test_linux_to_windows(self, mock_platform):
        """Test Linux to Windows path conversion"""
        result = convert_path_for_platform("/home/user/test/file.txt")
        assert result == "C:\\Users\\test\\file.txt"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"/Users/test": "C:\\Users"})
    @patch("platform.system", return_value="Windows")
    def test_macos_to_windows(self, mock_platform):
        """Test macOS to Windows path conversion"""
        result = convert_path_for_platform("/Users/test/file.txt")
        assert result == "C:\\Users\\file.txt"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    @patch("platform.system", return_value="Windows")
    def test_same_platform_no_conversion(self, mock_platform):
        """Test path on same platform uses backslashes"""
        result = convert_path_for_platform("C:\\Users\\test")
        assert "\\" in result or result == "C:\\Users\\test"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    def test_case_insensitive_matching(self):
        """Test path matching is case-insensitive"""
        with patch("platform.system", return_value="Linux"):
            result = convert_path_for_platform("c:\\users\\test\\file.txt")
            assert result == "/home/user/test/file.txt"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    def test_partial_path_no_match(self):
        """Test path that doesn't match any mapping returns original"""
        with patch("platform.system", return_value="Linux"):
            result = convert_path_for_platform("D:\\Other\\file.txt")
            assert result == "D:\\Other\\file.txt"

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    def test_path_traversal_preserved(self):
        """Test that path traversal attempts are preserved (not resolved)"""
        with patch("platform.system", return_value="Linux"):
            result = convert_path_for_platform("C:\\Users\\..\\..\\etc\\passwd")
            assert ".." in result

    @patch("tools.write_journal.utils.PATH_MAPPINGS", {"C:\\Users": "/home/user"})
    def test_invalid_characters_preserved(self):
        """Test that invalid characters are preserved (not validated)"""
        with patch("platform.system", return_value="Linux"):
            result = convert_path_for_platform("C:\\Users\\test<>|file.txt")
            assert result == "/home/user/test<>|file.txt"


class TestGetNextSequence:
    """Tests for get_next_sequence function - lines 71-93"""

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_nonexistent_directory_returns_one(self, mock_journals_dir):
        """Non-existent directory should return sequence 1"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = False
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15")
        assert result == 1

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_empty_directory_returns_one(self, mock_journals_dir):
        """Empty directory should return sequence 1"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_month_dir.glob.return_value = []
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15")
        assert result == 1

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_existing_files_increment(self, mock_journals_dir):
        """Existing files should increment max sequence"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_file1 = MagicMock()
        mock_file1.name = "life-index_2026-03-15_001.md"
        mock_file2 = MagicMock()
        mock_file2.name = "life-index_2026-03-15_003.md"
        mock_file3 = MagicMock()
        mock_file3.name = "life-index_2026-03-15_002.md"
        mock_month_dir.glob.return_value = [mock_file1, mock_file2, mock_file3]
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15")
        assert result == 4

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_mismatched_dates_ignored(self, mock_journals_dir):
        """Files with different dates should be ignored"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_file1 = MagicMock()
        mock_file1.name = "life-index_2026-03-14_001.md"
        mock_file2 = MagicMock()
        mock_file2.name = "life-index_2026-03-15_002.md"
        mock_file3 = MagicMock()
        mock_file3.name = "life-index_2026-03-16_001.md"
        mock_month_dir.glob.return_value = [mock_file1, mock_file2, mock_file3]
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15")
        assert result == 3

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_large_sequence_number(self, mock_journals_dir):
        """Test with large sequence numbers"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_file = MagicMock()
        mock_file.name = "life-index_2026-03-15_999.md"
        mock_month_dir.glob.return_value = [mock_file]
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15")
        assert result == 1000

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_malformed_filenames_ignored(self, mock_journals_dir):
        """Malformed filenames should be ignored"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_file1 = MagicMock()
        mock_file1.name = "life-index_2026-03-15_001.md"
        mock_file2 = MagicMock()
        mock_file2.name = "invalid_filename.md"
        mock_file3 = MagicMock()
        mock_file3.name = "life-index_2026-03-15_.md"
        mock_month_dir.glob.return_value = [mock_file1, mock_file2, mock_file3]
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15")
        assert result == 2

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_date_with_time_component(self, mock_journals_dir):
        """Test date string with time component"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_month_dir.glob.return_value = []
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = mock_month_dir
        result = get_next_sequence("2026-03-15T14:30:00")
        assert result == 1
        mock_journals_dir.__truediv__.assert_called_with("2026")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
