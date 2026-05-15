"""Fetch hourly weather data for Tokyo from Open-Meteo API (no API key required)."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

JST = ZoneInfo("Asia/Tokyo")

TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503

_ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT_SEC  = 30
_MAX_RETRIES  = 3
_RETRY_BACKOFF_SEC = 2.0
_HOURLY_WEATHER_VARS = "temperature_2m,apparent_temperature"


def _fetch_json(url: str, params: dict) -> dict:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(full_url, timeout=_TIMEOUT_SEC) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_error = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except (OSError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e

        if attempt < _MAX_RETRIES:
            wait = _RETRY_BACKOFF_SEC * attempt
            print(
                f"[WARN] Weather fetch failed (attempt {attempt}/{_MAX_RETRIES}): {last_error}; retrying in {wait:.0f}s",
                file=sys.stderr,
            )
            time.sleep(wait)

    assert last_error is not None
    raise last_error


def _parse_response(data: dict) -> pd.DataFrame:
    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    apparent_temps = data["hourly"].get("apparent_temperature", temps)
    return pd.DataFrame({
        "ts":              pd.to_datetime(times).tz_localize("Asia/Tokyo"),
        "temp_c":          [float(t) if t is not None else float("nan") for t in temps],
        "apparent_temp_c": [float(t) if t is not None else float("nan") for t in apparent_temps],
    })


def fetch_past_temps(start: date, end: date) -> pd.DataFrame:
    """Hourly temperature from Open-Meteo archive for Tokyo (JST-aware ts)."""
    return _parse_response(_fetch_json(_ARCHIVE_URL, {
        "latitude":   TOKYO_LAT,
        "longitude":  TOKYO_LON,
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     _HOURLY_WEATHER_VARS,
        "timezone":   "Asia/Tokyo",
    }))


def fetch_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Hourly temperature forecast from Open-Meteo for Tokyo (next N days)."""
    return _parse_response(_fetch_json(_FORECAST_URL, {
        "latitude":      TOKYO_LAT,
        "longitude":     TOKYO_LON,
        "hourly":        _HOURLY_WEATHER_VARS,
        "timezone":      "Asia/Tokyo",
        "forecast_days": days,
    }))


def enrich_cache_with_weather(cache: pd.DataFrame) -> pd.DataFrame:
    """Add / fill weather columns in cache using Open-Meteo archive API.

    Only fetches date ranges where actual_mw exists but weather values are missing.
    Returns updated cache (original is not modified).
    """
    cache = cache.copy()
    if "temp_c" not in cache.columns:
        cache["temp_c"] = float("nan")
    if "apparent_temp_c" not in cache.columns:
        cache["apparent_temp_c"] = float("nan")

    missing_mask = (
        (cache["temp_c"].isna() | cache["apparent_temp_c"].isna())
        & cache["actual_mw"].notna()
    )
    if not missing_mask.any():
        return cache

    missing_dates = sorted(set(cache.loc[missing_mask, "ts"].dt.date))
    start, end = missing_dates[0], missing_dates[-1]
    print(f"[WEATHER] Fetching archive temps: {start} to {end} ({len(missing_dates)} dates)")

    try:
        weather    = fetch_past_temps(start, end)
        ts_to_temp = dict(zip(weather["ts"], weather["temp_c"]))
        ts_to_apparent_temp = dict(zip(weather["ts"], weather["apparent_temp_c"]))
        fill_mask = cache["actual_mw"].notna()
        temp_fill_mask = cache["temp_c"].isna() & fill_mask
        apparent_fill_mask = cache["apparent_temp_c"].isna() & fill_mask
        cache.loc[temp_fill_mask, "temp_c"] = cache.loc[temp_fill_mask, "ts"].map(ts_to_temp)
        cache.loc[apparent_fill_mask, "apparent_temp_c"] = (
            cache.loc[apparent_fill_mask, "ts"].map(ts_to_apparent_temp)
        )
        print(
            "[WEATHER] Filled "
            f"{int(temp_fill_mask.sum())} temp_c values, "
            f"{int(apparent_fill_mask.sum())} apparent_temp_c values"
        )
    except Exception as e:
        print(f"[WARN] Weather archive fetch failed: {e}", file=sys.stderr)

    return cache
