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
    "temp_anomaly_doy",  # temp_c minus historical (month, hour) mean (how abnormal vs season)
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
    dfeat: dict[date, dict],
) -> pd.DataFrame:
    """Append lag_last_biz_hour / lag_last_nonhol_hour and date-level features."""

    def _lag(ts: pd.Timestamp, day_key: str) -> float:
        d = ts.date()
        target_day = dfeat.get(d, {}).get(day_key)
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
        lambda d: dfeat.get(d, {}).get("consec_holiday_len", 0)
    )
    df["days_since_holiday_end"] = df["ts"].dt.date.map(
        lambda d: dfeat.get(d, {}).get("days_since_holiday_end", 0)
    )
    df["major_holiday_season"] = df["ts"].dt.date.map(
        lambda d: dfeat.get(d, {}).get("major_holiday_season", 0)
    )
    df["lag_24h_dsh"] = df["ts"].dt.date.map(
        lambda d: dfeat.get(d, {}).get("lag_24h_dsh", 0)
    )
    df["lag_24h_consec"] = df["ts"].dt.date.map(
        lambda d: dfeat.get(d, {}).get("lag_24h_consec", 0)
    )
    df["lag_168h_dsh"] = df["ts"].dt.date.map(
        lambda d: dfeat.get(d, {}).get("lag_168h_dsh", 0)
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
    src = df[["ts", "actual_mw"]].copy()
    for hours, col in [
        (24,  "lag_24h"),
        (48,  "lag_48h"),
        (168, "lag_168h"),
        (336, "lag_336h"),
    ]:
        shifted = (
            src.assign(ts=src["ts"] + pd.Timedelta(hours=hours))
               .rename(columns={"actual_mw": col})
        )
        df = df.merge(shifted, on="ts", how="left")

    # Rolling stats within each (hour, dayofweek) slot
    grp = df.groupby(["hour", "dayofweek"])["actual_mw"]
    df["roll_4w_mean"] = grp.transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    )
    df["roll_4w_std"] = grp.transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).std().fillna(0.0)
    )

    # Holiday lag correction features
    ts_to_mw = dict(zip(df["ts"], df["actual_mw"]))
    dfeat = _date_features(sorted(set(df["ts"].dt.date)))
    df = _add_holiday_lag_cols(df, ts_to_mw, dfeat)

    # Temperature features
    if "temp_c" in df.columns:
        df["cooling_degree"]  = (df["temp_c"] - 22.0).clip(lower=0.0)
        df["heating_degree"]  = (10.0 - df["temp_c"]).clip(lower=0.0)
        # How abnormal vs recent 7 days (shift 1h to prevent self-inclusion)
        _t7 = df["temp_c"].shift(1).rolling(168, min_periods=24).mean()
        df["temp_anomaly_7d"] = df["temp_c"] - _t7
        # How abnormal vs historical same (month, hour) average
        _mh = df.groupby(["month", "hour"])["temp_c"].transform("mean")
        df["temp_anomaly_doy"] = df["temp_c"] - _mh
    else:
        df["temp_c"]           = np.nan
        df["cooling_degree"]   = np.nan
        df["heating_degree"]   = np.nan
        df["temp_anomaly_7d"]  = np.nan
        df["temp_anomaly_doy"] = np.nan

    # Interaction features: holiday × heat surplus
    _heat7d = df["temp_anomaly_7d"].clip(lower=0.0)
    _post_hol = df["days_since_holiday_end"].between(1, 2).astype(float)
    df["holiday_x_heat"]                    = df["consec_holiday_len"] * _heat7d
    df["post_holiday_x_heat"]               = _post_hol * _heat7d
    df["business_hour_x_post_holiday_heat"] = df["hour"].between(9, 18).astype(float) * _post_hol * _heat7d

    df = df.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    return df[FEATURE_COLS].copy(), df["actual_mw"].copy()


def build_inference_features(cache: pd.DataFrame, target_date: date) -> pd.DataFrame:
    """Return a 24-row DataFrame (one row per hour) for predicting target_date.

    cache may contain virtual rows (NaN actual_mw, non-NaN temp_c) for target_date
    added by run_batch._extend_cache_with_forecast_weather.
    """
    cache = _ensure_tz(cache)
    notna = cache[cache["actual_mw"].notna()].copy()

    ts_to_mw: dict = dict(zip(notna["ts"], notna["actual_mw"]))
    notna["_hour"] = notna["ts"].dt.hour
    notna["_dow"]  = notna["ts"].dt.dayofweek

    is_hol  = int(_is_holiday(target_date))
    dfeat   = _date_features([target_date])

    # Temperature lookup for target_date (includes virtual forecast rows)
    if "temp_c" in cache.columns:
        day_temp = cache[cache["ts"].dt.date == target_date][["ts", "temp_c"]].dropna(subset=["temp_c"])
        hour_to_temp: dict[int, float] = {
            int(r["ts"].hour): float(r["temp_c"]) for _, r in day_temp.iterrows()
        }
    else:
        hour_to_temp = {}

    # Trailing 7-day mean temperature (same for all 24 hours of target_date)
    _cutoff = pd.Timestamp(
        year=target_date.year, month=target_date.month, day=target_date.day, tz=JST
    )
    _past_168 = cache[
        (cache["ts"] < _cutoff) &
        (cache["ts"] >= _cutoff - pd.Timedelta(hours=168))
    ]["temp_c"].dropna() if "temp_c" in cache.columns else pd.Series(dtype=float)
    _past_7d_mean = float(_past_168.mean()) if len(_past_168) >= 24 else float("nan")

    # Historical (month, hour) mean temperature from past data
    if "temp_c" in cache.columns:
        _hist = cache[cache["ts"].dt.date < target_date].copy()
        _mh_dict: dict = (
            _hist.assign(_m=_hist["ts"].dt.month, _h=_hist["ts"].dt.hour)
                 .groupby(["_m", "_h"])["temp_c"]
                 .mean()
                 .to_dict()
        )
    else:
        _mh_dict = {}
    _target_month = target_date.month

    rows = []
    for hour in range(24):
        ts = pd.Timestamp(
            year=target_date.year, month=target_date.month, day=target_date.day,
            hour=hour, tz=JST,
        )
        dow = ts.dayofweek

        lag_24h  = ts_to_mw.get(ts - pd.Timedelta(hours=24),  np.nan)
        lag_48h  = ts_to_mw.get(ts - pd.Timedelta(hours=48),  np.nan)
        lag_168h = ts_to_mw.get(ts - pd.Timedelta(hours=168), np.nan)
        lag_336h = ts_to_mw.get(ts - pd.Timedelta(hours=336), np.nan)

        same = notna[
            (notna["_hour"] == hour) &
            (notna["_dow"]  == dow)  &
            (notna["ts"]    <  ts)
        ].tail(4)

        feat = dfeat[target_date]

        def _lag_day(day_key: str) -> float:
            d = feat.get(day_key)
            if d is None:
                return np.nan
            key_ts = pd.Timestamp(year=d.year, month=d.month, day=d.day,
                                  hour=hour, tz=JST)
            return ts_to_mw.get(key_ts, np.nan)

        temp_val = hour_to_temp.get(hour, float("nan"))
        _t_ok    = not np.isnan(temp_val)
        cooling  = max(0.0, temp_val - 22.0) if _t_ok else np.nan
        heating  = max(0.0, 10.0 - temp_val) if _t_ok else np.nan
        _a7d_ref = _past_7d_mean
        a7d      = (temp_val - _a7d_ref) if (_t_ok and not np.isnan(_a7d_ref)) else np.nan
        _adoy_ref = _mh_dict.get((_target_month, hour), float("nan"))
        adoy      = (temp_val - _adoy_ref) if (_t_ok and not np.isnan(_adoy_ref)) else np.nan

        # Interaction features
        dsh = feat["days_since_holiday_end"]
        _heat7d    = max(0.0, a7d) if not np.isnan(a7d) else np.nan
        _post_hol  = int(1 <= dsh <= 2)
        hol_x_heat  = feat["consec_holiday_len"] * _heat7d  # nan if _heat7d is nan
        post_x_heat = _post_hol * _heat7d                   # nan if _heat7d is nan
        biz_x_heat  = int(9 <= hour <= 18) * _post_hol * _heat7d  # nan if _heat7d is nan

        rows.append({
            "hour":                   hour,
            "dayofweek":              dow,
            "month":                  ts.month,
            "is_holiday":             is_hol,
            "is_weekend":             int(dow >= 5),
            "is_non_business_day":    int(_is_nonworking(target_date)),
            "lag_24h":                lag_24h,
            "lag_48h":                lag_48h,
            "lag_168h":               lag_168h,
            "lag_336h":               lag_336h,
            "roll_4w_mean":           float(same["actual_mw"].mean()) if len(same) > 0 else np.nan,
            "roll_4w_std":            float(same["actual_mw"].std())  if len(same) > 1 else 0.0,
            "lag_last_biz_hour":      _lag_day("last_biz_day"),
            "lag_last_nonhol_hour":   _lag_day("last_nonhol_day"),
            "consec_holiday_len":     feat["consec_holiday_len"],
            "days_since_holiday_end": feat["days_since_holiday_end"],
            "major_holiday_season":   feat["major_holiday_season"],
            "temp_c":           temp_val,
            "cooling_degree":   cooling,
            "heating_degree":   heating,
            "temp_anomaly_7d":  a7d,
            "temp_anomaly_doy": adoy,
            "holiday_x_heat":                    hol_x_heat,
            "post_holiday_x_heat":               post_x_heat,
            "business_hour_x_post_holiday_heat": biz_x_heat,
            "lag_24h_dsh":    feat["lag_24h_dsh"],
            "lag_24h_consec": feat["lag_24h_consec"],
            "lag_168h_dsh":   feat["lag_168h_dsh"],
        })

    return pd.DataFrame(rows)[FEATURE_COLS]
