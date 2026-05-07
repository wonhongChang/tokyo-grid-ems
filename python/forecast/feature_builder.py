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
    "lag_last_biz_hour",       # same hour on the last non-holiday weekday
    "lag_last_nonhol_hour",    # same hour on the last non-public-holiday day
    "consec_holiday_len",      # consecutive holiday/weekend days immediately before this date
    "days_since_holiday_end",  # calendar days since the holiday period ended (capped at 7)
    "major_holiday_season",    # 0=normal 1=golden_week_zone 2=obon_zone 3=newyear_zone
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
        result[d] = {
            "last_biz_day":          _last_biz_day(d),
            "last_nonhol_day":       _last_nonhol_day(d),
            "consec_holiday_len":    _consec_holiday_len(d),
            "days_since_holiday_end": _days_since_holiday_end(d),
            "major_holiday_season":  _major_holiday_season(d),
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
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_training_features(cache: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y) from hourly cache for training.

    Rows with missing actual_mw or any feature column are dropped.
    Lag features use timestamp-shift merge so gaps in the cache are handled
    correctly. Rolling stats are computed within each (hour, dayofweek) group
    with shift(1) to prevent self-inclusion.
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

    df = df.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    return df[FEATURE_COLS].copy(), df["actual_mw"].copy()


def build_inference_features(cache: pd.DataFrame, target_date: date) -> pd.DataFrame:
    """Return a 24-row DataFrame (one row per hour) for predicting target_date."""
    cache = _ensure_tz(cache)
    notna = cache[cache["actual_mw"].notna()].copy()

    ts_to_mw: dict = dict(zip(notna["ts"], notna["actual_mw"]))
    notna["_hour"] = notna["ts"].dt.hour
    notna["_dow"]  = notna["ts"].dt.dayofweek

    is_hol  = int(_is_holiday(target_date))
    dfeat   = _date_features([target_date])

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

        rows.append({
            "hour":                  hour,
            "dayofweek":             dow,
            "month":                 ts.month,
            "is_holiday":            is_hol,
            "is_weekend":            int(dow >= 5),
            "is_non_business_day":   int(_is_nonworking(target_date)),
            "lag_24h":               lag_24h,
            "lag_48h":               lag_48h,
            "lag_168h":              lag_168h,
            "lag_336h":              lag_336h,
            "roll_4w_mean":          float(same["actual_mw"].mean()) if len(same) > 0 else np.nan,
            "roll_4w_std":           float(same["actual_mw"].std())  if len(same) > 1 else 0.0,
            "lag_last_biz_hour":     _lag_day("last_biz_day"),
            "lag_last_nonhol_hour":  _lag_day("last_nonhol_day"),
            "consec_holiday_len":    feat["consec_holiday_len"],
            "days_since_holiday_end": feat["days_since_holiday_end"],
            "major_holiday_season":  feat["major_holiday_season"],
        })

    return pd.DataFrame(rows)[FEATURE_COLS]
