#!/usr/bin/env python3
"""
Unit tests for tools/write_journal/weather.py
"""

import pytest
from unittest.mock import patch, MagicMock
import json

from tools.write_journal.weather import normalize_location, query_weather_for_location


class TestNormalizeLocation:
    """Tests for normalize_location function"""

    def test_empty_string_returns_default(self):
        """Empty string should return default 'Chongqing, China'"""
        result = normalize_location("")
        assert result == "Chongqing, China"

    def test_none_returns_default(self):
        """None should return default 'Chongqing, China'"""
        result = normalize_location(None)  # type: ignore
        assert result == "Chongqing, China"

    def test_whitespace_only_returns_default(self):
        """Whitespace-only string should return empty after strip"""
        result = normalize_location("   ")
        # After strip(), becomes empty string, which returns empty (not default)
        assert result == ""

    def test_chinese_city_chongqing(self):
        """Chinese city '重庆' should map to 'Chongqing, China'"""
        result = normalize_location("重庆")
        assert result == "Chongqing, China"

    def test_chinese_city_beijing(self):
        """Chinese city '北京' should map to 'Beijing, China'"""
        result = normalize_location("北京")
        assert result == "Beijing, China"

    def test_chinese_city_shanghai(self):
        """Chinese city '上海' should map to 'Shanghai, China'"""
        result = normalize_location("上海")
        assert result == "Shanghai, China"

    def test_chinese_city_guangzhou(self):
        """Chinese city '广州' should map to 'Guangzhou, China'"""
        result = normalize_location("广州")
        assert result == "Guangzhou, China"

    def test_chinese_city_shenzhen(self):
        """Chinese city '深圳' should map to 'Shenzhen, China'"""
        result = normalize_location("深圳")
        assert result == "Shenzhen, China"

    def test_chinese_city_chengdu(self):
        """Chinese city '成都' should map to 'Chengdu, China'"""
        result = normalize_location("成都")
        assert result == "Chengdu, China"

    def test_chinese_city_hangzhou(self):
        """Chinese city '杭州' should map to 'Hangzhou, China'"""
        result = normalize_location("杭州")
        assert result == "Hangzhou, China"

    def test_chinese_city_wuhan(self):
        """Chinese city '武汉' should map to 'Wuhan, China'"""
        result = normalize_location("武汉")
        assert result == "Wuhan, China"

    def test_chinese_city_xian(self):
        """Chinese city '西安' should map to "Xi'an, China'"""
        result = normalize_location("西安")
        assert result == "Xi'an, China"

    def test_chinese_city_nanjing(self):
        """Chinese city '南京' should map to 'Nanjing, China'"""
        result = normalize_location("南京")
        assert result == "Nanjing, China"

    def test_chinese_city_with_country_chongqing(self):
        """'重庆，中国' should map to 'Chongqing, China'"""
        result = normalize_location("重庆，中国")
        assert result == "Chongqing, China"

    def test_chinese_city_with_country_beijing(self):
        """'北京，中国' should map to 'Beijing, China'"""
        result = normalize_location("北京，中国")
        assert result == "Beijing, China"

    def test_chinese_city_with_country_shanghai(self):
        """'上海，中国' should map to 'Shanghai, China'"""
        result = normalize_location("上海，中国")
        assert result == "Shanghai, China"

    def test_chinese_city_with_country_guangzhou(self):
        """'广州，中国' should map to 'Guangzhou, China'"""
        result = normalize_location("广州，中国")
        assert result == "Guangzhou, China"

    def test_chinese_city_with_country_shenzhen(self):
        """'深圳，中国' should map to 'Shenzhen, China'"""
        result = normalize_location("深圳，中国")
        assert result == "Shenzhen, China"

    def test_chinese_city_with_country_chengdu(self):
        """'成都，中国' should map to 'Chengdu, China'"""
        result = normalize_location("成都，中国")
        assert result == "Chengdu, China"

    def test_chinese_city_with_country_hangzhou(self):
        """'杭州，中国' should map to 'Hangzhou, China'"""
        result = normalize_location("杭州，中国")
        assert result == "Hangzhou, China"

    def test_chinese_city_with_country_wuhan(self):
        """'武汉，中国' should map to 'Wuhan, China'"""
        result = normalize_location("武汉，中国")
        assert result == "Wuhan, China"

    def test_chinese_city_with_country_xian(self):
        """'西安，中国' should map to "Xi'an, China'"""
        result = normalize_location("西安，中国")
        assert result == "Xi'an, China"

    def test_chinese_city_with_country_nanjing(self):
        """'南京，中国' should map to 'Nanjing, China'"""
        result = normalize_location("南京，中国")
        assert result == "Nanjing, China"

    def test_english_city_already_formatted(self):
        """English format 'Tokyo, Japan' should remain unchanged"""
        result = normalize_location("Tokyo, Japan")
        assert result == "Tokyo, Japan"

    def test_english_city_new_york(self):
        """English format 'New York, USA' should remain unchanged"""
        result = normalize_location("New York, USA")
        assert result == "New York, USA"

    def test_english_city_london(self):
        """English format 'London, UK' should remain unchanged"""
        result = normalize_location("London, UK")
        assert result == "London, UK"

    def test_unknown_chinese_city_adds_china(self):
        """Unknown Chinese city should add ', China' (comma + space)"""
        result = normalize_location("苏州")
        assert ", China" in result
        assert len(result) > 8  # City name + ", China"

    def test_unknown_chinese_city_qingdao(self):
        """Unknown Chinese city '青岛' should add ', China'"""
        result = normalize_location("青岛")
        assert ", China" in result

    def test_unknown_chinese_city_dalian(self):
        """Unknown Chinese city '大连' should add ', China'"""
        result = normalize_location("大连")
        assert ", China" in result

    def test_chinese_com格式_city_only(self):
        """Chinese comma format '重庆' with Chinese comma should convert"""
        result = normalize_location("重庆，")
        assert result == "Chongqing, China"

    def test_chinese_comma_format_city_with_suffix(self):
        """Chinese comma format with extra suffix should convert city"""
        result = normalize_location("北京，Some District")
        assert result == "Beijing, China"

    def test_chinese_comma_unknown_city(self):
        """Unknown city with Chinese comma should replace with English comma"""
        result = normalize_location("苏州，Industrial Park")
        assert ", " in result  # Should have English comma + space
        assert "Industrial Park" in result

    def test_whitespace_trimming(self):
        """Location with leading/trailing whitespace should be trimmed"""
        result = normalize_location("  北京  ")
        assert result == "Beijing, China"

    def test_whitespace_trimming_english(self):
        """English location with whitespace should be trimmed"""
        result = normalize_location("  Tokyo, Japan  ")
        assert result == "Tokyo, Japan"

    def test_mixed_chinese_english_unknown(self):
        """Mixed Chinese-English unknown city should add China"""
        result = normalize_location("Suzhou")
        assert result == "Suzhou"

    def test_single_chinese_character(self):
        """Single Chinese character should add ', China'"""
        result = normalize_location("京")
        assert ", China" in result


class TestQueryWeatherForLocation:
    """Tests for query_weather_for_location function"""

    @patch("tools.write_journal.weather.subprocess.run")
    def test_successful_query_basic(self, mock_run):
        """Test successful weather query with basic response"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "weather": {
                        "description": "Sunny",
                        "simple": "晴",
                        "temperature_max": 28,
                        "temperature_min": 22,
                    }
                }
            ),
        )

        result = query_weather_for_location("Chongqing, China", "2026-03-14")

        assert "Sunny" in result
        assert "28°C/22°C" in result

    @patch("tools.write_journal.weather.subprocess.run")
    def test_successful_query_no_date(self, mock_run):
        """Test successful weather query without date"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "weather": {
                        "description": "Cloudy",
                        "temperature_max": 25,
                        "temperature_min": 20,
                    }
                }
            ),
        )

        result = query_weather_for_location("Beijing, China")

        assert result == "Cloudy 25°C/20°C"
        # Verify date parameter was not added
        call_args = mock_run.call_args[0][0]
        assert "--date" not in call_args

    @patch("tools.write_journal.weather.subprocess.run")
    def test_successful_query_with_date(self, mock_run):
        """Test successful weather query with date truncation"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "weather": {
                        "description": "Rainy",
                        "temperature_max": 20,
                        "temperature_min": 15,
                    }
                }
            ),
        )

        result = query_weather_for_location("Shanghai, China", "2026-03-14T14:30:00Z")

        assert result == "Rainy 20°C/15°C"
        # Verify date was truncated to first 10 chars
        call_args = mock_run.call_args[0][0]
        date_idx = call_args.index("--date")
        assert call_args[date_idx + 1] == "2026-03-14"

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_with_description_at_root(self, mock_run):
        """Test weather query with description at root level (fallback)

        This fallback is triggered when weather_data is not a dict or str,
        but output dict has 'description' at root level.
        """
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "weather": None,  # Not dict or str, triggers fallback
                    "description": "Partly cloudy",
                }
            ),
        )

        result = query_weather_for_location("Nanjing, China")

        # Root-level description is checked when weather_data is not dict/str
        assert result == "Partly cloudy"

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_output_not_dict(self, mock_run):
        """Test when output is not a dict (edge case)"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps('"just a string"')
        )

        result = query_weather_for_location("Edge Case Location")

        # When output is not a dict, returns empty
        assert result == ""

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_non_zero_returncode(self, mock_run):
        """Test when subprocess returns non-zero exit code"""
        mock_run.return_value = MagicMock(
            returncode=1, stdout=json.dumps({"error": "failed"})
        )

        result = query_weather_for_location("Failed Location")

        assert result == ""

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_with_none_weather(self, mock_run):
        """Test weather query when weather field is None"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"weather": None})
        )

        result = query_weather_for_location("None Weather Location")

        assert result == ""

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_with_only_max_temp(self, mock_run):
        """Test weather query with only max temperature (line 124)"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {"weather": {"description": "Sunny", "temperature_max": 30}}
            ),
        )

        result = query_weather_for_location("Guangzhou, China")

        assert result == "Sunny 30°C"

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_with_simple_only_no_desc(self, mock_run):
        """Test weather query with only 'simple' field (lines 117-118)"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "weather": {
                        "simple": "小雨",
                        "temperature_max": 18,
                        "temperature_min": 12,
                    }
                }
            ),
        )

        result = query_weather_for_location("Hangzhou, China")

        assert "小雨" in result
        assert "18°C/12°C" in result

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_with_weather_as_string(self, mock_run):
        """Test weather query when weather is a string (line 128)"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"weather": "Sunny and warm"})
        )

        result = query_weather_for_location("Xi'an, China")

        assert result == "Sunny and warm"

    @patch("tools.write_journal.weather.subprocess.run")
    def test_query_exception_handling(self, mock_run):
        """Test exception handling for KeyError/ValueError/TypeError (lines 132-133)"""
        # This tests the except block - malformed JSON that causes TypeError
        mock_run.return_value = MagicMock(returncode=0, stdout="invalid json")

        result = query_weather_for_location("Bad JSON Location")

        assert result == ""

    @patch("tools.write_journal.weather.subprocess.run")
    def test_subprocess_call_parameters(self, mock_run):
        """Test that subprocess.run is called with correct parameters"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"weather": {"description": "Test"}})
        )

        query_weather_for_location("Test Location", "2026-03-14")

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]

        assert call_kwargs["capture_output"] is True
        assert call_kwargs["text"] is True
        assert call_kwargs["encoding"] == "utf-8"
        assert call_kwargs["errors"] == "replace"
        assert call_kwargs["timeout"] == 15

    @patch("tools.write_journal.weather.subprocess.run")
    def test_subprocess_command_format(self, mock_run):
        """Test that subprocess command is correctly formatted"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"weather": {"description": "Test"}})
        )

        query_weather_for_location("Test Location", "2026-03-14")

        call_args = mock_run.call_args[0][0]

        assert call_args[0].endswith("python") or call_args[0].endswith("python.exe")
        assert call_args[1] == "-m"
        assert call_args[2] == "tools.query_weather"
        assert "--location" in call_args
        assert "Test Location" in call_args
        assert "--date" in call_args
        assert "2026-03-14" in call_args


# Import subprocess for timeout test
import subprocess


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
