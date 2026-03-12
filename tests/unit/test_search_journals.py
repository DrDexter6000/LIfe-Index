#!/usr/bin/env python3
"""
Unit tests for search_journals.py core functions
"""

import pytest
from pathlib import Path
import sys

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from lib.frontmatter import parse_frontmatter


class TestParseFrontmatter:
    """Tests for parse_frontmatter function"""

    def test_valid_frontmatter(self):
        """Valid frontmatter should be parsed correctly"""
        content = """---
title: "Test Title"
date: 2026-03-10
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
        assert metadata["date"] == "2026-03-10"
        assert metadata["location"] == "Beijing, China"
        assert "work" in str(metadata["topic"])
        assert "Test Content" in body

    def test_no_frontmarker_returns_empty(self):
        """Content without --- marker should return empty metadata"""
        content = """# Test Title

This is just regular markdown.
"""
        metadata, body = parse_frontmatter(content)

        assert metadata == {}
        assert content in body or body == content

    def test_incomplete_frontmatter(self):
        """Incomplete frontmatter should be handled gracefully"""
        content = """---
title: "Test"

No closing marker.
"""
        metadata, body = parse_frontmatter(content)

        # Should handle gracefully, either empty or partial
        assert isinstance(metadata, dict)

    def test_array_parsing(self):
        """Arrays in frontmatter should be parsed correctly"""
        content = """---
mood: ["happy", "focused"]
tags: ["tag1", "tag2"]
---
Body content.
"""
        metadata, body = parse_frontmatter(content)

        # Arrays should be preserved
        assert "mood" in metadata or "happy" in str(metadata)

    def test_empty_frontmatter(self):
        """Empty frontmatter section should be handled"""
        content = """---
---

Body content.
"""
        metadata, body = parse_frontmatter(content)

        assert isinstance(metadata, dict)
        assert "Body content" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
