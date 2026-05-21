"""Fetch hourly weather data for Tokyo."""
from __future__ import annotations

import json
import math
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
_JMA_AMEDAS_POINT_URL = "https://www.jma.go.jp/bosai/amedas/data/point/{station}/{block}.json"
_JMA_TOKYO_AMEDAS_STATION = "44132"
_TIMEOUT_SEC  = 30
_MAX_RETRIES  = 3
_RETRY_BACKOFF_SEC = 2.0
_HOURLY_WEATHER_VARS = "temperature_2m,apparent_temperature,relative_humidity_2m"
_WEATHER_COLUMNS = [
    "ts", "temp_c", "apparent_temp_c", "humidity_pct",
    "discomfort_index", "weather_source",
]
_SOURCE_AMEDAS_ACTUAL = "AMEDAS_ACTUAL"
_SOURCE_JMA_FORECAST = "JMA_FORECAST"
_SOURCE_FORWARD_FILL = "FORWARD_FILL"
_SOURCE_OPEN_METEO_JMA = "OPEN_METEO_JMA"
_SOURCE_OPEN_METEO_ARCHIVE = "OPEN_METEO_ARCHIVE"
_SOURCE_SEASONAL_MEAN = "SEASONAL_MEAN"
_SOURCE_OPEN_METEO = "OPEN_METEO"


def _fetch_json(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}" if query else url
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


def _parse_response(data: dict, source: str = _SOURCE_OPEN_METEO) -> pd.DataFrame:
    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    apparent_temps = data["hourly"].get("apparent_temperature", temps)
    humidities = data["hourly"].get("relative_humidity_2m", [None] * len(times))
    temp_values = [float(t) if t is not None else float("nan") for t in temps]
    humidity_values = [
        float(h) if h is not None else float("nan")
        for h in humidities
    ]
    return pd.DataFrame({
        "ts":              pd.to_datetime(times).tz_localize("Asia/Tokyo"),
        "temp_c":          temp_values,
        "apparent_temp_c": [float(t) if t is not None else float("nan") for t in apparent_temps],
        "humidity_pct":    humidity_values,
        "discomfort_index": [
            _discomfort_index(temp, humidity)
            for temp, humidity in zip(temp_values, humidity_values)
        ],
        "weather_source": [source] * len(times),
    })


def _empty_weather_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_WEATHER_COLUMNS)


def _to_jst_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(JST)
    return ts.tz_convert(JST)


def _optional_float(value) -> float:
    if value is None or value == "":
        return float("nan")
    return float(value)


def _discomfort_index(temp_c: float, humidity_pct: float) -> float:
    if pd.isna(temp_c) or pd.isna(humidity_pct):
        return float("nan")
    return round(0.81 * temp_c + 0.01 * humidity_pct * (0.99 * temp_c - 14.3) + 46.3, 1)


def _combine_weather_source(current: object, added: str) -> str:
    if current is None or pd.isna(current) or str(current).strip() == "":
        return added
    current_text = str(current)
    parts = current_text.split("+")
    if added in parts:
        return current_text
    return f"{current_text}+{added}"


def _seasonal_humidity_pct(ts: pd.Timestamp) -> float:
    """Conservative monthly humidity fallback for emergency forecast gaps."""
    monthly = {
        1: 52.0, 2: 54.0, 3: 58.0, 4: 63.0,
        5: 68.0, 6: 75.0, 7: 78.0, 8: 76.0,
        9: 72.0, 10: 66.0, 11: 61.0, 12: 56.0,
    }
    return monthly.get(int(ts.month), 65.0)


def _refresh_humidity_derived_fields(
    weather: pd.DataFrame,
    mask: pd.Series,
    humidity_source: str,
) -> None:
    if not mask.any():
        return
    for idx in weather.loc[mask].index:
        temp_c = weather.at[idx, "temp_c"]
        humidity_pct = weather.at[idx, "humidity_pct"]
        weather.at[idx, "apparent_temp_c"] = _apparent_temp_from_observation(
            temp_c,
            humidity_pct,
            float("nan"),
        )
        weather.at[idx, "discomfort_index"] = _discomfort_index(temp_c, humidity_pct)
        weather.at[idx, "weather_source"] = _combine_weather_source(
            weather.at[idx, "weather_source"],
            humidity_source,
        )


def _apparent_temp_from_observation(
    temp_c: float,
    humidity_pct: float,
    wind_mps: float,
) -> float:
    """Estimate humid apparent temperature from official JMA observations."""
    if pd.isna(temp_c) or pd.isna(humidity_pct):
        return temp_c
    wind = 1.0 if pd.isna(wind_mps) else max(0.0, float(wind_mps))
    vapor_pressure_hpa = (
        humidity_pct
        / 100.0
        * 6.105
        * math.exp((17.27 * temp_c) / (237.7 + temp_c))
    )
    return round(temp_c + 0.33 * vapor_pressure_hpa - 0.70 * wind - 4.0, 1)


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
        return _empty_weather_frame()

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
        return _empty_weather_frame()

    hourly["temp_c"] = hourly["temp_c"].round(1)
    hourly["apparent_temp_c"] = hourly["temp_c"]
    hourly["humidity_pct"] = float("nan")
    hourly["discomfort_index"] = float("nan")
    hourly["weather_source"] = _SOURCE_JMA_FORECAST
    return hourly.reset_index()[_WEATHER_COLUMNS]


def _parse_jma_amedas_point(data: dict) -> pd.DataFrame:
    """Parse one JMA AMeDAS point block, keeping exact hourly observations."""
    rows = []
    for timestamp_key, point in data.items():
        temp = point.get("temp")
        if not isinstance(temp, list) or not temp:
            continue
        parsed_temp = _optional_float(temp[0])
        if pd.isna(parsed_temp):
            continue
        humidity = point.get("humidity")
        wind = point.get("wind")
        parsed_humidity = (
            _optional_float(humidity[0])
            if isinstance(humidity, list) and humidity
            else float("nan")
        )
        parsed_wind = (
            _optional_float(wind[0])
            if isinstance(wind, list) and wind
            else float("nan")
        )
        ts = pd.to_datetime(timestamp_key, format="%Y%m%d%H%M%S").tz_localize(JST)
        if ts.minute != 0:
            continue
        apparent_temp = _apparent_temp_from_observation(
            parsed_temp,
            parsed_humidity,
            parsed_wind,
        )
        rows.append({
            "ts": ts,
            "temp_c": parsed_temp,
            "apparent_temp_c": apparent_temp,
            "humidity_pct": parsed_humidity,
            "discomfort_index": _discomfort_index(parsed_temp, parsed_humidity),
            "weather_source": _SOURCE_AMEDAS_ACTUAL,
        })

    if not rows:
        return _empty_weather_frame()
    return (
        pd.DataFrame(rows)
          .drop_duplicates(subset=["ts"], keep="last")
          .sort_values("ts")
          .reset_index(drop=True)
    )


def _fetch_open_meteo_jma_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Open-Meteo JMA humidity fallback; operational temperature stays official JMA."""
    return _parse_response(_fetch_json(_OPEN_METEO_JMA_FORECAST_URL, {
        "latitude":      TOKYO_LAT,
        "longitude":     TOKYO_LON,
        "hourly":        _HOURLY_WEATHER_VARS,
        "timezone":      "Asia/Tokyo",
        "forecast_days": days,
    }), source=_SOURCE_OPEN_METEO_JMA)


def fetch_jma_official_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Hourly Tokyo temperatures interpolated from JMA official 3-hour forecast."""
    return _parse_jma_official_timeseries(_fetch_json(_JMA_OFFICIAL_TIMESERIES_URL, {}), days=days)


def fetch_jma_observed_temps(
    start: date,
    end: date,
    station: str = _JMA_TOKYO_AMEDAS_STATION,
) -> pd.DataFrame:
    """Hourly observed temperature from JMA AMeDAS Tokyo station.

    JMA publishes point observations in 3-hour blocks. Missing future blocks are
    ignored so same-day intraday updates can use the observations that already
    exist.
    """
    frames = []
    for day_offset in range((end - start).days + 1):
        target_date = start + timedelta(days=day_offset)
        for hour in range(0, 24, 3):
            block = f"{target_date:%Y%m%d}_{hour:02d}"
            try:
                payload = _fetch_json(
                    _JMA_AMEDAS_POINT_URL.format(station=station, block=block),
                    {},
                )
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                raise
            frames.append(_parse_jma_amedas_point(payload))

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty_weather_frame()

    result = (
        pd.concat(frames, ignore_index=True)
          .drop_duplicates(subset=["ts"], keep="last")
          .sort_values("ts")
          .reset_index(drop=True)
    )
    return result[
        (result["ts"].dt.date >= start)
        & (result["ts"].dt.date <= end)
    ].reset_index(drop=True)


def _combine_official_and_fallback_weather(
    official: pd.DataFrame,
    fallback: pd.DataFrame,
) -> pd.DataFrame:
    if official.empty:
        return fallback
    if fallback.empty:
        return official

    combined = fallback.copy()
    for col in _WEATHER_COLUMNS:
        if col not in combined.columns:
            combined[col] = float("nan") if col != "ts" else pd.NaT

    official_cols = [col for col in _WEATHER_COLUMNS if col in official.columns]
    rename_map = {
        col: f"_official_{col}"
        for col in official_cols
        if col != "ts"
    }
    combined = combined.merge(
        official[official_cols].rename(columns=rename_map),
        on="ts",
        how="left",
    )
    for col, official_col in rename_map.items():
        has_official = combined[official_col].notna()
        combined.loc[has_official, col] = combined.loc[has_official, official_col]
    combined = combined.drop(columns=list(rename_map.values()))

    missing_official = official[~official["ts"].isin(set(combined["ts"]))].copy()
    if not missing_official.empty:
        combined = pd.concat([combined, missing_official], ignore_index=True)

    combined["temp_c"] = combined["temp_c"].round(1)
    combined["apparent_temp_c"] = combined["apparent_temp_c"].round(1)
    combined["humidity_pct"] = combined["humidity_pct"].round(1)
    combined["discomfort_index"] = combined["discomfort_index"].round(1)
    return combined.sort_values("ts").reset_index(drop=True)


def _fetch_open_meteo_archive_temps(start: date, end: date) -> pd.DataFrame:
    return _parse_response(_fetch_json(_ARCHIVE_URL, {
        "latitude":   TOKYO_LAT,
        "longitude":  TOKYO_LON,
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     _HOURLY_WEATHER_VARS,
        "timezone":   "Asia/Tokyo",
    }), source=_SOURCE_OPEN_METEO_ARCHIVE)


def _overlay_observed_weather(
    forecast: pd.DataFrame,
    observed: pd.DataFrame,
) -> pd.DataFrame:
    if forecast.empty or observed.empty:
        return forecast

    result = forecast.copy()
    observed_cols = [col for col in _WEATHER_COLUMNS if col in observed.columns]
    rename_map = {
        col: f"_observed_{col}"
        for col in observed_cols
        if col != "ts"
    }
    result = result.merge(
        observed[observed_cols].rename(columns=rename_map),
        on="ts",
        how="left",
    )

    observed_mask = pd.Series(False, index=result.index)
    for col in ["temp_c", "apparent_temp_c", "humidity_pct", "discomfort_index"]:
        observed_col = f"_observed_{col}"
        if observed_col not in result.columns:
            continue
        has_observed = result[observed_col].notna()
        result.loc[has_observed, col] = result.loc[has_observed, observed_col]
        observed_mask = observed_mask | has_observed
    result.loc[observed_mask, "weather_source"] = _SOURCE_AMEDAS_ACTUAL

    return result.drop(columns=list(rename_map.values()))


def _apply_forecast_humidity_fallbacks(
    forecast: pd.DataFrame,
    observed: pd.DataFrame,
    fallback: pd.DataFrame,
    forward_fill_hours: int = 3,
) -> pd.DataFrame:
    """Fill forecast humidity without replacing official JMA temperatures."""
    result = forecast.copy()
    for col in _WEATHER_COLUMNS:
        if col not in result.columns:
            result[col] = float("nan") if col != "weather_source" else None

    if not observed.empty and "humidity_pct" in observed.columns:
        observed_humidity = (
            observed.dropna(subset=["humidity_pct"])
                    .sort_values("ts")
                    .reset_index(drop=True)
        )
        if not observed_humidity.empty:
            latest = observed_humidity.iloc[-1]
            latest_ts = latest["ts"]
            latest_humidity = float(latest["humidity_pct"])
            if pd.notna(latest_humidity):
                ff_end = latest_ts + pd.Timedelta(hours=max(0, int(forward_fill_hours)))
                ff_mask = (
                    result["humidity_pct"].isna()
                    & (result["ts"] > latest_ts)
                    & (result["ts"] <= ff_end)
                )
                result.loc[ff_mask, "humidity_pct"] = latest_humidity
                _refresh_humidity_derived_fields(result, ff_mask, _SOURCE_FORWARD_FILL)

    if not fallback.empty and "humidity_pct" in fallback.columns:
        fallback = fallback.dropna(subset=["humidity_pct"]).copy()
        humidity_by_ts = dict(zip(fallback["ts"], fallback["humidity_pct"]))
        om_mask = result["humidity_pct"].isna() & result["ts"].isin(humidity_by_ts.keys())
        result.loc[om_mask, "humidity_pct"] = result.loc[om_mask, "ts"].map(humidity_by_ts)
        _refresh_humidity_derived_fields(result, om_mask, _SOURCE_OPEN_METEO_JMA)

    seasonal_mask = result["humidity_pct"].isna()
    if seasonal_mask.any():
        result.loc[seasonal_mask, "humidity_pct"] = (
            result.loc[seasonal_mask, "ts"].map(_seasonal_humidity_pct)
        )
        _refresh_humidity_derived_fields(result, seasonal_mask, _SOURCE_SEASONAL_MEAN)

    result["temp_c"] = result["temp_c"].round(1)
    result["apparent_temp_c"] = result["apparent_temp_c"].round(1)
    result["humidity_pct"] = result["humidity_pct"].round(1)
    result["discomfort_index"] = result["discomfort_index"].round(1)
    return result[_WEATHER_COLUMNS].sort_values("ts").reset_index(drop=True)


def _should_prefer_jma_observed(start: date, end: date) -> bool:
    today = pd.Timestamp.now(tz=JST).date()
    return (end - start).days <= 3 and end >= today - timedelta(days=2)


def fetch_past_temps(start: date, end: date) -> pd.DataFrame:
    """Hourly temperature for Tokyo, preferring JMA AMeDAS for recent observations."""
    if _should_prefer_jma_observed(start, end):
        observed = _empty_weather_frame()
        try:
            observed = fetch_jma_observed_temps(start, end)
        except Exception as e:
            print(f"[WARN] JMA observed weather fetch failed: {e}", file=sys.stderr)

        if not observed.empty:
            try:
                fallback = _fetch_open_meteo_archive_temps(start, end)
            except Exception as e:
                print(f"[WARN] Open-Meteo archive fallback fetch failed: {e}", file=sys.stderr)
                return observed
            return _combine_official_and_fallback_weather(observed, fallback)

    return _fetch_open_meteo_archive_temps(start, end)


def fetch_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Hourly forecast weather with official JMA temperatures and guarded humidity.

    Temperature remains anchored to the official JMA time-series forecast. Since
    that feed does not publish hourly humidity, humidity is filled from short
    AMeDAS persistence first, then Open-Meteo JMA humidity, then a conservative
    seasonal mean as the final fallback.
    """
    try:
        official = fetch_jma_official_forecast_temps(days=days)
    except Exception as e:
        print(f"[WARN] JMA official forecast fetch failed: {e}", file=sys.stderr)
        raise

    if official.empty:
        raise RuntimeError("No official JMA forecast weather data available")

    observed = _empty_weather_frame()
    today = pd.Timestamp.now(tz=JST).date()
    try:
        observed = fetch_jma_observed_temps(today, today)
    except Exception as e:
        print(f"[WARN] JMA observed humidity fetch failed: {e}", file=sys.stderr)

    result = _overlay_observed_weather(official, observed)

    fallback = _empty_weather_frame()
    try:
        fallback = _fetch_open_meteo_jma_forecast_temps(days=days)
    except Exception as e:
        print(f"[WARN] Open-Meteo JMA humidity fallback fetch failed: {e}", file=sys.stderr)

    return _apply_forecast_humidity_fallbacks(result, observed, fallback)


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
    if "humidity_pct" not in cache.columns:
        cache["humidity_pct"] = float("nan")
    if "discomfort_index" not in cache.columns:
        cache["discomfort_index"] = float("nan")
    if "weather_source" not in cache.columns:
        cache["weather_source"] = None

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
        ts_to_humidity = (
            dict(zip(weather["ts"], weather["humidity_pct"]))
            if "humidity_pct" in weather.columns
            else {}
        )
        ts_to_discomfort = (
            dict(zip(weather["ts"], weather["discomfort_index"]))
            if "discomfort_index" in weather.columns
            else {}
        )
        ts_to_source = (
            dict(zip(weather["ts"], weather["weather_source"]))
            if "weather_source" in weather.columns
            else {}
        )
        fill_mask = cache["actual_mw"].notna()
        temp_fill_mask = cache["temp_c"].isna() & fill_mask
        apparent_fill_mask = cache["apparent_temp_c"].isna() & fill_mask
        humidity_fill_mask = cache["humidity_pct"].isna() & fill_mask
        discomfort_fill_mask = cache["discomfort_index"].isna() & fill_mask
        source_fill_mask = cache["weather_source"].isna() & fill_mask
        cache.loc[temp_fill_mask, "temp_c"] = cache.loc[temp_fill_mask, "ts"].map(ts_to_temp)
        cache.loc[apparent_fill_mask, "apparent_temp_c"] = (
            cache.loc[apparent_fill_mask, "ts"].map(ts_to_apparent_temp)
        )
        if ts_to_humidity:
            cache.loc[humidity_fill_mask, "humidity_pct"] = (
                cache.loc[humidity_fill_mask, "ts"].map(ts_to_humidity)
            )
        if ts_to_discomfort:
            cache.loc[discomfort_fill_mask, "discomfort_index"] = (
                cache.loc[discomfort_fill_mask, "ts"].map(ts_to_discomfort)
            )
        if ts_to_source:
            cache.loc[source_fill_mask, "weather_source"] = (
                cache.loc[source_fill_mask, "ts"].map(ts_to_source)
            )
        print(
            "[WEATHER] Filled "
            f"{int(temp_fill_mask.sum())} temp_c values, "
            f"{int(apparent_fill_mask.sum())} apparent_temp_c values, "
            f"{int(humidity_fill_mask.sum())} humidity_pct values, "
            f"{int(discomfort_fill_mask.sum())} discomfort_index values, "
            f"{int(source_fill_mask.sum())} weather_source values"
        )
    except Exception as e:
        print(f"[WARN] Weather archive fetch failed: {e}", file=sys.stderr)

    return cache
