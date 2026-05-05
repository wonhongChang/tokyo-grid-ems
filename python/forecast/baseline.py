from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import jpholiday
    _JPHOLIDAY_AVAILABLE = True
except ImportError:
    _JPHOLIDAY_AVAILABLE = False

JST = ZoneInfo("Asia/Tokyo")

# Seasonal window half-width used when matching holiday days across years.
# 30 days keeps Golden Week (Apr 29 - May 6) together while excluding Spring
# Equinox (Mar 20, ±46 days from May 5) which has ~3,600 万kW vs GW ~2,500 万kW.
_HOLIDAY_SEASON_DAYS = 30
_WEEKDAY_SEASON_DAYS = 28  # ±4 weeks year-over-year window for regular weekday matching


def _is_holiday(d: date) -> bool:
    if not _JPHOLIDAY_AVAILABLE:
        return False
    return bool(jpholiday.is_holiday(d))


def _is_holiday_or_weekend(d: date) -> bool:
    return d.weekday() >= 5 or _is_holiday(d)


@dataclass
class HourlyForecast:
    ts: str           # ISO 8601 with +09:00
    forecast_mw: float
    p95_lower_mw: float
    p95_upper_mw: float
    p99_lower_mw: float
    p99_upper_mw: float


def _select_training_rows(
    hist: pd.DataFrame,
    target_date: date,
    n_weeks: int,
    min_samples: int,
) -> pd.DataFrame:
    """Return the rows from hist to use as training data for target_date.

    Holiday strategy: when target_date is a public holiday (jpholiday), gather
    past holiday days within a ±HOLIDAY_SEASON_DAYS window for each prior year
    (covers the same seasonal period). Falls back to same-weekday non-holiday
    window when fewer than min_samples holiday days are available.
    """
    target_ts = pd.Timestamp(target_date, tz=JST)

    if _is_holiday(target_date):
        day_of_year = target_date.timetuple().tm_yday
        candidate_dates: list[date] = []

        # Walk back up to 5 years collecting ONLY public holiday days in the seasonal
        # window — NOT regular weekends. Weekends have ~300 万kW higher demand than
        # Golden Week holidays and would bias the mean upward.
        for years_back in range(1, 6):
            year = target_date.year - years_back
            start = date(year, 1, 1) + timedelta(days=max(0, day_of_year - _HOLIDAY_SEASON_DAYS - 1))
            end   = date(year, 1, 1) + timedelta(days=min(364, day_of_year + _HOLIDAY_SEASON_DAYS - 1))
            d = start
            while d <= end:
                if _is_holiday(d):  # public holidays only — excludes regular weekends
                    candidate_dates.append(d)
                d += timedelta(days=1)

        if candidate_dates:
            candidate_ts = {pd.Timestamp(d, tz=JST) for d in candidate_dates}
            holiday_hist = hist[
                (hist["ts"] < target_ts) &
                hist["ts"].dt.normalize().isin(candidate_ts)
            ]
            # Count unique training days (need at least min_samples distinct days)
            unique_days = holiday_hist["ts"].dt.normalize().nunique()
            if unique_days >= min_samples:
                return holiday_hist

    # Default: same-weekday non-holiday — recent rolling window PLUS
    # year-over-year same-season same-weekday from up to 5 prior years.
    target_dow = target_date.weekday()
    day_of_year = target_date.timetuple().tm_yday

    cutoff_ts = target_ts - pd.Timedelta(weeks=n_weeks)
    recent = hist[
        (hist["ts"] < target_ts) &
        (hist["ts"] >= cutoff_ts) &
        (hist["ts"].dt.dayofweek == target_dow)
    ]

    yoy_dates: set[date] = set()
    for years_back in range(1, 6):
        year = target_date.year - years_back
        start_doy = max(1, day_of_year - _WEEKDAY_SEASON_DAYS)
        end_doy   = min(365, day_of_year + _WEEKDAY_SEASON_DAYS)
        try:
            start = date(year, 1, 1) + timedelta(days=start_doy - 1)
            end   = date(year, 1, 1) + timedelta(days=end_doy   - 1)
        except ValueError:
            continue
        d = start
        while d <= end:
            if d.weekday() == target_dow:
                yoy_dates.add(d)
            d += timedelta(days=1)

    yoy_ts = {pd.Timestamp(d, tz=JST) for d in yoy_dates}
    yoy = hist[
        (hist["ts"] < target_ts) &
        hist["ts"].dt.normalize().isin(yoy_ts)
    ]

    combined = pd.concat([recent, yoy]).drop_duplicates(subset=["ts"])
    if _JPHOLIDAY_AVAILABLE:
        combined = combined[~combined["ts"].dt.date.apply(_is_holiday)]
    return combined


def compute_forecast(
    all_history: pd.DataFrame,
    target_date: date,
    n_weeks: int = 12,
    min_samples: int = 4,
) -> list[HourlyForecast]:
    """
    Compute hourly baseline forecast for target_date.

    For regular weekdays: uses same-weekday non-holiday data from the n_weeks
    window. For Japanese public holidays: uses past holiday days in a seasonal
    ±60-day window across up to 5 prior years. Falls back to weekday window if
    not enough holiday samples.

    all_history: DataFrame with columns [ts (tz-aware Asia/Tokyo), actual_mw].
                 May include target_date itself — filtered out internally.
    """
    if all_history.empty or "actual_mw" not in all_history.columns:
        return []

    # Ensure ts is datetime (pd.concat with empty DataFrames can degrade dtype to object)
    hist = all_history.copy()
    if not pd.api.types.is_datetime64_any_dtype(hist["ts"]):
        hist["ts"] = pd.to_datetime(hist["ts"], utc=True).dt.tz_convert("Asia/Tokyo")

    hist = _select_training_rows(hist, target_date, n_weeks, min_samples)

    if hist.empty:
        return []

    hist = hist.copy()
    hist["_hour"] = hist["ts"].dt.hour

    result: list[HourlyForecast] = []
    for hour in range(24):
        vals = hist[hist["_hour"] == hour]["actual_mw"].dropna()
        if len(vals) < min_samples:
            continue

        mean = float(vals.mean())
        std = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0

        ts_obj = pd.Timestamp(
            year=target_date.year, month=target_date.month, day=target_date.day,
            hour=hour, minute=0, tzinfo=JST,
        )
        result.append(HourlyForecast(
            ts=ts_obj.isoformat(timespec="seconds"),
            forecast_mw=round(mean, 1),
            p95_lower_mw=round(mean - 1.96 * std, 1),
            p95_upper_mw=round(mean + 1.96 * std, 1),
            p99_lower_mw=round(mean - 2.576 * std, 1),
            p99_upper_mw=round(mean + 2.576 * std, 1),
        ))

    return result


def forecast_to_dict(f: HourlyForecast) -> dict:
    return {
        "ts": f.ts,
        "forecastMw": f.forecast_mw,
        "p95LowerMw": f.p95_lower_mw,
        "p95UpperMw": f.p95_upper_mw,
        "p99LowerMw": f.p99_lower_mw,
        "p99UpperMw": f.p99_upper_mw,
    }


def peak_of_forecasts(fc_list: list[HourlyForecast]) -> dict | None:
    if not fc_list:
        return None
    peak = max(fc_list, key=lambda f: f.forecast_mw)
    return {
        "forecastMw": peak.forecast_mw,
        "at": peak.ts,
        "interval": {
            "p95Lower": peak.p95_lower_mw,
            "p95Upper": peak.p95_upper_mw,
        },
    }
