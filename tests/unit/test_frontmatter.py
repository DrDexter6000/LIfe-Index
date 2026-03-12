#!/usr/bin/env python3
"""
Unit tests for lib/frontmatter.py - YAML frontmatter 统一处理模块
SSOT 测试：确保 frontmatter 解析/格式化行为一致
"""

import pytest
from pathlib import Path
import sys

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from lib.frontmatter import (
    parse_frontmatter,
    parse_journal_file,
    format_frontmatter,
    format_journal_content,
    update_frontmatter_fields,
    validate_metadata,
    get_required_fields,
    get_recommended_fields,
    FIELD_ORDER,
)


class TestParseFrontmatter:
    """Tests for parse_frontmatter function"""

    def test_valid_frontmatter(self):
        """Test parsing valid frontmatter"""
        content = """---
title: "Test Title"
date: 2026-03-10T14:30:00
location: "Beijing, China"
weather: "Sunny"
topic: ["work"]
tags: ["test", "unit"]
---

# Test Content

This is the body.
"""
        metadata, body = parse_frontmatter(content)

        assert metadata["title"] == "Test Title"
        assert metadata["date"] == "2026-03-10T14:30:00"
        assert metadata["location"] == "Beijing, China"
        assert metadata["weather"] == "Sunny"
        assert "work" in metadata["topic"]
        assert "Test Content" in body

    def test_no_frontmatter(self):
        """Content without frontmatter markers"""
        content = "# Just a title\n\nBody content."
        metadata, body = parse_frontmatter(content)

        assert metadata == {}
        assert body == content

    def test_incomplete_frontmatter(self):
        """Incomplete frontmatter should be handled"""
        content = """---
title: "Test"

No closing marker.
"""
        metadata, body = parse_frontmatter(content)

        # Should handle gracefully
        assert isinstance(metadata, dict)

    def test_empty_frontmatter(self):
        """Empty frontmatter section"""
        content = """---
---

Body content.
"""
        metadata, body = parse_frontmatter(content)

        assert isinstance(metadata, dict)
        assert "Body content" in body

    def test_array_parsing(self):
        """Arrays should be parsed correctly"""
        content = """---
mood: ["happy", "focused"]
tags: ["tag1", "tag2", "tag3"]
---
Body.
"""
        metadata, body = parse_frontmatter(content)

        assert isinstance(metadata.get("mood"), list)
        assert "happy" in metadata["mood"]
        assert "focused" in metadata["mood"]
        assert len(metadata["tags"]) == 3

    def test_string_parsing(self):
        """String values should be unquoted"""
        content = """---
title: "Quoted Title"
location: 'Single Quoted'
plain: No Quotes
---
Body.
"""
        metadata, body = parse_frontmatter(content)

        assert metadata["title"] == "Quoted Title"
        assert metadata["location"] == "Single Quoted"
        assert metadata["plain"] == "No Quotes"


class TestFormatFrontmatter:
    """Tests for format_frontmatter function"""

    def test_basic_formatting(self):
        """Test basic frontmatter formatting"""
        data = {
            "title": "Test Title",
            "date": "2026-03-10T14:30:00",
            "location": "Beijing, China",
            "weather": "Sunny",
            "topic": ["work"],
            "tags": ["test"],
        }
        result = format_frontmatter(data)

        assert result.startswith("---")
        assert result.endswith("---")
        assert 'title: "Test Title"' in result
        assert "date: 2026-03-10T14:30:00" in result  # date 不带引号
        assert 'location: "Beijing, China"' in result  # 字符串带引号
        assert 'topic: ["work"]' in result  # 数组用 JSON 格式

    def test_field_order(self):
        """Fields should follow FIELD_ORDER: title, date, ..., tags, project, topic, ..."""
        data = {
            "tags": ["test"],  # tags comes before topic in FIELD_ORDER
            "title": "Test",
            "date": "2026-03-10",
            "topic": ["work"],
        }
        result = format_frontmatter(data)

        lines = result.strip().split("\n")
        # Find field positions
        title_pos = next((i for i, l in enumerate(lines) if l.startswith("title:")), -1)
        date_pos = next((i for i, l in enumerate(lines) if l.startswith("date:")), -1)
        topic_pos = next((i for i, l in enumerate(lines) if l.startswith("topic:")), -1)
        tags_pos = next((i for i, l in enumerate(lines) if l.startswith("tags:")), -1)

        # Verify order per FIELD_ORDER: title < date < tags < topic
        assert title_pos < date_pos
        assert date_pos < tags_pos
        assert tags_pos < topic_pos

    def test_empty_list(self):
        """Empty list should be formatted correctly"""
        data = {
            "date": "2026-03-10",
            "mood": [],
            "tags": [],
        }
        result = format_frontmatter(data)

        assert 'mood: []' in result
        assert 'tags: []' in result

    def test_boolean_values(self):
        """Boolean values should be formatted correctly"""
        data = {
            "date": "2026-03-10",
            "published": True,
            "draft": False,
        }
        result = format_frontmatter(data)

        assert "published: true" in result
        assert "draft: false" in result


class TestValidateMetadata:
    """Tests for validate_metadata function"""

    def test_valid_metadata(self):
        """Valid metadata should have no errors"""
        metadata = {
            "title": "Test",
            "date": "2026-03-10T14:30:00",
            "location": "Beijing",
        }
        issues = validate_metadata(metadata)

        # Should have no errors (title and date are present)
        errors = [i for i in issues if i["level"] == "error"]
        assert len(errors) == 0

    def test_missing_required_fields(self):
        """Missing required fields should be reported"""
        metadata = {
            "location": "Beijing",
        }
        issues = validate_metadata(metadata)

        errors = [i for i in issues if i["level"] == "error"]
        assert len(errors) == 2  # missing title and date

    def test_invalid_date_format(self):
        """Invalid date format should generate warning"""
        metadata = {
            "title": "Test",
            "date": "invalid-date",
        }
        issues = validate_metadata(metadata)

        warnings = [i for i in issues if i["level"] == "warning"]
        assert any("date" in w["field"] for w in warnings)


class TestFieldConstants:
    """Tests for field constants"""

    def test_field_order_contains_key_fields(self):
        """FIELD_ORDER should contain key fields"""
        assert "title" in FIELD_ORDER
        assert "date" in FIELD_ORDER
        assert "location" in FIELD_ORDER
        assert "topic" in FIELD_ORDER

    def test_required_fields(self):
        """Required fields should be title and date"""
        required = get_required_fields()
        assert "title" in required
        assert "date" in required

    def test_recommended_fields(self):
        """Recommended fields should include common metadata"""
        recommended = get_recommended_fields()
        assert "location" in recommended
        assert "weather" in recommended
        assert "mood" in recommended
        assert "topic" in recommended


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
