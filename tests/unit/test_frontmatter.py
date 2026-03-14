#!/usr/bin/env python3
"""
Unit tests for lib/frontmatter.py - YAML frontmatter 统一处理模块
SSOT 测试：确保 frontmatter 解析/格式化行为一致
"""

import pytest

from tools.lib.frontmatter import (
    parse_frontmatter,
    parse_journal_file,
    format_frontmatter,
    format_journal_content,
    update_frontmatter_fields,
    validate_metadata,
    migrate_metadata,
    get_required_fields,
    get_recommended_fields,
    get_schema_version,
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

    def test_malformed_yaml(self):
        """Malformed YAML should be handled gracefully (lines 64-65)"""
        content = """---
title: "Test
date: 2026-03-10
---

Body content.
"""
        metadata, body = parse_frontmatter(content)

        # Should handle YAML error gracefully
        assert isinstance(metadata, dict)

    def test_datetime_conversion(self):
        """ISO 8601 timestamps should be converted to strings (line 73)"""
        content = """---
title: "Test"
date: 2026-03-10T14:30:00
---

Body.
"""
        metadata, body = parse_frontmatter(content)

        # date should be string, not datetime object
        assert isinstance(metadata.get("date"), str)
        assert metadata["date"] == "2026-03-10T14:30:00"

    def test_date_only_conversion(self):
        """Date only should be converted to ISO string"""
        content = """---
title: "Test"
date: 2026-03-10
---

Body.
"""
        metadata, body = parse_frontmatter(content)

        assert isinstance(metadata.get("date"), str)
        assert metadata["date"] == "2026-03-10"

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
        title_pos = next(
            (i for i, line in enumerate(lines) if line.startswith("title:")), -1
        )
        date_pos = next(
            (i for i, line in enumerate(lines) if line.startswith("date:")), -1
        )
        topic_pos = next(
            (i for i, line in enumerate(lines) if line.startswith("topic:")), -1
        )
        tags_pos = next(
            (i for i, line in enumerate(lines) if line.startswith("tags:")), -1
        )

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

        assert "mood: []" in result
        assert "tags: []" in result

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

    def test_none_values(self):
        """None values should be skipped (line 159)"""
        data = {
            "date": "2026-03-10",
            "title": "Test",
            "location": None,
        }
        result = format_frontmatter(data)

        # None values are skipped in format_frontmatter
        assert "location" not in result
        assert "null" not in result.lower()

    def test_numeric_values(self):
        """Numeric values should be formatted correctly"""
        data = {
            "date": "2026-03-10",
            "count": 42,
            "rating": 3.14,
        }
        result = format_frontmatter(data)

        assert "count: 42" in result
        assert "rating: 3.14" in result

    def test_dict_values(self):
        """Dict values should be formatted as JSON"""
        data = {
            "date": "2026-03-10",
            "custom": {"key": "value"},
        }
        result = format_frontmatter(data)

        assert "custom:" in result


class TestFormatJournalContent:
    """Tests for format_journal_content function (lines 174-206)"""

    def test_basic_content(self):
        """Test basic content formatting"""
        data = {
            "title": "Test Title",
            "date": "2026-03-10",
            "content": "This is the body content.",
        }
        result = format_journal_content(data)

        assert result.startswith("---")
        assert "# Test Title" in result
        assert "This is the body content." in result

    def test_content_without_title(self):
        """Test content without title"""
        data = {
            "date": "2026-03-10",
            "content": "Body without title.",
        }
        result = format_journal_content(data)

        assert "# " not in result.split("\n", 5)[-1]  # No H1 in body
        assert "Body without title." in result

    def test_attachments_dict_format(self):
        """Test attachments with dict format (lines 196-200)"""
        data = {
            "title": "Test",
            "date": "2026-03-10",
            "content": "Content",
            "attachments": [
                {
                    "filename": "photo.jpg",
                    "rel_path": "../attachments/photo.jpg",
                    "description": "A nice photo",
                }
            ],
        }
        result = format_journal_content(data)

        assert "## Attachments" in result
        assert "[photo.jpg]" in result
        assert "../attachments/photo.jpg" in result
        assert "A nice photo" in result

    def test_attachments_string_format(self):
        """Test attachments with string format (lines 201-202)"""
        data = {
            "title": "Test",
            "date": "2026-03-10",
            "content": "Content",
            "attachments": ["file1.mp4", "file2.pdf"],
        }
        result = format_journal_content(data)

        assert "## Attachments" in result
        assert "[file1.mp4](file1.mp4)" in result
        assert "[file2.pdf](file2.pdf)" in result

    def test_attachments_with_rel_path_fallback(self):
        """Test attachment uses rel_path or fallback to Attachments/"""
        data = {
            "title": "Test",
            "date": "2026-03-10",
            "content": "Content",
            "attachments": [{"filename": "no_path.png", "description": "No path"}],
        }
        result = format_journal_content(data)

        assert "Attachments/no_path.png" in result


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

    def test_schema_version_mismatch(self):
        """Schema version mismatch should generate warning (line 300)"""
        metadata = {
            "title": "Test",
            "date": "2026-03-10",
            "schema_version": 99,  # Future version
        }
        issues = validate_metadata(metadata)

        warnings = [i for i in issues if i["level"] == "warning"]
        assert any("schema_version" in w["field"] for w in warnings)
        assert any("Schema 版本不匹配" in w["message"] for w in warnings)


class TestUpdateFrontmatterFields:
    """Tests for update_frontmatter_fields function (lines 223-252)"""

    def test_dry_run(self, tmp_path):
        """Test dry_run mode doesn't modify file"""
        file_path = tmp_path / "test.md"
        original_content = """---
title: "Original"
date: 2026-03-10
---

# Original

Content.
"""
        file_path.write_text(original_content, encoding="utf-8")

        result = update_frontmatter_fields(
            file_path, {"title": "Updated"}, dry_run=True
        )

        assert result["success"] is True
        assert "title" in result["changes"]
        assert result["changes"]["title"]["old"] == "Original"
        assert result["changes"]["title"]["new"] == "Updated"

        # File should not be modified
        assert file_path.read_text(encoding="utf-8") == original_content

    def test_actual_update(self, tmp_path):
        """Test actual file update"""
        file_path = tmp_path / "test.md"
        original_content = """---
title: "Original"
date: 2026-03-10
---

# Original

Content.
"""
        file_path.write_text(original_content, encoding="utf-8")

        result = update_frontmatter_fields(
            file_path, {"title": "Updated"}, dry_run=False
        )

        assert result["success"] is True
        assert "title" in result["changes"]

        # File should be modified
        updated_content = file_path.read_text(encoding="utf-8")
        assert 'title: "Updated"' in updated_content
        assert "Content." in updated_content  # Body preserved

    def test_no_changes(self, tmp_path):
        """Test update with same value"""
        file_path = tmp_path / "test.md"
        content = """---
title: "Same"
date: 2026-03-10
---

# Title

Content.
"""
        file_path.write_text(content, encoding="utf-8")

        result = update_frontmatter_fields(file_path, {"title": "Same"}, dry_run=False)

        assert result["success"] is True
        assert result["changes"] == {}

    def test_file_not_found(self, tmp_path):
        """Test handling of file not found error"""
        file_path = tmp_path / "nonexistent.md"

        result = update_frontmatter_fields(file_path, {"title": "Test"}, dry_run=False)

        assert result["success"] is False
        assert result["error"] is not None

    def test_add_new_field(self, tmp_path):
        """Test adding a new field"""
        file_path = tmp_path / "test.md"
        content = """---
title: "Test"
date: 2026-03-10
---

# Title

Content.
"""
        file_path.write_text(content, encoding="utf-8")

        result = update_frontmatter_fields(
            file_path, {"weather": "Sunny"}, dry_run=False
        )

        assert result["success"] is True
        assert "weather" in result["changes"]

        updated_content = file_path.read_text(encoding="utf-8")
        assert 'weather: "Sunny"' in updated_content


class TestParseJournalFile:
    """Tests for parse_journal_file function (lines 88-111)"""

    def test_parse_valid_file(self, tmp_path):
        """Test parsing a valid journal file"""
        file_path = tmp_path / "test.md"
        content = """---
title: "Test Title"
date: 2026-03-10
location: "Beijing"
---

# Test Title

This is the body content.
"""
        file_path.write_text(content, encoding="utf-8")

        metadata = parse_journal_file(file_path)

        assert metadata["title"] == "Test Title"
        assert metadata["date"] == "2026-03-10"
        assert metadata["_body"] is not None
        assert metadata["_file"] == str(file_path)
        assert metadata["_title"] == "Test Title"

    def test_extract_abstract(self, tmp_path):
        """Test abstract extraction from body"""
        file_path = tmp_path / "test.md"
        content = """---
title: "Test"
date: 2026-03-10
---

# Title

This is a longer paragraph that should be extracted as abstract.
It has multiple sentences.

## Another section

More content here.
"""
        file_path.write_text(content, encoding="utf-8")

        metadata = parse_journal_file(file_path)

        assert "_abstract" in metadata
        assert "This is a longer paragraph" in metadata["_abstract"]

    def test_no_abstract(self, tmp_path):
        """Test file with no extractable abstract"""
        file_path = tmp_path / "test.md"
        content = """---
title: "Test"
date: 2026-03-10
---

# Title
"""
        file_path.write_text(content, encoding="utf-8")

        metadata = parse_journal_file(file_path)

        assert metadata["_abstract"] == "(无摘要)"

    def test_file_not_found(self, tmp_path):
        """Test handling of file not found"""
        file_path = tmp_path / "nonexistent.md"

        metadata = parse_journal_file(file_path)

        assert "_error" in metadata
        assert "_file" in metadata

    def test_unicode_content(self, tmp_path):
        """Test parsing file with Unicode content"""
        file_path = tmp_path / "test.md"
        content = """---
title: "测试标题"
date: 2026-03-10
location: "北京，中国"
---

# 测试标题

这是中文内容。👨‍👩‍👧
"""
        file_path.write_text(content, encoding="utf-8")

        metadata = parse_journal_file(file_path)

        assert metadata["title"] == "测试标题"
        assert "这是中文内容" in metadata["_body"]


class TestMigrateMetadata:
    """Tests for migrate_metadata function (lines 330-348)"""

    def test_current_version(self):
        """Test migration when version matches"""
        metadata = {
            "title": "Test",
            "date": "2026-03-10",
            "schema_version": 1,
        }

        result = migrate_metadata(metadata)

        assert result["schema_version"] == 1
        assert result["title"] == "Test"

    def test_no_schema_version(self):
        """Test migration when no schema_version present (defaults to 1)"""
        metadata = {
            "title": "Test",
            "date": "2026-03-10",
        }

        result = migrate_metadata(metadata)

        # When no schema_version, defaults to 1, which matches current
        # So no migration happens, schema_version not added
        assert "schema_version" not in result or result["schema_version"] == 1
        assert result["title"] == "Test"

    def test_future_version(self):
        """Test migration framework for future versions"""
        metadata = {
            "title": "Test",
            "date": "2026-03-10",
            "schema_version": 5,  # Future version
        }

        result = migrate_metadata(metadata)

        # Should update to current version
        assert result["schema_version"] == 1


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

    def test_get_schema_version(self):
        """Test get_schema_version function (line 313)"""
        version = get_schema_version()
        assert version == 1
        assert isinstance(version, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
