#!/usr/bin/env python3
"""
Life Index - Query Weather Tool
查询指定日期和地点的天气信息 (使用 Open-Meteo API)

Usage:
    python -m tools.query_weather --location "Lagos" --date 2026-03-04
    python -m tools.query_weather --lat 6.5244 --lon 3.3792 --date 2026-03-04
    python -m tools.query_weather --location "Lagos,Nigeria" --date 2026-03-04 --format detailed
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

# Open-Meteo API 端点
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_API = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"


def geocode_location(location: str) -> Optional[Dict[str, Any]]:
    """
    将地点名称转换为经纬度

    Returns:
        {
            "name": str,
            "latitude": float,
            "longitude": float,
            "country": str,
            "admin1": str (省份/州)
        }
    """
    try:
        params = urllib.parse.urlencode(
            {"name": location, "count": 5, "language": "en", "format": "json"}
        )
        url = f"{GEOCODING_API}?{params}"

        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        if not data.get("results"):
            return None

        # 返回第一个结果
        result = data["results"][0]
        return {
            "name": result.get("name", ""),
            "latitude": result.get("latitude", 0),
            "longitude": result.get("longitude", 0),
            "country": result.get("country", ""),
            "admin1": result.get("admin1", ""),
        }

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        TimeoutError,
    ) as e:
        return {"error": str(e)}


def get_weather_code_description(code: int) -> str:
    """将 WMO Weather interpretation codes 转换为描述"""
    codes = {
        0: "Clear sky (晴朗)",
        1: "Mainly clear (大部晴朗)",
        2: "Partly cloudy (多云)",
        3: "Overcast (阴天)",
        45: "Fog (雾)",
        48: "Depositing rime fog (雾凇)",
        51: "Light drizzle (毛毛雨)",
        53: "Moderate drizzle (中雨)",
        55: "Dense drizzle (大雨)",
        61: "Slight rain (小雨)",
        63: "Moderate rain (中雨)",
        65: "Heavy rain (大雨)",
        71: "Slight snow (小雪)",
        73: "Moderate snow (中雪)",
        75: "Heavy snow (大雪)",
        77: "Snow grains (雪粒)",
        80: "Slight rain showers (阵雨)",
        81: "Moderate rain showers (中阵雨)",
        82: "Violent rain showers (强阵雨)",
        85: "Slight snow showers (阵雪)",
        86: "Heavy snow showers (强阵雪)",
        95: "Thunderstorm (雷雨)",
        96: "Thunderstorm with slight hail (雷雨伴小冰雹)",
        99: "Thunderstorm with heavy hail (雷雨伴大冰雹)",
    }
    return codes.get(code, f"Unknown weather code: {code}")


def simplify_weather(description: str) -> str:
    """简化天气描述为常用词汇"""
    description_lower = description.lower()

    if any(word in description_lower for word in ["clear", "sunny"]):
        return "晴天"
    elif any(word in description_lower for word in ["partly cloudy", "cloudy"]):
        return "多云"
    elif any(word in description_lower for word in ["overcast"]):
        return "阴天"
    elif any(word in description_lower for word in ["rain", "drizzle", "shower"]):
        return "雨天"
    elif any(word in description_lower for word in ["snow"]):
        return "雪天"
    elif any(word in description_lower for word in ["fog", "mist"]):
        return "雾天"
    elif any(word in description_lower for word in ["thunder"]):
        return "雷雨"
    else:
        return "未知"


def query_weather(
    latitude: float, longitude: float, date: str, timezone: str = "auto"
) -> Dict[str, Any]:
    """
    查询指定坐标和日期的天气

    Args:
        latitude: 纬度
        longitude: 经度
        date: 日期 (YYYY-MM-DD)
        timezone: 时区

    Returns:
        {
            "success": bool,
            "date": str,
            "location": {"lat": float, "lon": float},
            "weather": {
                "code": int,
                "description": str,
                "simple": str,
                "temperature_max": float,
                "temperature_min": float,
                "precipitation": float
            },
            "error": str (optional)
        }
    """
    result = {
        "success": False,
        "date": date,
        "location": {"lat": latitude, "lon": longitude},
        "weather": {},
        "error": None,
    }

    try:
        # 判断是历史数据还是未来预报
        query_date = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.now().date()

        # Open-Meteo archive API 支持到昨天，今天及以后用 forecast
        if query_date < today:
            api_url = WEATHER_API
        else:
            api_url = FORECAST_API

        params = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": date,
                "end_date": date,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": timezone,
            }
        )

        url = f"{api_url}?{params}"

        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        daily = data.get("daily", {})

        if not daily or not daily.get("weather_code"):
            result["error"] = "No weather data available for this date"
            return result

        weather_code = daily["weather_code"][0]
        description = get_weather_code_description(weather_code)

        result["weather"] = {
            "code": weather_code,
            "description": description,
            "simple": simplify_weather(description),
            "temperature_max": daily.get("temperature_2m_max", [None])[0],
            "temperature_min": daily.get("temperature_2m_min", [None])[0],
            "precipitation": daily.get("precipitation_sum", [None])[0],
        }
        result["success"] = True

    except urllib.error.HTTPError as e:
        result["error"] = f"API error: {e.code} - {e.reason}"
    except urllib.error.URLError as e:
        result["error"] = f"Network error: {e.reason}"
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        result["error"] = str(e)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Life Index - Query Weather Tool (Open-Meteo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.query_weather --location "Lagos"
    python -m tools.query_weather --location "Beijing,China" --date 2026-03-04
    python -m tools.query_weather --lat 6.5244 --lon 3.3792 --date 2026-03-04
    python -m tools.query_weather --location "Paris" --format simple
        """,
    )

    parser.add_argument("--location", help='地点名称 (如 "Lagos", "Beijing,China")')

    parser.add_argument("--lat", type=float, help="纬度")

    parser.add_argument("--lon", type=float, help="经度")

    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="日期 (YYYY-MM-DD), 默认今天",
    )

    parser.add_argument(
        "--format", choices=["detailed", "simple"], default="detailed", help="输出格式"
    )

    parser.add_argument("--timezone", default="auto", help="时区 (默认 auto)")

    args = parser.parse_args()

    # 验证参数
    if not args.location and (args.lat is None or args.lon is None):
        print(
            json.dumps(
                {"success": False, "error": "必须提供 --location 或 --lat/--lon"},
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

    # 获取坐标
    if args.location:
        geo_result = geocode_location(args.location)
        if geo_result is None:
            print(
                json.dumps(
                    {"success": False, "error": f"无法找到地点: {args.location}"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            sys.exit(1)
        if "error" in geo_result:
            print(
                json.dumps(
                    {"success": False, "error": f"地理编码错误: {geo_result['error']}"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            sys.exit(1)

        latitude = geo_result["latitude"]
        longitude = geo_result["longitude"]
        location_name = f"{geo_result['name']}, {geo_result.get('admin1', '')}, {geo_result['country']}".strip(
            ", "
        )
    else:
        latitude = args.lat
        longitude = args.lon
        location_name = f"{latitude}, {longitude}"

    # 查询天气
    result = query_weather(latitude, longitude, args.date, args.timezone)
    result["location_name"] = location_name

    # 格式化输出
    if args.format == "simple" and result["success"]:
        simple_output = {
            "success": True,
            "location": location_name,
            "date": args.date,
            "weather": result["weather"].get("simple", "未知"),
            "temp_high": result["weather"].get("temperature_max"),
            "temp_low": result["weather"].get("temperature_min"),
        }
        print(json.dumps(simple_output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
