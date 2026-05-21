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
    "apparent_temp_c", "apparent_cooling_degree",
    "temp_anomaly_7d",   # temp_c minus trailing 7-day mean (how abnormal vs recent week)
    "temp_anomaly_doy",  # temp_c minus historical (month, hour) mean; kept for model compatibility
    "temp_delta_24h",       # current temp_c minus previous-day same-hour temp_c
    "cooling_delta_24h",    # current cooling_degree minus previous-day same-hour cooling_degree
    "temp_delta_168h",      # current temp_c minus 7-day-ago same-hour temp_c
    "cooling_delta_168h",   # current cooling_degree minus 7-day-ago same-hour cooling_degree
    "temp_delta_1h",        # current temp_c minus previous-hour temp_c
    "temp_delta_2h",        # current temp_c minus two-hours-ago temp_c
    "apparent_temp_delta_1h",
    "cooling_delta_1h",
    "cooling_degree_3h_mean",  # recent cooling load inertia, including current hour
    "cooling_degree_6h_mean",
    "heating_degree_3h_mean",  # recent heating load inertia, including current hour
    "heating_degree_6h_mean",
    "temp_72h_mean",           # 3-day thermal memory
    "cooling_degree_72h_mean", # 3-day cooling load persistence
    "heating_degree_72h_mean", # 3-day heating load persistence
    "business_morning_x_temp_delta_24h",   # weekday morning ramp x same-hour temp change vs yesterday
    "business_morning_x_temp_anomaly_7d",  # weekday morning ramp x temp anomaly vs recent week
    "business_morning_x_temp_anomaly_doy", # weekday morning ramp x seasonal same-hour temp anomaly
    "business_late_afternoon_x_temp_delta_1h",    # weekday 15-18 demand hysteresis x temp direction
    "business_late_afternoon_x_cooling_delta_1h", # weekday 15-18 cooling-load direction
    # Interaction: holiday × heat surplus (captures post-holiday demand spike on hot days)
    "holiday_x_heat",                    # consec_holiday_len × max(0, temp_anomaly_7d)
    "post_holiday_x_heat",               # int(1 ≤ days_since_holiday_end ≤ 2) × max(0, temp_anomaly_7d)
    "business_hour_x_post_holiday_heat", # int(9≤h≤18) × int(1≤dsh≤2) × max(0, temp_anomaly_7d)
    # Lag contamination context (why is the lag low/high?)
    "lag_24h_dsh",    # days_since_holiday_end(yesterday) — was yesterday post-holiday?
    "lag_24h_consec", # consec_holiday_len(yesterday) — how many holidays preceded yesterday?
    "lag_168h_dsh",   # days_since_holiday_end(7 days ago)
    "lag_24h_business_type_mismatch",        # target and previous day differ in business/non-business type
    "lag_24h_mismatch_x_business_hour",      # mismatch focused on daytime demand hours
    "recent_same_business_type_mean",        # recent same-hour mean for business vs non-business days
    "lag_24h_to_last_biz_gap",               # last business-day same-hour demand minus lag_24h
    "lag_24h_to_same_business_type_gap",     # recent same business-type mean minus lag_24h
    "lag_24h_gap_x_business_hour",           # mismatch gap focused on morning/daytime demand hours
]

INFERENCE_CONTEXT_COLS: list[str] = [
    "lag_24h_hourly_delta",
    "lag_168h_hourly_delta",
    "recent_same_business_type_delta_mean",
    "recent_same_business_type_delta_q25",
    "same_day_latest_actual_hour",
    "same_day_latest_hourly_delta",
    "same_day_recent_hourly_delta_mean",
    "business_midday_x_lag_24h_delta",
    "business_midday_x_recent_delta_mean",
    "business_midday_x_recent_delta_q25",
    "business_midday_x_same_day_recent_delta_mean",
]

# Golden Week / Obon / New Year day-of-year zones (wider than the holiday itself
# to cover the return-to-work spike period)
_SEASON_RANGES = [
    (115, 132, 1),  # Golden Week zone  : ~Apr 25 – May 12
    (220, 235, 2),  # Obon zone         : ~Aug  8 – Aug 23
    (358, 366, 3),  # New Year zone (1) : Dec 24 – Dec 31
    (1,    10, 3),  # New Year zone (2) : Jan  1 – Jan 10
]

_DEFAULT_COOLING_BASE_TEMP_C = 22.0
_DEFAULT_HEATING_BASE_TEMP_C = 18.0


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


def _weather_feature_config(config: dict | None = None) -> tuple[float, float]:
    """Return configurable balance points used by degree-day style features."""
    weather_config = (config or {}).get("weather_features", {})
    cooling_base = float(
        weather_config.get("cooling_base_temp_c", _DEFAULT_COOLING_BASE_TEMP_C)
    )
    heating_base = float(
        weather_config.get("heating_base_temp_c", _DEFAULT_HEATING_BASE_TEMP_C)
    )
    return cooling_base, heating_base


def _cooling_degree(temp_c: float, cooling_base_temp_c: float) -> float:
    return max(0.0, temp_c - cooling_base_temp_c)


def _heating_degree(temp_c: float, heating_base_temp_c: float) -> float:
    return max(0.0, heating_base_temp_c - temp_c)


def _add_lag_gap_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Expose how much the 24h lag differs from business-type demand anchors."""
    df["lag_24h_to_last_biz_gap"] = df["lag_last_biz_hour"] - df["lag_24h"]
    df["lag_24h_to_same_business_type_gap"] = (
        df["recent_same_business_type_mean"] - df["lag_24h"]
    )
    df["lag_24h_gap_x_business_hour"] = (
        df["lag_24h_business_type_mismatch"]
        * df["hour"].between(6, 18).astype(float)
        * df["lag_24h_to_same_business_type_gap"]
    )
    return df


def _add_midday_transition_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Expose learned weekday midday demand shape without hard-coding a dip."""
    for column in [
        "recent_same_business_type_delta_q25",
        "same_day_recent_hourly_delta_mean",
    ]:
        if column not in df.columns:
            df[column] = np.nan
    business_midday = (df["is_non_business_day"] == 0) & df["hour"].between(11, 13)
    df["business_midday_x_lag_24h_delta"] = df["lag_24h_hourly_delta"].where(
        business_midday,
        0.0,
    )
    df["business_midday_x_recent_delta_mean"] = (
        df["recent_same_business_type_delta_mean"].where(business_midday, 0.0)
    )
    df["business_midday_x_recent_delta_q25"] = (
        df["recent_same_business_type_delta_q25"].where(business_midday, 0.0)
    )
    df["business_midday_x_same_day_recent_delta_mean"] = (
        df["same_day_recent_hourly_delta_mean"].where(business_midday, 0.0)
    )
    return df


def _add_relative_weather_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """Add relative weather interactions without fixed temperature cutoffs."""
    business_morning = (
        (df["is_non_business_day"] == 0)
        & df["hour"].between(5, 11)
    ).astype(float)
    df["business_morning_x_temp_delta_24h"] = business_morning * df["temp_delta_24h"]
    df["business_morning_x_temp_anomaly_7d"] = business_morning * df["temp_anomaly_7d"]
    df["business_morning_x_temp_anomaly_doy"] = business_morning * df["temp_anomaly_doy"]
    business_late_afternoon = (
        (df["is_non_business_day"] == 0)
        & df["hour"].between(15, 18)
    ).astype(float)
    df["business_late_afternoon_x_temp_delta_1h"] = (
        business_late_afternoon * df["temp_delta_1h"]
    )
    df["business_late_afternoon_x_cooling_delta_1h"] = (
        business_late_afternoon * df["cooling_delta_1h"]
    )
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

def build_training_features(
    cache: pd.DataFrame,
    config: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y) from hourly cache for training.

    Rows with missing actual_mw or any non-temperature feature column are dropped.
    Temperature features (temp_c, cooling_degree, heating_degree) are included when
    the cache has a temp_c column with sufficient coverage; rows missing temp_c are
    also dropped via dropna.
    """
    cooling_base_temp_c, heating_base_temp_c = _weather_feature_config(config)
    df = _ensure_tz(cache)
    df = df[df["actual_mw"].notna()].sort_values("ts").reset_index(drop=True)

    df["hour"]       = df["ts"].dt.hour
    df["dayofweek"]  = df["ts"].dt.dayofweek
    df["month"]      = df["ts"].dt.month
    df["is_weekend"]          = (df["dayofweek"] >= 5).astype(int)
    df["is_holiday"]          = df["ts"].dt.date.map(lambda d: int(_is_holiday(d)))
    df["is_non_business_day"] = df["ts"].dt.date.map(lambda d: int(_is_nonworking(d)))
    df["prev_day_is_non_business_day"] = df["ts"].dt.date.map(
        lambda d: int(_is_nonworking(d - timedelta(days=1)))
    )
    df["lag_24h_business_type_mismatch"] = (
        df["is_non_business_day"] != df["prev_day_is_non_business_day"]
    ).astype(int)
    df["lag_24h_mismatch_x_business_hour"] = (
        df["lag_24h_business_type_mismatch"] * df["hour"].between(8, 18).astype(int)
    )

    # Standard lag features via timestamp-shift merge
    actual_history = df[["ts", "actual_mw"]].copy()
    for hours, col in [
        (24,  "lag_24h"),
        (25,  "_lag_25h"),
        (48,  "lag_48h"),
        (168, "lag_168h"),
        (169, "_lag_169h"),
        (336, "lag_336h"),
    ]:
        shifted = (
            actual_history.assign(ts=actual_history["ts"] + pd.Timedelta(hours=hours))
               .rename(columns={"actual_mw": col})
        )
        df = df.merge(shifted, on="ts", how="left")
    df["lag_24h_hourly_delta"] = df["lag_24h"] - df["_lag_25h"]
    df["lag_168h_hourly_delta"] = df["lag_168h"] - df["_lag_169h"]

    previous_hour = (
        actual_history.assign(ts=actual_history["ts"] + pd.Timedelta(hours=1))
            .rename(columns={"actual_mw": "_actual_prev_hour"})
    )
    df = df.merge(previous_hour, on="ts", how="left")
    df["_actual_hourly_delta"] = df["actual_mw"] - df["_actual_prev_hour"]

    # Rolling stats within each (hour, dayofweek) slot
    hour_weekday_group = df.groupby(["hour", "dayofweek"])["actual_mw"]
    df["roll_4w_mean"] = hour_weekday_group.transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    )
    df["roll_4w_std"] = hour_weekday_group.transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).std().fillna(0.0)
    )
    # Recent same-hour mean within the same business/non-business type.
    # This gives weekend/holiday forecasts a broader non-business anchor when
    # lag_24h comes from a different type of day.
    hour_business_type_group = df.groupby(["hour", "is_non_business_day"])["actual_mw"]
    df["recent_same_business_type_mean"] = hour_business_type_group.transform(
        lambda s: s.shift(1).rolling(8, min_periods=1).mean()
    )
    hour_business_type_delta_group = df.groupby(
        ["hour", "is_non_business_day"]
    )["_actual_hourly_delta"]
    df["recent_same_business_type_delta_mean"] = hour_business_type_delta_group.transform(
        lambda s: s.shift(1).rolling(8, min_periods=1).mean()
    )

    # Holiday lag correction features
    ts_to_mw = dict(zip(df["ts"], df["actual_mw"]))
    date_feature_map = _date_features(sorted(set(df["ts"].dt.date)))
    df = _add_holiday_lag_cols(df, ts_to_mw, date_feature_map)
    df = _add_lag_gap_cols(df)
    df = _add_midday_transition_cols(df)

    # Temperature features
    if "temp_c" in df.columns:
        if "apparent_temp_c" not in df.columns:
            df["apparent_temp_c"] = df["temp_c"]
        df["apparent_temp_c"] = df["apparent_temp_c"].fillna(df["temp_c"])
        df["cooling_degree"]  = (df["temp_c"] - cooling_base_temp_c).clip(lower=0.0)
        df["heating_degree"]  = (heating_base_temp_c - df["temp_c"]).clip(lower=0.0)
        df["apparent_cooling_degree"] = (
            df["apparent_temp_c"] - cooling_base_temp_c
        ).clip(lower=0.0)
        df["cooling_degree_3h_mean"] = (
            df["cooling_degree"].rolling(3, min_periods=1).mean()
        )
        df["cooling_degree_6h_mean"] = (
            df["cooling_degree"].rolling(6, min_periods=1).mean()
        )
        df["heating_degree_3h_mean"] = (
            df["heating_degree"].rolling(3, min_periods=1).mean()
        )
        df["heating_degree_6h_mean"] = (
            df["heating_degree"].rolling(6, min_periods=1).mean()
        )
        df["temp_72h_mean"] = df["temp_c"].rolling(72, min_periods=24).mean()
        df["cooling_degree_72h_mean"] = (
            df["cooling_degree"].rolling(72, min_periods=24).mean()
        )
        df["heating_degree_72h_mean"] = (
            df["heating_degree"].rolling(72, min_periods=24).mean()
        )
        # How abnormal vs recent 7 days (shift 1h to prevent self-inclusion)
        trailing_7d_temp_mean = df["temp_c"].shift(1).rolling(168, min_periods=24).mean()
        df["temp_anomaly_7d"] = df["temp_c"] - trailing_7d_temp_mean
        # How abnormal vs historical same (month, hour) average
        month_hour_temp_mean = df.groupby(["month", "hour"])["temp_c"].transform("mean")
        df["temp_anomaly_doy"] = df["temp_c"] - month_hour_temp_mean
        temp_history = df[[
            "ts", "temp_c", "apparent_temp_c", "cooling_degree",
        ]].copy()
        shifted_temp_1h = (
            temp_history.assign(ts=temp_history["ts"] + pd.Timedelta(hours=1))
                .rename(columns={
                    "temp_c": "temp_c_1h",
                    "apparent_temp_c": "apparent_temp_c_1h",
                    "cooling_degree": "cooling_degree_1h",
                })
        )
        shifted_temp_2h = (
            temp_history[["ts", "temp_c"]]
                .assign(ts=temp_history["ts"] + pd.Timedelta(hours=2))
                .rename(columns={"temp_c": "temp_c_2h"})
        )
        shifted_temp_24h = (
            temp_history[["ts", "temp_c", "cooling_degree"]]
                .assign(ts=temp_history["ts"] + pd.Timedelta(hours=24))
                .rename(columns={
                    "temp_c": "temp_c_24h",
                    "cooling_degree": "cooling_degree_24h",
                })
        )
        shifted_temp_168h = (
            temp_history[["ts", "temp_c", "cooling_degree"]]
                .assign(ts=temp_history["ts"] + pd.Timedelta(hours=168))
                .rename(columns={
                    "temp_c": "temp_c_168h",
                    "cooling_degree": "cooling_degree_168h",
                })
        )
        df = df.merge(shifted_temp_1h, on="ts", how="left")
        df = df.merge(shifted_temp_2h, on="ts", how="left")
        df = df.merge(shifted_temp_24h, on="ts", how="left")
        df = df.merge(shifted_temp_168h, on="ts", how="left")
        df["temp_delta_24h"] = df["temp_c"] - df["temp_c_24h"]
        df["cooling_delta_24h"] = df["cooling_degree"] - df["cooling_degree_24h"]
        df["temp_delta_168h"] = df["temp_c"] - df["temp_c_168h"]
        df["cooling_delta_168h"] = df["cooling_degree"] - df["cooling_degree_168h"]
        df["temp_delta_1h"] = df["temp_c"] - df["temp_c_1h"]
        df["temp_delta_2h"] = df["temp_c"] - df["temp_c_2h"]
        df["apparent_temp_delta_1h"] = (
            df["apparent_temp_c"] - df["apparent_temp_c_1h"]
        )
        df["cooling_delta_1h"] = df["cooling_degree"] - df["cooling_degree_1h"]
    else:
        df["temp_c"]           = np.nan
        df["cooling_degree"]   = np.nan
        df["heating_degree"]   = np.nan
        df["apparent_temp_c"] = np.nan
        df["apparent_cooling_degree"] = np.nan
        df["temp_anomaly_7d"]  = np.nan
        df["temp_anomaly_doy"] = np.nan
        df["temp_delta_24h"] = np.nan
        df["cooling_delta_24h"] = np.nan
        df["temp_delta_168h"] = np.nan
        df["cooling_delta_168h"] = np.nan
        df["temp_delta_1h"] = np.nan
        df["temp_delta_2h"] = np.nan
        df["apparent_temp_delta_1h"] = np.nan
        df["cooling_delta_1h"] = np.nan
        df["cooling_degree_3h_mean"] = np.nan
        df["cooling_degree_6h_mean"] = np.nan
        df["heating_degree_3h_mean"] = np.nan
        df["heating_degree_6h_mean"] = np.nan
        df["temp_72h_mean"] = np.nan
        df["cooling_degree_72h_mean"] = np.nan
        df["heating_degree_72h_mean"] = np.nan

    df = _add_relative_weather_interactions(df)

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


def build_inference_features(
    cache: pd.DataFrame,
    target_date: date,
    config: dict | None = None,
    include_context: bool = False,
) -> pd.DataFrame:
    """Return a 24-row DataFrame (one row per hour) for predicting target_date.

    cache may contain virtual rows (NaN actual_mw, non-NaN temp_c) for target_date
    added by run_batch._extend_cache_with_forecast_weather.
    """
    cooling_base_temp_c, heating_base_temp_c = _weather_feature_config(config)
    cache = _ensure_tz(cache)
    actual_rows = cache[cache["actual_mw"].notna()].copy()

    actual_mw_by_ts: dict = dict(zip(actual_rows["ts"], actual_rows["actual_mw"]))
    actual_rows["_hour"] = actual_rows["ts"].dt.hour
    actual_rows["_dow"]  = actual_rows["ts"].dt.dayofweek
    actual_rows["_is_non_business_day"] = actual_rows["ts"].dt.date.map(
        lambda d: int(_is_nonworking(d))
    )
    actual_rows["_actual_prev_hour"] = actual_rows["ts"].map(
        lambda ts: actual_mw_by_ts.get(ts - pd.Timedelta(hours=1), np.nan)
    )
    actual_rows["_actual_hourly_delta"] = (
        actual_rows["actual_mw"] - actual_rows["_actual_prev_hour"]
    )

    is_public_holiday = int(_is_holiday(target_date))
    is_target_non_business_day = int(_is_nonworking(target_date))
    prev_day_is_non_business_day = int(_is_nonworking(target_date - timedelta(days=1)))
    lag_24h_business_type_mismatch = int(
        is_target_non_business_day != prev_day_is_non_business_day
    )
    date_feature_map = _date_features([target_date])

    # Temperature lookup for target_date (includes virtual forecast rows)
    if "temp_c" in cache.columns:
        cache_weather = cache[["ts", "temp_c"]].copy()
        if "apparent_temp_c" in cache.columns:
            cache_weather["apparent_temp_c"] = cache["apparent_temp_c"]
        else:
            cache_weather["apparent_temp_c"] = cache_weather["temp_c"]
        cache_weather["apparent_temp_c"] = cache_weather["apparent_temp_c"].fillna(
            cache_weather["temp_c"]
        )
        target_day_temps = cache_weather[
            cache_weather["ts"].dt.date == target_date
        ].dropna(subset=["temp_c"])
        hour_to_temp: dict[int, float] = {
            int(row["ts"].hour): float(row["temp_c"]) for _, row in target_day_temps.iterrows()
        }
        hour_to_apparent_temp: dict[int, float] = {
            int(row["ts"].hour): float(row["apparent_temp_c"])
            for _, row in target_day_temps.iterrows()
        }
        temp_by_ts: dict[pd.Timestamp, float] = {
            row["ts"]: float(row["temp_c"])
            for _, row in cache_weather.dropna(subset=["temp_c"]).iterrows()
        }
        apparent_temp_by_ts: dict[pd.Timestamp, float] = {
            row["ts"]: float(row["apparent_temp_c"])
            for _, row in cache_weather.dropna(subset=["apparent_temp_c"]).iterrows()
        }
    else:
        hour_to_temp = {}
        hour_to_apparent_temp = {}
        temp_by_ts = {}
        apparent_temp_by_ts = {}

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

    def _temp_at(lookup_ts: pd.Timestamp) -> float:
        if lookup_ts.date() == target_date:
            return hour_to_temp.get(int(lookup_ts.hour), float("nan"))
        return temp_by_ts.get(lookup_ts, float("nan"))

    def _apparent_temp_at(lookup_ts: pd.Timestamp) -> float:
        if lookup_ts.date() == target_date:
            return hour_to_apparent_temp.get(int(lookup_ts.hour), float("nan"))
        return apparent_temp_by_ts.get(lookup_ts, float("nan"))

    def _degree_window_mean(
        lookup_ts: pd.Timestamp,
        window_hours: int,
        degree_fn,
    ) -> float:
        values = []
        for offset_hour in range(window_hours):
            temp_value = _temp_at(lookup_ts - pd.Timedelta(hours=offset_hour))
            if not np.isnan(temp_value):
                values.append(float(degree_fn(temp_value)))
        return float(np.mean(values)) if values else float("nan")

    rows = []
    for hour in range(24):
        ts = pd.Timestamp(
            year=target_date.year, month=target_date.month, day=target_date.day,
            hour=hour, tz=JST,
        )
        day_of_week = ts.dayofweek

        lag_24h  = actual_mw_by_ts.get(ts - pd.Timedelta(hours=24),  np.nan)
        lag_25h  = actual_mw_by_ts.get(ts - pd.Timedelta(hours=25),  np.nan)
        lag_48h  = actual_mw_by_ts.get(ts - pd.Timedelta(hours=48),  np.nan)
        lag_168h = actual_mw_by_ts.get(ts - pd.Timedelta(hours=168), np.nan)
        lag_169h = actual_mw_by_ts.get(ts - pd.Timedelta(hours=169), np.nan)
        lag_336h = actual_mw_by_ts.get(ts - pd.Timedelta(hours=336), np.nan)
        lag_24h_hourly_delta = lag_24h - lag_25h
        lag_168h_hourly_delta = lag_168h - lag_169h

        recent_same_hour_weekday = actual_rows[
            (actual_rows["_hour"] == hour) &
            (actual_rows["_dow"]  == day_of_week)  &
            (actual_rows["ts"]    <  ts)
        ].tail(4)
        recent_same_business_type = actual_rows[
            (actual_rows["_hour"] == hour) &
            (actual_rows["_is_non_business_day"] == is_target_non_business_day) &
            (actual_rows["ts"] < ts)
        ].tail(8)
        recent_same_business_type_delta = actual_rows[
            (actual_rows["_hour"] == hour) &
            (actual_rows["_is_non_business_day"] == is_target_non_business_day) &
            (actual_rows["ts"] < ts)
        ].dropna(subset=["_actual_hourly_delta"]).tail(8)
        same_day_actuals_before_ts = actual_rows[
            (actual_rows["ts"].dt.date == target_date) &
            (actual_rows["ts"] < ts)
        ].dropna(subset=["_actual_hourly_delta"])

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
        hour_apparent_temp_c = hour_to_apparent_temp.get(hour, hour_temp_c)
        has_hour_apparent_temp = not np.isnan(hour_apparent_temp_c)
        cooling = _cooling_degree(hour_temp_c, cooling_base_temp_c) if has_hour_temp else np.nan
        heating = _heating_degree(hour_temp_c, heating_base_temp_c) if has_hour_temp else np.nan
        apparent_cooling = (
            _cooling_degree(hour_apparent_temp_c, cooling_base_temp_c)
            if has_hour_apparent_temp
            else np.nan
        )
        cooling_3h_mean = _degree_window_mean(
            ts,
            3,
            lambda temp: _cooling_degree(temp, cooling_base_temp_c),
        )
        cooling_6h_mean = _degree_window_mean(
            ts,
            6,
            lambda temp: _cooling_degree(temp, cooling_base_temp_c),
        )
        heating_3h_mean = _degree_window_mean(
            ts,
            3,
            lambda temp: _heating_degree(temp, heating_base_temp_c),
        )
        heating_6h_mean = _degree_window_mean(
            ts,
            6,
            lambda temp: _heating_degree(temp, heating_base_temp_c),
        )
        temp_72h_mean = _degree_window_mean(ts, 72, lambda temp: temp)
        cooling_72h_mean = _degree_window_mean(
            ts,
            72,
            lambda temp: _cooling_degree(temp, cooling_base_temp_c),
        )
        heating_72h_mean = _degree_window_mean(
            ts,
            72,
            lambda temp: _heating_degree(temp, heating_base_temp_c),
        )
        temp_24h = temp_by_ts.get(ts - pd.Timedelta(hours=24), float("nan"))
        has_temp_24h = not np.isnan(temp_24h)
        cooling_24h = (
            _cooling_degree(temp_24h, cooling_base_temp_c)
            if has_temp_24h
            else np.nan
        )
        temp_168h = temp_by_ts.get(ts - pd.Timedelta(hours=168), float("nan"))
        has_temp_168h = not np.isnan(temp_168h)
        cooling_168h = (
            _cooling_degree(temp_168h, cooling_base_temp_c)
            if has_temp_168h
            else np.nan
        )
        temp_delta_24h = (
            hour_temp_c - temp_24h
            if has_hour_temp and has_temp_24h
            else np.nan
        )
        cooling_delta_24h = (
            cooling - cooling_24h
            if has_hour_temp and has_temp_24h
            else np.nan
        )
        temp_delta_168h = (
            hour_temp_c - temp_168h
            if has_hour_temp and has_temp_168h
            else np.nan
        )
        cooling_delta_168h = (
            cooling - cooling_168h
            if has_hour_temp and has_temp_168h
            else np.nan
        )
        temp_1h = _temp_at(ts - pd.Timedelta(hours=1))
        temp_2h = _temp_at(ts - pd.Timedelta(hours=2))
        apparent_temp_1h = _apparent_temp_at(ts - pd.Timedelta(hours=1))
        has_temp_1h = not np.isnan(temp_1h)
        has_temp_2h = not np.isnan(temp_2h)
        has_apparent_temp_1h = not np.isnan(apparent_temp_1h)
        cooling_1h = (
            _cooling_degree(temp_1h, cooling_base_temp_c)
            if has_temp_1h
            else np.nan
        )
        temp_delta_1h = (
            hour_temp_c - temp_1h
            if has_hour_temp and has_temp_1h
            else np.nan
        )
        temp_delta_2h = (
            hour_temp_c - temp_2h
            if has_hour_temp and has_temp_2h
            else np.nan
        )
        apparent_temp_delta_1h = (
            hour_apparent_temp_c - apparent_temp_1h
            if has_hour_apparent_temp and has_apparent_temp_1h
            else np.nan
        )
        cooling_delta_1h = (
            cooling - cooling_1h
            if has_hour_temp and has_temp_1h
            else np.nan
        )
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
        business_morning = int(is_target_non_business_day == 0 and 5 <= hour <= 11)
        business_late_afternoon = int(
            is_target_non_business_day == 0 and 15 <= hour <= 18
        )
        recent_same_business_type_mean = (
            float(recent_same_business_type["actual_mw"].mean())
            if len(recent_same_business_type) > 0
            else np.nan
        )
        recent_same_business_type_delta_mean = (
            float(recent_same_business_type_delta["_actual_hourly_delta"].mean())
            if len(recent_same_business_type_delta) > 0
            else np.nan
        )
        recent_same_business_type_delta_q25 = (
            float(recent_same_business_type_delta["_actual_hourly_delta"].quantile(0.25))
            if len(recent_same_business_type_delta) >= 3
            else recent_same_business_type_delta_mean
        )
        same_day_recent_deltas = same_day_actuals_before_ts.tail(2)
        same_day_latest_actual_hour = (
            int(same_day_actuals_before_ts["ts"].dt.hour.iloc[-1])
            if len(same_day_actuals_before_ts) > 0
            else np.nan
        )
        same_day_latest_hourly_delta = (
            float(same_day_actuals_before_ts["_actual_hourly_delta"].iloc[-1])
            if len(same_day_actuals_before_ts) > 0
            else np.nan
        )
        same_day_recent_hourly_delta_mean = (
            float(same_day_recent_deltas["_actual_hourly_delta"].mean())
            if len(same_day_recent_deltas) > 0
            else np.nan
        )
        lag_last_biz_hour = _lag_day("last_biz_day")
        lag_last_nonhol_hour = _lag_day("last_nonhol_day")
        lag_24h_to_same_business_type_gap = recent_same_business_type_mean - lag_24h

        rows.append({
            "hour":                   hour,
            "dayofweek":              day_of_week,
            "month":                  ts.month,
            "is_holiday":             is_public_holiday,
            "is_weekend":             int(day_of_week >= 5),
            "is_non_business_day":    is_target_non_business_day,
            "lag_24h":                lag_24h,
            "lag_48h":                lag_48h,
            "lag_168h":               lag_168h,
            "lag_336h":               lag_336h,
            "lag_24h_hourly_delta":   lag_24h_hourly_delta,
            "lag_168h_hourly_delta":  lag_168h_hourly_delta,
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
            "recent_same_business_type_mean": recent_same_business_type_mean,
            "recent_same_business_type_delta_mean": recent_same_business_type_delta_mean,
            "recent_same_business_type_delta_q25": recent_same_business_type_delta_q25,
            "same_day_latest_actual_hour": same_day_latest_actual_hour,
            "same_day_latest_hourly_delta": same_day_latest_hourly_delta,
            "same_day_recent_hourly_delta_mean": same_day_recent_hourly_delta_mean,
            "lag_last_biz_hour":      lag_last_biz_hour,
            "lag_last_nonhol_hour":   lag_last_nonhol_hour,
            "consec_holiday_len":     target_date_features["consec_holiday_len"],
            "days_since_holiday_end": target_date_features["days_since_holiday_end"],
            "major_holiday_season":   target_date_features["major_holiday_season"],
            "temp_c":           hour_temp_c,
            "cooling_degree":   cooling,
            "heating_degree":   heating,
            "apparent_temp_c":   hour_apparent_temp_c,
            "apparent_cooling_degree": apparent_cooling,
            "temp_anomaly_7d":  temp_anomaly_vs_7d_mean,
            "temp_anomaly_doy": temp_anomaly_vs_month_hour_mean,
            "temp_delta_24h":       temp_delta_24h,
            "cooling_delta_24h":    cooling_delta_24h,
            "temp_delta_168h":      temp_delta_168h,
            "cooling_delta_168h":   cooling_delta_168h,
            "temp_delta_1h":        temp_delta_1h,
            "temp_delta_2h":        temp_delta_2h,
            "apparent_temp_delta_1h": apparent_temp_delta_1h,
            "cooling_delta_1h":     cooling_delta_1h,
            "cooling_degree_3h_mean": cooling_3h_mean,
            "cooling_degree_6h_mean": cooling_6h_mean,
            "heating_degree_3h_mean": heating_3h_mean,
            "heating_degree_6h_mean": heating_6h_mean,
            "temp_72h_mean": temp_72h_mean,
            "cooling_degree_72h_mean": cooling_72h_mean,
            "heating_degree_72h_mean": heating_72h_mean,
            "business_morning_x_temp_delta_24h": (
                business_morning * temp_delta_24h
            ),
            "business_morning_x_temp_anomaly_7d": (
                business_morning * temp_anomaly_vs_7d_mean
            ),
            "business_morning_x_temp_anomaly_doy": (
                business_morning * temp_anomaly_vs_month_hour_mean
            ),
            "business_late_afternoon_x_temp_delta_1h": (
                business_late_afternoon * temp_delta_1h
            ),
            "business_late_afternoon_x_cooling_delta_1h": (
                business_late_afternoon * cooling_delta_1h
            ),
            "holiday_x_heat":                    holiday_heat_interaction,
            "post_holiday_x_heat":               post_holiday_heat_interaction,
            "business_hour_x_post_holiday_heat": business_hour_post_holiday_heat_interaction,
            "lag_24h_dsh":    target_date_features["lag_24h_dsh"],
            "lag_24h_consec": target_date_features["lag_24h_consec"],
            "lag_168h_dsh":   target_date_features["lag_168h_dsh"],
            "lag_24h_business_type_mismatch": lag_24h_business_type_mismatch,
            "lag_24h_mismatch_x_business_hour": (
                lag_24h_business_type_mismatch * int(8 <= hour <= 18)
            ),
            "lag_24h_to_last_biz_gap": lag_last_biz_hour - lag_24h,
            "lag_24h_to_same_business_type_gap": lag_24h_to_same_business_type_gap,
            "lag_24h_gap_x_business_hour": (
                lag_24h_business_type_mismatch
                * int(6 <= hour <= 18)
                * lag_24h_to_same_business_type_gap
            ),
        })

    out = _add_midday_transition_cols(pd.DataFrame(rows))
    columns = FEATURE_COLS + (INFERENCE_CONTEXT_COLS if include_context else [])
    return out[columns]
