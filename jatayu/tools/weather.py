"""Weather tool — via Open-Meteo (free, no API key required, no signup needed).

Defaults to Sujay's configured home location (config.yaml `location` block:
city/latitude/longitude) unless a different city is given, in which case it
geocodes that city first via Open-Meteo's free geocoding endpoint.
"""

from __future__ import annotations

import httpx

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _geocode(city: str):
    resp = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=8,
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        return None
    r = results[0]
    return r["latitude"], r["longitude"], r.get("name", city), r.get("country", "")


def get_weather(city: str = None) -> str:
    """Get current weather + today's forecast for a city (defaults to Sujay's home location)."""
    try:
        if city:
            geo = _geocode(city)
            if not geo:
                return f"⚠️ Couldn't find a location matching '{city}'."
            lat, lon, name, country = geo
            label = f"{name}, {country}" if country else name
        else:
            loc = get_config().get("location", {})
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            label = loc.get("city", "your location")
            if lat is None or lon is None:
                return "⚠️ No location configured, and no city was given."

        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "auto",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        temp = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        condition = WEATHER_CODES.get(current.get("weather_code"), "Unknown conditions")

        today_max = (daily.get("temperature_2m_max") or [None])[0]
        today_min = (daily.get("temperature_2m_min") or [None])[0]

        line = f"Weather in {label}: {condition}, {temp}°C right now (humidity {humidity}%, wind {wind} km/h)."
        if today_max is not None and today_min is not None:
            line += f" Today's range: {today_min}°C to {today_max}°C."
        return line

    except httpx.TimeoutException:
        return "⚠️ Weather service timed out — try again in a moment."
    except Exception as e:
        return f"⚠️ Couldn't fetch weather: {e}"


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="get_weather",
        description=(
            "Get current weather and today's forecast for a city. If no city is given, "
            "defaults to Sujay's home location."
        ),
        handler=get_weather,
        params=[
            ToolParam(name="city", type="string",
                      description="City name (optional — defaults to Sujay's home location if omitted)",
                      required=False),
        ],
    ))
