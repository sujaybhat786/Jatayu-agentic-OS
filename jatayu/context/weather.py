"""
JATAYU Weather Service
Fetches and caches current weather data for the configured location.
Uses Open-Meteo API (free, open access, no API key required).
"""

import logging
import json
import time
import urllib.request
import urllib.parse
import ssl
from typing import Dict, Any, Optional

from jatayu.config import get_config

logger = logging.getLogger(__name__)

# Open-Meteo WMO Weather interpretation codes
WMO_WEATHER_CODES = {
    0: ("Clear", "🌤"),
    1: ("Mainly Clear", "🌤"),
    2: ("Partly Cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫"),
    48: ("Rime Fog", "🌫"),
    51: ("Light Drizzle", "🌦"),
    53: ("Drizzle", "🌦"),
    55: ("Heavy Drizzle", "🌧"),
    61: ("Slight Rain", "🌧"),
    63: ("Moderate Rain", "🌧"),
    65: ("Heavy Rain", "🌧"),
    71: ("Slight Snow", "❄️"),
    73: ("Moderate Snow", "❄️"),
    75: ("Heavy Snow", "❄️"),
    80: ("Slight Showers", "🌦"),
    81: ("Moderate Showers", "🌦"),
    82: ("Violent Showers", "🌧"),
    95: ("Thunderstorm", "🌩"),
    96: ("Thunderstorm with Hail", "🌩"),
    99: ("Heavy Thunderstorm", "🌩"),
}

class WeatherService:
    """Service to retrieve, format, and cache local weather data."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, cache_ttl_seconds: int = 1800):
        self.config = config or get_config()
        self.cache_ttl = cache_ttl_seconds
        self._cached_data: Optional[Dict[str, Any]] = None
        self._last_fetch_time: float = 0.0

    def _get_location_config(self) -> Dict[str, Any]:
        loc = self.config.get("location", {})
        city = loc.get("city", "Mysuru")
        lat = loc.get("latitude", 12.2958)
        lon = loc.get("longitude", 76.6394)
        return {"city": city, "latitude": lat, "longitude": lon}

    def get_weather(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Retrieves weather info. Uses cached response if available and fresh.
        Returns None if fetching fails so JATAYU continues operating gracefully.
        """
        now = time.time()
        if not force_refresh and self._cached_data and (now - self._last_fetch_time < self.cache_ttl):
            return self._cached_data

        try:
            loc = self._get_location_config()
            lat = loc["latitude"]
            lon = loc["longitude"]
            city = loc["city"]

            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}&"
                f"current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&"
                f"daily=temperature_2m_max,temperature_2m_min,sunrise,sunset&"
                f"timezone=auto"
            )

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(url, headers={"User-Agent": "JATAYU-OS/1.0"})
            with urllib.request.urlopen(req, timeout=6.0, context=ssl_context) as resp:
                if resp.status != 200:
                    logger.warning("Weather API returned HTTP status %s", resp.status)
                    return self._cached_data

                raw_data = json.loads(resp.read().decode("utf-8"))

            current = raw_data.get("current", {})
            daily = raw_data.get("daily", {})

            weather_code = current.get("weather_code", 0)
            condition, icon = WMO_WEATHER_CODES.get(weather_code, ("Clear", "🌤"))

            # Format sunrise / sunset (ISO format e.g. "2026-07-20T05:58" -> "05:58")
            sunrise_raw = daily.get("sunrise", [""])[0]
            sunset_raw = daily.get("sunset", [""])[0]

            sunrise = sunrise_raw.split("T")[-1] if "T" in sunrise_raw else sunrise_raw
            sunset = sunset_raw.split("T")[-1] if "T" in sunset_raw else sunset_raw

            formatted_weather = {
                "city": city,
                "temp_c": round(current.get("temperature_2m", 25)),
                "condition": condition,
                "icon": icon,
                "high_c": round(daily.get("temperature_2m_max", [28])[0]),
                "low_c": round(daily.get("temperature_2m_min", [20])[0]),
                "humidity": round(current.get("relative_humidity_2m", 60)),
                "wind_kmh": round(current.get("wind_speed_10m", 10)),
                "sunrise": sunrise,
                "sunset": sunset
            }

            self._cached_data = formatted_weather
            self._last_fetch_time = now
            return formatted_weather

        except Exception as exc:
            logger.warning("Failed to fetch weather data: %s", exc)
            return self._cached_data
