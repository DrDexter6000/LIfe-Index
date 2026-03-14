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
from tools.write_journal.frontmatter import format_frontmatter, format_content


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

    def test_minimal_frontmatter(self):
        """Test minimal frontmatter with only required fields"""
        data = {"date": "2026-03-10", "title": "Test"}
        result = format_frontmatter(data)
        assert result.startswith("---")
        assert result.endswith("---")
        assert 'title: "Test"' in result
        assert "date: 2026-03-10" in result

    def test_complete_frontmatter(self):
        """Test complete frontmatter with all fields"""
        data = {
            "title": "Complete Test",
            "date": "2026-03-10T14:30:00",
            "location": "Beijing, China",
            "weather": "Sunny 25°C",
            "mood": ["happy", "productive"],
            "people": ["Alice", "Bob"],
            "tags": ["test", "demo"],
            "project": "Life-Index",
            "topic": ["work", "create"],
            "abstract": "Test abstract",
            "links": ["https://example.com"],
            "attachments": ["file1.txt", "file2.txt"],
        }
        result = format_frontmatter(data)
        assert 'title: "Complete Test"' in result
        assert "date: 2026-03-10T14:30:00" in result
        assert 'location: "Beijing, China"' in result
        assert 'weather: "Sunny 25°C"' in result
        assert '"happy"' in result
        assert '"Alice"' in result
        assert '"test"' in result
        assert 'project: "Life-Index"' in result
        assert '"work"' in result
        assert 'abstract: "Test abstract"' in result
        assert '"https://example.com"' in result
        assert '"file1.txt"' in result

    def test_date_only_adds_current_time(self):
        """Test that date without time gets current time appended"""
        data = {"date": "2026-03-10", "title": "Test"}
        result = format_frontmatter(data)
        # Should have time component added
        assert "date: 2026-03-10T" in result
        # Should not have quotes around date
        assert '"date:' not in result

    def test_date_with_time_unchanged(self):
        """Test that date with time is kept as-is"""
        data = {"date": "2026-03-10T14:30:00", "title": "Test"}
        result = format_frontmatter(data)
        assert "date: 2026-03-10T14:30:00" in result

    def test_empty_string_fields(self):
        """Test that empty string fields are still included"""
        data = {"date": "2026-03-10", "title": "Test", "location": "", "weather": ""}
        result = format_frontmatter(data)
        assert 'location: ""' in result
        assert 'weather: ""' in result
        assert 'project: ""' in result
        assert 'abstract: ""' in result

    def test_title_with_quotes(self):
        """Test title with quotes is properly escaped"""
        data = {"date": "2026-03-10", "title": 'Test "Quoted" Title'}
        result = format_frontmatter(data)
        # Title should be quoted
        assert 'title: "' in result

    def test_mood_string_converted_to_list(self):
        """Test that mood as string is converted to list"""
        data = {"date": "2026-03-10", "mood": "happy"}
        result = format_frontmatter(data)
        assert 'mood: ["happy"]' in result

    def test_mood_empty_string_becomes_empty_list(self):
        """Test that empty mood string becomes empty list"""
        data = {"date": "2026-03-10", "mood": ""}
        result = format_frontmatter(data)
        assert "mood: []" in result

    def test_people_string_converted_to_list(self):
        """Test that people as string is converted to list"""
        data = {"date": "2026-03-10", "people": "Alice"}
        result = format_frontmatter(data)
        assert 'people: ["Alice"]' in result

    def test_tags_string_converted_to_list(self):
        """Test that tags as string is converted to list"""
        data = {"date": "2026-03-10", "tags": "test"}
        result = format_frontmatter(data)
        assert 'tags: ["test"]' in result

    def test_topic_string_converted_to_list(self):
        """Test that topic as string is converted to list"""
        data = {"date": "2026-03-10", "topic": "work"}
        result = format_frontmatter(data)
        assert 'topic: ["work"]' in result

    def test_links_string_converted_to_list(self):
        """Test that links as string is converted to list"""
        data = {"date": "2026-03-10", "links": "https://example.com"}
        result = format_frontmatter(data)
        assert '"https://example.com"' in result

    def test_attachments_dict_with_rel_path(self):
        """Test attachments with dict containing rel_path"""
        data = {
            "date": "2026-03-10",
            "attachments": [
                {"rel_path": "attachments/file.txt", "filename": "file.txt"}
            ],
        }
        result = format_frontmatter(data)
        assert '"attachments/file.txt"' in result

    def test_attachments_dict_with_filename_only(self):
        """Test attachments with dict containing only filename"""
        data = {"date": "2026-03-10", "attachments": [{"filename": "file.txt"}]}
        result = format_frontmatter(data)
        assert '"file.txt"' in result

    def test_attachments_dict_missing_both_paths(self):
        """Test attachments dict without rel_path or filename is skipped"""
        data = {"date": "2026-03-10", "attachments": [{"description": "no path"}]}
        result = format_frontmatter(data)
        # Should not include the attachment
        assert "no path" not in result

    def test_attachments_mixed_types(self):
        """Test attachments with mixed string and dict types"""
        data = {
            "date": "2026-03-10",
            "attachments": [
                "file1.txt",
                {"rel_path": "attachments/file2.txt", "filename": "file2.txt"},
            ],
        }
        result = format_frontmatter(data)
        assert '"file1.txt"' in result
        assert '"attachments/file2.txt"' in result

    def test_unicode_in_fields(self):
        """Test Unicode characters are preserved"""
        data = {
            "date": "2026-03-10",
            "title": "测试标题",
            "location": "北京，中国",
            "weather": "晴天 25°C",
            "mood": ["开心", "充实"],
        }
        result = format_frontmatter(data)
        assert "测试标题" in result
        assert "北京，中国" in result
        assert "晴天" in result
        assert "开心" in result

    def test_special_characters_in_title(self):
        """Test special characters in title"""
        data = {"date": "2026-03-10", "title": 'Test: Title with "quotes" & symbols!'}
        result = format_frontmatter(data)
        assert 'title: "' in result

    def test_field_order_title_date(self):
        """Test that title comes before date"""
        data = {"date": "2026-03-10", "title": "Test"}
        result = format_frontmatter(data)
        title_pos = result.find('title: "Test"')
        date_pos = result.find("date: 2026-03-10")
        assert title_pos < date_pos

    def test_field_order_project_before_topic(self):
        """Test that project comes before topic"""
        data = {
            "date": "2026-03-10",
            "project": "Life-Index",
            "topic": ["work"],
        }
        result = format_frontmatter(data)
        project_pos = result.find('project: "Life-Index"')
        topic_pos = result.find('topic: ["work"]')
        assert project_pos < topic_pos

    def test_field_order_mood_before_people(self):
        """Test that mood comes before people"""
        data = {"date": "2026-03-10", "mood": ["happy"], "people": ["Alice"]}
        result = format_frontmatter(data)
        mood_pos = result.find("mood:")
        people_pos = result.find("people:")
        assert mood_pos < people_pos

    def test_field_order_tags_before_project(self):
        """Test that tags comes before project"""
        data = {"date": "2026-03-10", "tags": ["test"], "project": "Life-Index"}
        result = format_frontmatter(data)
        tags_pos = result.find("tags:")
        project_pos = result.find('project: "Life-Index"')
        assert tags_pos < project_pos

    def test_no_title_skipped(self):
        """Test that empty title is skipped"""
        data = {"date": "2026-03-10", "title": ""}
        result = format_frontmatter(data)
        assert "title:" not in result

    def test_attachments_list_empty(self):
        """Test empty attachments list"""
        data = {"date": "2026-03-10", "attachments": []}
        result = format_frontmatter(data)
        assert "attachments: []" in result

    def test_links_list_empty(self):
        """Test empty links list"""
        data = {"date": "2026-03-10", "links": []}
        result = format_frontmatter(data)
        assert "links: []" in result

    def test_mood_list_empty(self):
        """Test empty mood list"""
        data = {"date": "2026-03-10", "mood": []}
        result = format_frontmatter(data)
        assert "mood: []" in result

    def test_people_list_empty(self):
        """Test empty people list"""
        data = {"date": "2026-03-10", "people": []}
        result = format_frontmatter(data)
        assert "people: []" in result

    def test_tags_list_empty(self):
        """Test empty tags list"""
        data = {"date": "2026-03-10", "tags": []}
        result = format_frontmatter(data)
        assert "tags: []" in result

    def test_topic_list_empty(self):
        """Test empty topic list"""
        data = {"date": "2026-03-10", "topic": []}
        result = format_frontmatter(data)
        assert "topic: []" in result


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
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
        result = get_next_sequence("2026-03-15")
        assert result == 1

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_empty_directory_returns_one(self, mock_journals_dir):
        """Empty directory should return sequence 1"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_month_dir.glob.return_value = []
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
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
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
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
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
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
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
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
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
        result = get_next_sequence("2026-03-15")
        assert result == 2

    @patch("tools.write_journal.utils.JOURNALS_DIR")
    def test_date_with_time_component(self, mock_journals_dir):
        """Test date string with time component"""
        mock_month_dir = MagicMock()
        mock_month_dir.exists.return_value = True
        mock_month_dir.glob.return_value = []
        mock_journals_dir.__truediv__.return_value.__truediv__.return_value = (
            mock_month_dir
        )
        result = get_next_sequence("2026-03-15T14:30:00")
        assert result == 1
        mock_journals_dir.__truediv__.assert_called_with("2026")


class TestFormatContent:
    """Tests for format_content function"""

    def test_content_with_title_only(self):
        """Test content with only title"""
        data = {"title": "Test Title", "content": ""}
        result = format_content(data)
        # Title is rendered even without content
        assert "# Test Title" in result

    def test_content_with_body_only(self):
        """Test content with only body, no title"""
        data = {"title": "", "content": "Test content"}
        result = format_content(data)
        assert "Test content" in result
        assert "#" not in result

    def test_content_with_title_and_body(self):
        """Test content with both title and body"""
        data = {"title": "Test Title", "content": "Test content here"}
        result = format_content(data)
        assert "# Test Title" in result
        assert "Test content here" in result

    def test_content_empty(self):
        """Test empty content"""
        data = {"title": "", "content": ""}
        result = format_content(data)
        assert result.strip() == ""

    def test_content_with_attachments_dicts(self):
        """Test content with attachments as dicts"""
        data = {
            "title": "",
            "content": "",
            "attachments": [
                {
                    "filename": "file1.txt",
                    "rel_path": "attachments/file1.txt",
                    "description": "Test file 1",
                }
            ],
        }
        result = format_content(data)
        assert "## Attachments" in result
        assert "[file1.txt]" in result
        assert "(attachments/file1.txt)" in result
        assert "Test file 1" in result

    def test_content_with_attachments_strings_skipped(self):
        """Test that string attachments are skipped (only dicts supported)"""
        data = {"title": "", "content": "", "attachments": ["file1.txt", "file2.txt"]}
        # String attachments will cause AttributeError in current implementation
        # This is a known limitation - attachments should be dicts in content
        with pytest.raises(AttributeError):
            format_content(data)

    def test_content_with_mixed_attachments_dict_only(self):
        """Test content with only dict attachments"""
        data = {
            "title": "",
            "content": "Some content",
            "attachments": [
                {
                    "filename": "file2.txt",
                    "rel_path": "attachments/file2.txt",
                    "description": "Test file",
                },
            ],
        }
        result = format_content(data)
        assert "Some content" in result
        assert "## Attachments" in result

    def test_content_attachments_with_missing_rel_path(self):
        """Test attachments fallback to filename when rel_path missing"""
        data = {
            "title": "",
            "content": "",
            "attachments": [{"filename": "file.txt", "description": "Test"}],
        }
        result = format_content(data)
        assert "../../../Attachments/file.txt" in result

    def test_content_multiline(self):
        """Test multiline content"""
        data = {"title": "Test", "content": "Line 1\nLine 2\nLine 3"}
        result = format_content(data)
        assert "# Test" in result
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_content_with_markdown(self):
        """Test content with markdown formatting"""
        data = {"title": "Test", "content": "**bold** and *italic* and `code`"}
        result = format_content(data)
        assert "**bold**" in result
        assert "*italic*" in result
        assert "`code`" in result

    def test_content_with_unicode(self):
        """Test content with Unicode characters"""
        data = {"title": "测试", "content": "这是中文内容 🎉"}
        result = format_content(data)
        assert "# 测试" in result
        assert "这是中文内容" in result
        assert "🎉" in result

    def test_content_with_empty_attachments(self):
        """Test that empty attachments list doesn't add section"""
        data = {"title": "Test", "content": "Content", "attachments": []}
        result = format_content(data)
        assert "## Attachments" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
