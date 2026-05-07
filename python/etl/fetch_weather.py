"""Fetch hourly temperature data for Tokyo from Open-Meteo API (no API key required)."""
from __future__ import annotations

import json
import sys
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


def _fetch_json(url: str, params: dict) -> dict:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full_url, timeout=_TIMEOUT_SEC) as resp:
        return json.loads(resp.read())


def _parse_response(data: dict) -> pd.DataFrame:
    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    return pd.DataFrame({
        "ts":     pd.to_datetime(times).tz_localize("Asia/Tokyo"),
        "temp_c": [float(t) if t is not None else float("nan") for t in temps],
    })


def fetch_past_temps(start: date, end: date) -> pd.DataFrame:
    """Hourly temperature from Open-Meteo archive for Tokyo (JST-aware ts)."""
    return _parse_response(_fetch_json(_ARCHIVE_URL, {
        "latitude":   TOKYO_LAT,
        "longitude":  TOKYO_LON,
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     "temperature_2m",
        "timezone":   "Asia/Tokyo",
    }))


def fetch_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Hourly temperature forecast from Open-Meteo for Tokyo (next N days)."""
    return _parse_response(_fetch_json(_FORECAST_URL, {
        "latitude":      TOKYO_LAT,
        "longitude":     TOKYO_LON,
        "hourly":        "temperature_2m",
        "timezone":      "Asia/Tokyo",
        "forecast_days": days,
    }))


def enrich_cache_with_weather(cache: pd.DataFrame) -> pd.DataFrame:
    """Add / fill temp_c in cache using Open-Meteo archive API.

    Only fetches date ranges where actual_mw exists but temp_c is missing.
    Returns updated cache (original is not modified).
    """
    cache = cache.copy()
    if "temp_c" not in cache.columns:
        cache["temp_c"] = float("nan")

    missing_mask = cache["temp_c"].isna() & cache["actual_mw"].notna()
    if not missing_mask.any():
        return cache

    missing_dates = sorted(set(cache.loc[missing_mask, "ts"].dt.date))
    start, end = missing_dates[0], missing_dates[-1]
    print(f"[WEATHER] Fetching archive temps: {start} to {end} ({len(missing_dates)} dates)")

    try:
        weather    = fetch_past_temps(start, end)
        ts_to_temp = dict(zip(weather["ts"], weather["temp_c"]))
        fill_mask  = cache["temp_c"].isna() & cache["actual_mw"].notna()
        cache.loc[fill_mask, "temp_c"] = cache.loc[fill_mask, "ts"].map(ts_to_temp)
        print(f"[WEATHER] Filled {int(fill_mask.sum())} temp_c values")
    except Exception as e:
        print(f"[WARN] Weather archive fetch failed: {e}", file=sys.stderr)

    return cache
