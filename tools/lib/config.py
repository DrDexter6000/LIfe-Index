"""
Life Index - Shared Configuration Module
=======================================
Centralized configuration for all atomic tools.
"""

import os
from pathlib import Path
from datetime import datetime

# User data directory (OS standard user documents directory)
# Uses Path.home() for cross-platform compatibility:
#   Windows: C:\Users\<username>\Documents\Life-Index
#   macOS:   ~/Documents/Life-Index
#   Linux:   ~/Documents/Life-Index
USER_DATA_DIR = Path.home() / "Documents" / "Life-Index"

# Project root (for reference only, not for data storage)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# Directory structure - POINT TO USER DATA DIR
JOURNALS_DIR = USER_DATA_DIR / "Journals"
BY_TOPIC_DIR = USER_DATA_DIR / "by-topic"
ATTACHMENTS_DIR = USER_DATA_DIR / "attachments"

# Abstracts directory (stored within Journals for co-location)
ABSTRACTS_DIR = JOURNALS_DIR

# Note: Abstracts are stored within Journals directory structure:
#   - Monthly: Journals/YYYY/MM/monthly_abstract.md
#   - Yearly:  Journals/YYYY/yearly_abstract.md
# This keeps abstracts co-located with the journals they summarize.

# Ensure directories exist
for dir_path in [JOURNALS_DIR, BY_TOPIC_DIR, ATTACHMENTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# File naming patterns
JOURNAL_FILENAME_PATTERN = "{project}_{date}_{seq:03d}.md"
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M"

# YAML Frontmatter template
JOURNAL_TEMPLATE = """---
date: {date}
time: {time}
location: {location}
weather: {weather}
topic: {topic}
project: {project}
tags: {tags}
seq: {seq}
---

{content}
"""

# Default values
DEFAULT_LOCATION = "重庆，中国"
DEFAULT_TOPIC = "life"
DEFAULT_PROJECT = "life-index"

# Weather API configuration
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def get_journal_dir(year: int = None, month: int = None) -> Path:
    """Get journal directory for given year/month (defaults to current)."""
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    return JOURNALS_DIR / str(year) / f"{month:02d}"


def get_next_sequence(project: str, date_str: str) -> int:
    """Get next sequence number for a project on a given date."""
    year, month, _ = date_str.split('-')
    journal_dir = JOURNALS_DIR / year / month

    if not journal_dir.exists():
        return 1

    # Find existing files for this project and date
    pattern = f"{project}_{date_str}_*.md"
    existing = list(journal_dir.glob(pattern))

    if not existing:
        return 1

    # Extract sequence numbers
    seq_nums = []
    for f in existing:
        try:
            seq_part = f.stem.split('_')[-1]
            seq_nums.append(int(seq_part))
        except (ValueError, IndexError):
            continue

    return max(seq_nums, default=0) + 1


def parse_frontmatter(file_path: Path) -> dict:
    """Parse YAML frontmatter from a markdown file."""
    content = file_path.read_text(encoding='utf-8')

    if not content.startswith('---'):
        return {}

    try:
        _, fm, body = content.split('---', 2)
        import yaml
        metadata = yaml.safe_load(fm.strip())
        metadata['_body'] = body.strip()
        metadata['_file'] = str(file_path)
        return metadata
    except Exception:
        return {}
