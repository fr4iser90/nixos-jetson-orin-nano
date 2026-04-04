"""OpenWeather current conditions (API key from environment only)."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import httpx

__version__ = "1.1.0"
TOOL_ID = "openweather"

_OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


def _api_key() -> str:
    return (os.environ.get("OPENWEATHER_API_KEY") or "").strip()


def openweather_current(arguments: dict[str, Any]) -> str:
    """
    Current weather for a place name (OpenWeather ``/weather``, metric units).
    API key: ``OPENWEATHER_API_KEY`` in the agent container environment only.
    """
    loc = str(arguments.get("location") or "").strip()
    if not loc:
        return json.dumps({"ok": False, "error": "location is required"}, ensure_ascii=False)
    key = _api_key()
    if not key:
        return json.dumps(
            {
                "ok": False,
                "error": "OPENWEATHER_API_KEY is not set in the agent environment",
                "hint": "Set it in docker/.env for the agent-layer service and restart.",
            },
            ensure_ascii=False,
        )
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                _OPENWEATHER_URL,
                params={"q": loc, "units": "metric", "appid": key},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {
                "ok": False,
                "error": f"OpenWeather HTTP {e.response.status_code}",
                "detail": (e.response.text or "")[:800],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    main = data.get("main") if isinstance(data.get("main"), dict) else {}
    wind = data.get("wind") if isinstance(data.get("wind"), dict) else {}
    clouds = data.get("clouds") if isinstance(data.get("clouds"), dict) else {}
    coord = data.get("coord") if isinstance(data.get("coord"), dict) else {}
    sys_o = data.get("sys") if isinstance(data.get("sys"), dict) else {}
    weather = data.get("weather")
    w0 = weather[0] if isinstance(weather, list) and weather and isinstance(weather[0], dict) else {}

    out: dict[str, Any] = {
        "ok": True,
        "location_query": loc,
        "name": data.get("name"),
        "country": sys_o.get("country"),
        "lat": coord.get("lat"),
        "lon": coord.get("lon"),
        "temp_c": main.get("temp"),
        "feels_like_c": main.get("feels_like"),
        "temp_min_c": main.get("temp_min"),
        "temp_max_c": main.get("temp_max"),
        "humidity_pct": main.get("humidity"),
        "pressure_hpa": main.get("pressure"),
        "sea_level_hpa": main.get("sea_level"),
        "visibility_m": data.get("visibility"),
        "wind_speed_m_s": wind.get("speed"),
        "wind_deg": wind.get("deg"),
        "wind_gust_m_s": wind.get("gust"),
        "cloudiness_pct": clouds.get("all"),
        "weather_id": w0.get("id"),
        "weather_main": w0.get("main"),
        "weather_description": w0.get("description"),
        "sunrise_unix": sys_o.get("sunrise"),
        "sunset_unix": sys_o.get("sunset"),
        "timezone_offset_s": data.get("timezone"),
        "data_dt_unix": data.get("dt"),
    }
    return json.dumps(out, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "openweather_current": openweather_current,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "openweather_current",
            "description": (
                "Fetch current weather for a city or place using the OpenWeather API (one call, metric). "
                "API key must be set as environment variable OPENWEATHER_API_KEY on the server — never pass keys in chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name (and optional country), e.g. Berlin,de or Munich",
                    },
                },
                "required": ["location"],
            },
        },
    },
]
