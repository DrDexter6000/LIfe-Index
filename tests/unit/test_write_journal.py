#!/usr/bin/env python3
"""
Unit tests for write_journal.py core functions
"""

import pytest
from pathlib import Path
from datetime import datetime
import sys

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from write_journal.utils import (
    generate_filename,
    get_next_sequence,
)
from write_journal.weather import normalize_location
from lib.frontmatter import format_frontmatter


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
        result = normalize_location(None)
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
        assert result == "苏州, China"


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
        assert 'location: "Beijing, China"' in result  # 字符串字段带引号

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
        # Should use JSON array format, not YAML list
        assert '["work", "life"]' in result or '["work","life"]' in result
        assert '["tag1", "tag2"]' in result or '["tag1","tag2"]' in result

    def test_date_no_quotes(self):
        """Date field should not have quotes"""
        data = {"date": "2026-03-10", "seq": 1, "content": ""}
        result = format_frontmatter(data)
        assert 'date: "2026-03-10"' not in result  # Should NOT have quotes
        assert "date: 2026-03-10" in result


class TestGetNextSequence:
    """Tests for get_next_sequence function"""

    def test_empty_directory_returns_one(self, tmp_path):
        """Empty directory should return sequence 1"""
        # This test requires mocking JOURNALS_DIR
        pass  # TODO: Implement with proper mocking

    def test_existing_files_increment(self, tmp_path):
        """Existing files should increment max sequence"""
        pass  # TODO: Implement with proper mocking


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
