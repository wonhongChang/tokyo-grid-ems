"""Feature engineering for LightGBM demand forecasting."""
from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import jpholiday
    _HAS_JPHOLIDAY = True
except ImportError:
    _HAS_JPHOLIDAY = False

JST = ZoneInfo("Asia/Tokyo")

FEATURE_COLS: list[str] = [
    # Calendar
    "hour", "dayofweek", "month", "is_holiday", "is_weekend", "is_non_business_day",
    # Standard lags
    "lag_24h", "lag_48h", "lag_168h", "lag_336h",
    # Rolling stats
    "roll_4w_mean", "roll_4w_std",
    # Holiday lag correction
    "lag_last_biz_hour",
    "lag_last_nonhol_hour",
    "consec_holiday_len",
    "days_since_holiday_end",
    "major_holiday_season",
    # Temperature
    "temp_c", "cooling_degree", "heating_degree",
    "temp_anomaly_7d",   # temp_c minus trailing 7-day mean (how abnormal vs recent week)
    "temp_anomaly_doy",  # temp_c minus historical (month, hour) mean; kept for model compatibility
    # Interaction: holiday × heat surplus (captures post-holiday demand spike on hot days)
    "holiday_x_heat",                    # consec_holiday_len × max(0, temp_anomaly_7d)
    "post_holiday_x_heat",               # int(1 ≤ days_since_holiday_end ≤ 2) × max(0, temp_anomaly_7d)
    "business_hour_x_post_holiday_heat", # int(9≤h≤18) × int(1≤dsh≤2) × max(0, temp_anomaly_7d)
    # Lag contamination context (why is the lag low/high?)
    "lag_24h_dsh",    # days_since_holiday_end(yesterday) — was yesterday post-holiday?
    "lag_24h_consec", # consec_holiday_len(yesterday) — how many holidays preceded yesterday?
    "lag_168h_dsh",   # days_since_holiday_end(7 days ago)
]

# Golden Week / Obon / New Year day-of-year zones (wider than the holiday itself
# to cover the return-to-work spike period)
_SEASON_RANGES = [
    (115, 132, 1),  # Golden Week zone  : ~Apr 25 – May 12
    (220, 235, 2),  # Obon zone         : ~Aug  8 – Aug 23
    (358, 366, 3),  # New Year zone (1) : Dec 24 – Dec 31
    (1,    10, 3),  # New Year zone (2) : Jan  1 – Jan 10
]


# ---------------------------------------------------------------------------
# Date-level helper functions
# ---------------------------------------------------------------------------

def _is_holiday(d: date) -> bool:
    return bool(jpholiday.is_holiday(d)) if _HAS_JPHOLIDAY else False


def _is_nonworking(d: date) -> bool:
    return d.weekday() >= 5 or _is_holiday(d)


def _last_biz_day(d: date) -> date | None:
    """Most recent non-holiday weekday strictly before d."""
    candidate = d - timedelta(days=1)
    for _ in range(30):
        if not _is_nonworking(candidate):
            return candidate
        candidate -= timedelta(days=1)
    return None


def _last_nonhol_day(d: date) -> date | None:
    """Most recent non-public-holiday day strictly before d (weekends allowed)."""
    candidate = d - timedelta(days=1)
    for _ in range(30):
        if not _is_holiday(candidate):
            return candidate
        candidate -= timedelta(days=1)
    return None


def _consec_holiday_len(d: date) -> int:
    """Count of consecutive holiday/weekend days immediately before d."""
    count = 0
    candidate = d - timedelta(days=1)
    for _ in range(60):
        if _is_nonworking(candidate):
            count += 1
            candidate -= timedelta(days=1)
        else:
            break
    return count


def _days_since_holiday_end(d: date, max_days: int = 7) -> int:
    """Calendar days since the most recent holiday/weekend, capped at max_days.
    Returns 0 when d itself is a holiday/weekend or the last holiday was >max_days ago.
    """
    if _is_nonworking(d):
        return 0
    candidate = d - timedelta(days=1)
    for days_back in range(1, max_days + 2):
        if _is_nonworking(candidate):
            return min(days_back, max_days)
        candidate -= timedelta(days=1)
    return 0


def _major_holiday_season(d: date) -> int:
    """0=normal 1=golden_week_zone 2=obon_zone 3=newyear_zone."""
    doy = d.timetuple().tm_yday
    for start, end, code in _SEASON_RANGES:
        if start <= doy <= end:
            return code
    return 0


# ---------------------------------------------------------------------------
# Internal: pre-compute date-level features for a set of dates
# ---------------------------------------------------------------------------

def _date_features(dates: list[date]) -> dict[date, dict]:
    """Return a dict mapping each date to its holiday-lag correction values."""
    result: dict[date, dict] = {}
    for d in dates:
        lag_1d = d - timedelta(days=1)
        lag_7d = d - timedelta(days=7)
        result[d] = {
            "last_biz_day":           _last_biz_day(d),
            "last_nonhol_day":        _last_nonhol_day(d),
            "consec_holiday_len":     _consec_holiday_len(d),
            "days_since_holiday_end": _days_since_holiday_end(d),
            "major_holiday_season":   _major_holiday_season(d),
            "lag_24h_dsh":            _days_since_holiday_end(lag_1d),
            "lag_24h_consec":         _consec_holiday_len(lag_1d),
            "lag_168h_dsh":           _days_since_holiday_end(lag_7d),
        }
    return result


# ---------------------------------------------------------------------------
# Timezone helper
# ---------------------------------------------------------------------------

def _ensure_tz(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "ts" in df.columns and not isinstance(df["ts"].dtype, pd.DatetimeTZDtype):
        df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize("Asia/Tokyo")
    return df


# ---------------------------------------------------------------------------
# Holiday lag columns (shared between training and inference)
# ---------------------------------------------------------------------------

def _add_holiday_lag_cols(
    df: pd.DataFrame,
    ts_to_mw: dict,
    date_feature_map: dict[date, dict],
) -> pd.DataFrame:
    """Append lag_last_biz_hour / lag_last_nonhol_hour and date-level features."""

    def _lag(ts: pd.Timestamp, day_key: str) -> float:
        row_date = ts.date()
        target_day = date_feature_map.get(row_date, {}).get(day_key)
        if target_day is None:
            return np.nan
        key_ts = pd.Timestamp(
            year=target_day.year, month=target_day.month, day=target_day.day,
            hour=ts.hour, tz=JST,
        )
        return ts_to_mw.get(key_ts, np.nan)

    df["lag_last_biz_hour"]    = df["ts"].map(lambda ts: _lag(ts, "last_biz_day"))
    df["lag_last_nonhol_hour"] = df["ts"].map(lambda ts: _lag(ts, "last_nonhol_day"))
    df["consec_holiday_len"]   = df["ts"].dt.date.map(
        lambda row_date: date_feature_map.get(row_date, {}).get("consec_holiday_len", 0)
    )
    df["days_since_holiday_end"] = df["ts"].dt.date.map(
        lambda row_date: date_feature_map.get(row_date, {}).get("days_since_holiday_end", 0)
    )
    df["major_holiday_season"] = df["ts"].dt.date.map(
        lambda row_date: date_feature_map.get(row_date, {}).get("major_holiday_season", 0)
    )
    df["lag_24h_dsh"] = df["ts"].dt.date.map(
        lambda row_date: date_feature_map.get(row_date, {}).get("lag_24h_dsh", 0)
    )
    df["lag_24h_consec"] = df["ts"].dt.date.map(
        lambda row_date: date_feature_map.get(row_date, {}).get("lag_24h_consec", 0)
    )
    df["lag_168h_dsh"] = df["ts"].dt.date.map(
        lambda row_date: date_feature_map.get(row_date, {}).get("lag_168h_dsh", 0)
    )
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_training_features(cache: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y) from hourly cache for training.

    Rows with missing actual_mw or any non-temperature feature column are dropped.
    Temperature features (temp_c, cooling_degree, heating_degree) are included when
    the cache has a temp_c column with sufficient coverage; rows missing temp_c are
    also dropped via dropna.
    """
    df = _ensure_tz(cache)
    df = df[df["actual_mw"].notna()].sort_values("ts").reset_index(drop=True)

    df["hour"]       = df["ts"].dt.hour
    df["dayofweek"]  = df["ts"].dt.dayofweek
    df["month"]      = df["ts"].dt.month
    df["is_weekend"]          = (df["dayofweek"] >= 5).astype(int)
    df["is_holiday"]          = df["ts"].dt.date.map(lambda d: int(_is_holiday(d)))
    df["is_non_business_day"] = df["ts"].dt.date.map(lambda d: int(_is_nonworking(d)))

    # Standard lag features via timestamp-shift merge
    actual_history = df[["ts", "actual_mw"]].copy()
    for hours, col in [
        (24,  "lag_24h"),
        (48,  "lag_48h"),
        (168, "lag_168h"),
        (336, "lag_336h"),
    ]:
        shifted = (
            actual_history.assign(ts=actual_history["ts"] + pd.Timedelta(hours=hours))
               .rename(columns={"actual_mw": col})
        )
        df = df.merge(shifted, on="ts", how="left")

    # Rolling stats within each (hour, dayofweek) slot
    hour_weekday_group = df.groupby(["hour", "dayofweek"])["actual_mw"]
    df["roll_4w_mean"] = hour_weekday_group.transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    )
    df["roll_4w_std"] = hour_weekday_group.transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).std().fillna(0.0)
    )

    # Holiday lag correction features
    ts_to_mw = dict(zip(df["ts"], df["actual_mw"]))
    date_feature_map = _date_features(sorted(set(df["ts"].dt.date)))
    df = _add_holiday_lag_cols(df, ts_to_mw, date_feature_map)

    # Temperature features
    if "temp_c" in df.columns:
        df["cooling_degree"]  = (df["temp_c"] - 22.0).clip(lower=0.0)
        df["heating_degree"]  = (10.0 - df["temp_c"]).clip(lower=0.0)
        # How abnormal vs recent 7 days (shift 1h to prevent self-inclusion)
        trailing_7d_temp_mean = df["temp_c"].shift(1).rolling(168, min_periods=24).mean()
        df["temp_anomaly_7d"] = df["temp_c"] - trailing_7d_temp_mean
        # How abnormal vs historical same (month, hour) average
        month_hour_temp_mean = df.groupby(["month", "hour"])["temp_c"].transform("mean")
        df["temp_anomaly_doy"] = df["temp_c"] - month_hour_temp_mean
    else:
        df["temp_c"]           = np.nan
        df["cooling_degree"]   = np.nan
        df["heating_degree"]   = np.nan
        df["temp_anomaly_7d"]  = np.nan
        df["temp_anomaly_doy"] = np.nan

    # Interaction features: holiday × heat surplus
    positive_temp_anomaly_7d = df["temp_anomaly_7d"].clip(lower=0.0)
    is_recent_post_holiday = df["days_since_holiday_end"].between(1, 2).astype(float)
    df["holiday_x_heat"] = df["consec_holiday_len"] * positive_temp_anomaly_7d
    df["post_holiday_x_heat"] = is_recent_post_holiday * positive_temp_anomaly_7d
    df["business_hour_x_post_holiday_heat"] = (
        df["hour"].between(9, 18).astype(float)
        * is_recent_post_holiday
        * positive_temp_anomaly_7d
    )

    df = df.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    return df[FEATURE_COLS].copy(), df["actual_mw"].copy()


def build_inference_features(cache: pd.DataFrame, target_date: date) -> pd.DataFrame:
    """Return a 24-row DataFrame (one row per hour) for predicting target_date.

    cache may contain virtual rows (NaN actual_mw, non-NaN temp_c) for target_date
    added by run_batch._extend_cache_with_forecast_weather.
    """
    cache = _ensure_tz(cache)
    actual_rows = cache[cache["actual_mw"].notna()].copy()

    actual_mw_by_ts: dict = dict(zip(actual_rows["ts"], actual_rows["actual_mw"]))
    actual_rows["_hour"] = actual_rows["ts"].dt.hour
    actual_rows["_dow"]  = actual_rows["ts"].dt.dayofweek

    is_public_holiday = int(_is_holiday(target_date))
    date_feature_map = _date_features([target_date])

    # Temperature lookup for target_date (includes virtual forecast rows)
    if "temp_c" in cache.columns:
        target_day_temps = cache[
            cache["ts"].dt.date == target_date
        ][["ts", "temp_c"]].dropna(subset=["temp_c"])
        hour_to_temp: dict[int, float] = {
            int(row["ts"].hour): float(row["temp_c"]) for _, row in target_day_temps.iterrows()
        }
    else:
        hour_to_temp = {}

    # Trailing 7-day mean temperature (same for all 24 hours of target_date)
    target_start = pd.Timestamp(
        year=target_date.year, month=target_date.month, day=target_date.day, tz=JST
    )
    recent_temp_window = cache[
        (cache["ts"] < target_start) &
        (cache["ts"] >= target_start - pd.Timedelta(hours=168))
    ]["temp_c"].dropna() if "temp_c" in cache.columns else pd.Series(dtype=float)
    recent_7d_temp_mean = (
        float(recent_temp_window.mean()) if len(recent_temp_window) >= 24 else float("nan")
    )

    # Historical (month, hour) mean temperature from past data
    if "temp_c" in cache.columns:
        historical_temp_rows = cache[cache["ts"].dt.date < target_date].copy()
        month_hour_temp_mean: dict = (
            historical_temp_rows.assign(
                _m=historical_temp_rows["ts"].dt.month,
                _h=historical_temp_rows["ts"].dt.hour,
            )
                 .groupby(["_m", "_h"])["temp_c"]
                 .mean()
                 .to_dict()
        )
    else:
        month_hour_temp_mean = {}
    target_month = target_date.month

    rows = []
    for hour in range(24):
        ts = pd.Timestamp(
            year=target_date.year, month=target_date.month, day=target_date.day,
            hour=hour, tz=JST,
        )
        day_of_week = ts.dayofweek

        lag_24h  = actual_mw_by_ts.get(ts - pd.Timedelta(hours=24),  np.nan)
        lag_48h  = actual_mw_by_ts.get(ts - pd.Timedelta(hours=48),  np.nan)
        lag_168h = actual_mw_by_ts.get(ts - pd.Timedelta(hours=168), np.nan)
        lag_336h = actual_mw_by_ts.get(ts - pd.Timedelta(hours=336), np.nan)

        recent_same_hour_weekday = actual_rows[
            (actual_rows["_hour"] == hour) &
            (actual_rows["_dow"]  == day_of_week)  &
            (actual_rows["ts"]    <  ts)
        ].tail(4)

        target_date_features = date_feature_map[target_date]

        def _lag_day(day_key: str) -> float:
            lag_date = target_date_features.get(day_key)
            if lag_date is None:
                return np.nan
            key_ts = pd.Timestamp(year=lag_date.year, month=lag_date.month, day=lag_date.day,
                                  hour=hour, tz=JST)
            return actual_mw_by_ts.get(key_ts, np.nan)

        hour_temp_c = hour_to_temp.get(hour, float("nan"))
        has_hour_temp = not np.isnan(hour_temp_c)
        cooling = max(0.0, hour_temp_c - 22.0) if has_hour_temp else np.nan
        heating = max(0.0, 10.0 - hour_temp_c) if has_hour_temp else np.nan
        temp_anomaly_vs_7d_mean = (
            hour_temp_c - recent_7d_temp_mean
            if has_hour_temp and not np.isnan(recent_7d_temp_mean)
            else np.nan
        )
        month_hour_temp_reference = month_hour_temp_mean.get((target_month, hour), float("nan"))
        temp_anomaly_vs_month_hour_mean = (
            hour_temp_c - month_hour_temp_reference
            if has_hour_temp and not np.isnan(month_hour_temp_reference)
            else np.nan
        )

        # Interaction features
        days_since_holiday_end = target_date_features["days_since_holiday_end"]
        positive_temp_anomaly_7d = (
            max(0.0, temp_anomaly_vs_7d_mean)
            if not np.isnan(temp_anomaly_vs_7d_mean)
            else np.nan
        )
        is_recent_post_holiday = int(1 <= days_since_holiday_end <= 2)
        holiday_heat_interaction = (
            target_date_features["consec_holiday_len"] * positive_temp_anomaly_7d
        )
        post_holiday_heat_interaction = is_recent_post_holiday * positive_temp_anomaly_7d
        business_hour_post_holiday_heat_interaction = (
            int(9 <= hour <= 18) * is_recent_post_holiday * positive_temp_anomaly_7d
        )

        rows.append({
            "hour":                   hour,
            "dayofweek":              day_of_week,
            "month":                  ts.month,
            "is_holiday":             is_public_holiday,
            "is_weekend":             int(day_of_week >= 5),
            "is_non_business_day":    int(_is_nonworking(target_date)),
            "lag_24h":                lag_24h,
            "lag_48h":                lag_48h,
            "lag_168h":               lag_168h,
            "lag_336h":               lag_336h,
            "roll_4w_mean": (
                float(recent_same_hour_weekday["actual_mw"].mean())
                if len(recent_same_hour_weekday) > 0
                else np.nan
            ),
            "roll_4w_std": (
                float(recent_same_hour_weekday["actual_mw"].std())
                if len(recent_same_hour_weekday) > 1
                else 0.0
            ),
            "lag_last_biz_hour":      _lag_day("last_biz_day"),
            "lag_last_nonhol_hour":   _lag_day("last_nonhol_day"),
            "consec_holiday_len":     target_date_features["consec_holiday_len"],
            "days_since_holiday_end": target_date_features["days_since_holiday_end"],
            "major_holiday_season":   target_date_features["major_holiday_season"],
            "temp_c":           hour_temp_c,
            "cooling_degree":   cooling,
            "heating_degree":   heating,
            "temp_anomaly_7d":  temp_anomaly_vs_7d_mean,
            "temp_anomaly_doy": temp_anomaly_vs_month_hour_mean,
            "holiday_x_heat":                    holiday_heat_interaction,
            "post_holiday_x_heat":               post_holiday_heat_interaction,
            "business_hour_x_post_holiday_heat": business_hour_post_holiday_heat_interaction,
            "lag_24h_dsh":    target_date_features["lag_24h_dsh"],
            "lag_24h_consec": target_date_features["lag_24h_consec"],
            "lag_168h_dsh":   target_date_features["lag_168h_dsh"],
        })

    return pd.DataFrame(rows)[FEATURE_COLS]
