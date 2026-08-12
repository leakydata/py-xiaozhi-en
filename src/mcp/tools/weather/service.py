"""Weather data via Open-Meteo.

Open-Meteo needs no API key, has no geo restrictions and covers the whole world,
which is why it replaced the previous hard-coded mock. Two calls are involved:
geocoding (city name -> lat/lon) and the forecast itself.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import aiohttp

from src.logging import get_logger

logger = get_logger()

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Geocoding is stable and repeated constantly for the same few cities.
_geo_cache: dict[str, dict] = {}

# WMO weather interpretation codes -> plain English.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


def _describe(code: Any) -> str:
    try:
        return _WMO.get(int(code), f"unknown (code {code})")
    except (TypeError, ValueError):
        return "unknown"


def _units(args: dict[str, Any]) -> tuple[str, str, str]:
    """Default to Fahrenheit/mph; callers can ask for metric."""
    metric = str(args.get("units", "imperial")).lower() in ("metric", "celsius", "c")
    if metric:
        return "celsius", "kmh", "C"
    return "fahrenheit", "mph", "F"


async def _geocode(session: aiohttp.ClientSession, city: str) -> Optional[dict]:
    key = city.strip().lower()
    if key in _geo_cache:
        return _geo_cache[key]
    params = {"name": city, "count": 1, "language": "en", "format": "json"}
    async with session.get(_GEOCODE_URL, params=params) as r:
        if r.status != 200:
            logger.warning(f"[WeatherTool] geocoding HTTP {r.status} for {city!r}")
            return None
        data = await r.json()
    results = data.get("results") or []
    if not results:
        return None
    hit = results[0]
    place = {
        "name": hit.get("name"),
        "admin1": hit.get("admin1"),
        "country": hit.get("country"),
        "latitude": hit.get("latitude"),
        "longitude": hit.get("longitude"),
    }
    _geo_cache[key] = place
    return place


def _label(place: dict) -> str:
    parts = [place.get("name"), place.get("admin1"), place.get("country")]
    return ", ".join(p for p in parts if p)


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


async def get_weather_payload(args: dict[str, Any]) -> str:
    """Current conditions for a city."""
    city = str(args.get("city", "")).strip()
    if not city:
        return _err("No city given. Ask the user which city they mean.")
    temp_unit, wind_unit, tsym = _units(args)
    logger.info(f"[WeatherTool] current weather for {city}")
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            place = await _geocode(session, city)
            if not place:
                return _err(f"Could not find a place called {city!r}.")
            params = {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": ",".join([
                    "temperature_2m", "apparent_temperature", "relative_humidity_2m",
                    "precipitation", "weather_code", "wind_speed_10m",
                ]),
                "temperature_unit": temp_unit,
                "wind_speed_unit": wind_unit,
                "timezone": "auto",
            }
            async with session.get(_FORECAST_URL, params=params) as r:
                if r.status != 200:
                    return _err(f"Weather service returned HTTP {r.status}.")
                data = await r.json()
    except Exception as e:
        logger.warning(f"[WeatherTool] current weather failed: {e}")
        return _err(f"Weather lookup failed: {e}")

    cur = data.get("current", {})
    return json.dumps({
        "location": _label(place),
        "condition": _describe(cur.get("weather_code")),
        "temperature": cur.get("temperature_2m"),
        "feels_like": cur.get("apparent_temperature"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precipitation": cur.get("precipitation"),
        "wind_speed": cur.get("wind_speed_10m"),
        "units": {"temperature": tsym, "wind": wind_unit},
        "observed_at": cur.get("time"),
    }, ensure_ascii=False)


async def get_forecast_payload(args: dict[str, Any]) -> str:
    """Daily forecast, 1-7 days."""
    city = str(args.get("city", "")).strip()
    if not city:
        return _err("No city given. Ask the user which city they mean.")
    try:
        days = max(1, min(7, int(args.get("days", 3))))
    except (TypeError, ValueError):
        days = 3
    temp_unit, wind_unit, tsym = _units(args)
    logger.info(f"[WeatherTool] {days}-day forecast for {city}")
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            place = await _geocode(session, city)
            if not place:
                return _err(f"Could not find a place called {city!r}.")
            params = {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": ",".join([
                    "weather_code", "temperature_2m_max", "temperature_2m_min",
                    "precipitation_probability_max",
                ]),
                "forecast_days": days,
                "temperature_unit": temp_unit,
                "wind_speed_unit": wind_unit,
                "timezone": "auto",
            }
            async with session.get(_FORECAST_URL, params=params) as r:
                if r.status != 200:
                    return _err(f"Weather service returned HTTP {r.status}.")
                data = await r.json()
    except Exception as e:
        logger.warning(f"[WeatherTool] forecast failed: {e}")
        return _err(f"Forecast lookup failed: {e}")

    d = data.get("daily", {})
    dates = d.get("time", []) or []
    out = []
    for i, date in enumerate(dates[:days]):
        def at(key, idx=i):
            seq = d.get(key) or []
            return seq[idx] if idx < len(seq) else None
        out.append({
            "date": date,
            "condition": _describe(at("weather_code")),
            "high": at("temperature_2m_max"),
            "low": at("temperature_2m_min"),
            "precip_chance_pct": at("precipitation_probability_max"),
        })
    return json.dumps({
        "location": _label(place),
        "units": {"temperature": tsym},
        "forecast": out,
    }, ensure_ascii=False)
