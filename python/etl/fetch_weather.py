"""Fetch hourly weather data for Tokyo."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

JST = ZoneInfo("Asia/Tokyo")

TOKYO_LAT = 35.6589
TOKYO_LON = 139.7066

_ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
_OPEN_METEO_JMA_FORECAST_URL = "https://api.open-meteo.com/v1/jma"
_JMA_OFFICIAL_TIMESERIES_URL = "https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/130010.json"
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


def _to_jst_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(JST)
    return ts.tz_convert(JST)


def _optional_float(value) -> float:
    if value is None or value == "":
        return float("nan")
    return float(value)


def _extract_daily_extremes(point_series: dict, field: str, reducer) -> dict[date, float]:
    values = point_series.get(field, [])
    time_defines = point_series.get("timeDefines", [])
    by_date: dict[date, list[float]] = {}
    for time_define, value in zip(time_defines, values):
        parsed = _optional_float(value)
        if pd.isna(parsed):
            continue
        ts = _to_jst_timestamp(time_define["dateTime"])
        by_date.setdefault(ts.date(), []).append(parsed)
    return {target_date: reducer(vals) for target_date, vals in by_date.items() if vals}


def _apply_extreme_constraint(
    hourly: pd.DataFrame,
    target_date: date,
    target_value: float,
    mode: str,
) -> None:
    mask = hourly.index.date == target_date
    if not mask.any() or pd.isna(target_value):
        return

    values = hourly.loc[mask, "temp_c"].copy()
    if values.dropna().empty:
        return

    current_min = float(values.min())
    current_max = float(values.max())
    if mode == "max":
        current = current_max
        delta = target_value - current
        if abs(delta) < 0.05:
            return
        span = current_max - current_min
        weights = (values - current_min) / span if span > 0 else pd.Series(1.0, index=values.index)
        hourly.loc[mask, "temp_c"] = values + delta * weights.clip(0.0, 1.0)
        peak_idx = hourly.loc[mask, "temp_c"].idxmax()
        hourly.at[peak_idx, "temp_c"] = target_value
    elif mode == "min":
        current = current_min
        delta = target_value - current
        if abs(delta) < 0.05:
            return
        span = current_max - current_min
        weights = (current_max - values) / span if span > 0 else pd.Series(1.0, index=values.index)
        hourly.loc[mask, "temp_c"] = values + delta * weights.clip(0.0, 1.0)
        low_idx = hourly.loc[mask, "temp_c"].idxmin()
        hourly.at[low_idx, "temp_c"] = target_value


def _parse_jma_official_timeseries(
    data: dict,
    days: int = 3,
    today: date | None = None,
) -> pd.DataFrame:
    """Parse JMA official 3-hour Tokyo forecast into hourly temperatures."""
    point_series = data.get("pointTimeSeries", {})
    time_defines = point_series.get("timeDefines", [])
    temperatures = point_series.get("temperature", [])
    rows = []
    for time_define, temp in zip(time_defines, temperatures):
        parsed_temp = _optional_float(temp)
        if pd.isna(parsed_temp):
            continue
        rows.append({
            "ts": _to_jst_timestamp(time_define["dateTime"]),
            "temp_c": parsed_temp,
        })

    if len(rows) < 2:
        return pd.DataFrame(columns=["ts", "temp_c", "apparent_temp_c"])

    hourly = (
        pd.DataFrame(rows)
          .drop_duplicates(subset=["ts"], keep="last")
          .sort_values("ts")
          .set_index("ts")
          .resample("h")
          .interpolate(method="time")
    )

    max_by_date = _extract_daily_extremes(point_series, "maxTemperature", max)
    min_by_date = _extract_daily_extremes(point_series, "minTemperature", min)
    for target_date, target_max in max_by_date.items():
        _apply_extreme_constraint(hourly, target_date, target_max, "max")
    for target_date, target_min in min_by_date.items():
        _apply_extreme_constraint(hourly, target_date, target_min, "min")

    start_date = today or pd.Timestamp.now(tz=JST).date()
    end_date = start_date + timedelta(days=max(days, 1))
    hourly = hourly[
        (hourly.index.date >= start_date)
        & (hourly.index.date < end_date)
    ]
    if hourly.empty:
        return pd.DataFrame(columns=["ts", "temp_c", "apparent_temp_c"])

    hourly["temp_c"] = hourly["temp_c"].round(1)
    hourly["apparent_temp_c"] = hourly["temp_c"]
    return hourly.reset_index()[["ts", "temp_c", "apparent_temp_c"]]


def _fetch_open_meteo_jma_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Hourly temperature forecast from Open-Meteo JMA for Tokyo (fallback source)."""
    return _parse_response(_fetch_json(_OPEN_METEO_JMA_FORECAST_URL, {
        "latitude":      TOKYO_LAT,
        "longitude":     TOKYO_LON,
        "hourly":        _HOURLY_WEATHER_VARS,
        "timezone":      "Asia/Tokyo",
        "forecast_days": days,
    }))


def fetch_jma_official_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Hourly Tokyo temperatures interpolated from JMA official 3-hour forecast."""
    return _parse_jma_official_timeseries(_fetch_json(_JMA_OFFICIAL_TIMESERIES_URL, {}), days=days)


def _combine_official_and_fallback_weather(
    official: pd.DataFrame,
    fallback: pd.DataFrame,
) -> pd.DataFrame:
    if official.empty:
        return fallback
    if fallback.empty:
        return official

    combined = fallback.copy()
    official_temp = official[["ts", "temp_c"]].rename(columns={"temp_c": "_official_temp_c"})
    combined = combined.merge(official_temp, on="ts", how="left")
    has_official = combined["_official_temp_c"].notna()
    temp_delta = combined["_official_temp_c"] - combined["temp_c"]
    combined.loc[has_official, "temp_c"] = combined.loc[has_official, "_official_temp_c"]
    combined.loc[has_official & combined["apparent_temp_c"].notna(), "apparent_temp_c"] = (
        combined.loc[has_official & combined["apparent_temp_c"].notna(), "apparent_temp_c"]
        + temp_delta.loc[has_official & combined["apparent_temp_c"].notna()]
    )
    combined.loc[has_official & combined["apparent_temp_c"].isna(), "apparent_temp_c"] = (
        combined.loc[has_official & combined["apparent_temp_c"].isna(), "temp_c"]
    )
    combined = combined.drop(columns=["_official_temp_c"])

    missing_official = official[~official["ts"].isin(set(combined["ts"]))].copy()
    if not missing_official.empty:
        combined = pd.concat([combined, missing_official], ignore_index=True)

    combined["temp_c"] = combined["temp_c"].round(1)
    combined["apparent_temp_c"] = combined["apparent_temp_c"].round(1)
    return combined.sort_values("ts").reset_index(drop=True)


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
    """Hourly temperature forecast, preferring official JMA time-series data."""
    official = pd.DataFrame(columns=["ts", "temp_c", "apparent_temp_c"])
    fallback = pd.DataFrame(columns=["ts", "temp_c", "apparent_temp_c"])
    official_error: Exception | None = None
    fallback_error: Exception | None = None

    try:
        official = fetch_jma_official_forecast_temps(days=days)
    except Exception as e:
        official_error = e
        print(f"[WARN] JMA official forecast fetch failed: {e}", file=sys.stderr)

    try:
        fallback = _fetch_open_meteo_jma_forecast_temps(days=days)
    except Exception as e:
        fallback_error = e
        if official.empty:
            print(f"[WARN] Open-Meteo JMA fallback fetch failed: {e}", file=sys.stderr)

    if not official.empty:
        return _combine_official_and_fallback_weather(official, fallback)
    if not fallback.empty:
        return fallback
    raise official_error or fallback_error or RuntimeError("No forecast weather data available")


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
