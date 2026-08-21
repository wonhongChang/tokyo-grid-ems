"""Leakage-safe rolling calibration for operational forecast intervals."""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Iterable


_TEPCO_FORECAST_FALLBACK_SOURCE = "tepco_forecast_fallback"
_TIME_BANDS: tuple[tuple[str, int, int], ...] = (
    ("overnight", 0, 5),
    ("morning", 6, 10),
    ("daytime", 11, 15),
    ("late_afternoon", 16, 18),
    ("evening", 19, 23),
)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _is_non_business_day(target: date) -> bool:
    try:
        import jpholiday

        return target.weekday() >= 5 or bool(jpholiday.is_holiday(target))
    except ImportError:
        return target.weekday() >= 5


def interval_time_band(hour: int) -> str | None:
    """Return the operational interval-calibration band for an hour."""
    for name, start_hour, end_hour in _TIME_BANDS:
        if start_hour <= int(hour) <= end_hour:
            return name
    return None


def finite_sample_upper_quantile(
    values: Iterable[float],
    coverage: float,
) -> float | None:
    """Return the finite-sample conformal upper quantile.

    The rank is ceil((n + 1) * coverage), clamped to the available sample.
    This is deliberately more conservative than an interpolated percentile.
    """
    clean_values = sorted(
        value
        for raw_value in values
        if (value := _finite_float(raw_value)) is not None
    )
    if not clean_values or not 0.0 < float(coverage) < 1.0:
        return None
    rank = min(len(clean_values), math.ceil((len(clean_values) + 1) * coverage))
    return clean_values[rank - 1]


def _actual_by_hour(payload: dict | None) -> dict[int, float]:
    result: dict[int, float] = {}
    for point in (payload or {}).get("series", []):
        if point.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE:
            continue
        actual = _finite_float(point.get("actualMw"))
        timestamp = point.get("ts")
        if actual is None or not timestamp:
            continue
        try:
            hour = int(str(timestamp)[11:13])
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23:
            result[hour] = actual
    return result


def _forecast_by_hour(payload: dict | None) -> dict[int, float]:
    result: dict[int, float] = {}
    for point in (payload or {}).get("series", []):
        forecast = _finite_float(point.get("forecastMw"))
        timestamp = point.get("ts")
        if forecast is None or not timestamp:
            continue
        try:
            hour = int(str(timestamp)[11:13])
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23:
            result[hour] = forecast
    return result


def _finalized_dates(out_dir: Path, target_date: date) -> list[date]:
    state = _read_json(out_dir / ".etl_state.json") or {}
    finalized: list[date] = []
    for raw_date in state.get("okDates", []):
        try:
            parsed = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if parsed < target_date:
            finalized.append(parsed)
    return sorted(set(finalized))


def build_rolling_conformal_floor_profile(
    out_dir: Path,
    target_date: date,
    config: dict | None,
) -> dict | None:
    """Build a same-regime, time-band p95 minimum-width profile.

    Only dates marked complete by ETL are eligible. The target date is always
    excluded, so intraday actuals cannot leak into its forecast interval.
    """
    interval_config = (config or {}).get("interval_calibration", {})
    floor_config = interval_config.get("rolling_conformal_floor", {})
    if not bool(floor_config.get("enabled", False)):
        return None

    window_days = max(1, int(floor_config.get("window_days", 28)))
    target_coverage = float(floor_config.get("target_coverage", 0.95))
    if not 0.0 < target_coverage < 1.0:
        target_coverage = 0.95
    min_samples = max(1, int(floor_config.get("min_samples_per_band", 24)))
    configured_min = max(
        0.0,
        float(interval_config.get("min_p95_half_width_mw", 500.0)),
    )
    configured_max = _finite_float(interval_config.get("max_p95_half_width_mw"))
    width_scale = _finite_float(interval_config.get("p95_half_width_scale"))
    if width_scale is None or width_scale <= 0.0:
        width_scale = 1.0

    target_is_non_business = _is_non_business_day(target_date)
    eligible_dates: list[date] = []
    rows_by_band: dict[str, list[float]] = {name: [] for name, _, _ in _TIME_BANDS}

    # The window is the latest N finalized calendar days, then the target's
    # business regime is selected inside that window.
    for historical_date in reversed(_finalized_dates(out_dir, target_date)):
        actual_by_hour = _actual_by_hour(
            _read_json(out_dir / "actual" / f"{historical_date.isoformat()}.json")
        )
        forecast_by_hour = _forecast_by_hour(
            _read_json(out_dir / "forecast" / f"{historical_date.isoformat()}.json")
        )
        if len(actual_by_hour) != 24 or len(forecast_by_hour) != 24:
            continue
        eligible_dates.append(historical_date)
        if len(eligible_dates) >= window_days:
            break

    eligible_dates.sort()
    contributing_dates: list[date] = []
    for historical_date in eligible_dates:
        if _is_non_business_day(historical_date) != target_is_non_business:
            continue
        actual_by_hour = _actual_by_hour(
            _read_json(out_dir / "actual" / f"{historical_date.isoformat()}.json")
        )
        forecast_by_hour = _forecast_by_hour(
            _read_json(out_dir / "forecast" / f"{historical_date.isoformat()}.json")
        )
        if len(actual_by_hour) != 24 or len(forecast_by_hour) != 24:
            continue
        contributing_dates.append(historical_date)
        for hour in range(24):
            band = interval_time_band(hour)
            if band is None:
                continue
            rows_by_band[band].append(
                abs(forecast_by_hour[hour] - actual_by_hour[hour])
            )

    floors_by_band: dict[str, float] = {}
    sample_hours_by_band: dict[str, int] = {}
    for band, residuals in rows_by_band.items():
        sample_hours_by_band[band] = len(residuals)
        if len(residuals) < min_samples:
            continue
        floor = finite_sample_upper_quantile(residuals, target_coverage)
        if floor is None:
            continue
        floor = max(configured_min, floor)
        if configured_max is not None:
            floor = min(floor, configured_max)
        floors_by_band[band] = round(float(floor), 1)

    availability = "ok" if floors_by_band else "insufficient_history"
    return {
        "schemaVersion": "1.1.0",
        "availability": availability,
        "method": "rolling_conformal_minimum_floor",
        "source": "finalized_actual_vs_served_forecast",
        "targetCoveragePct": round(target_coverage * 100.0, 1),
        "windowDays": window_days,
        "minimumSamplesPerBand": min_samples,
        "targetRegime": "nonBusiness" if target_is_non_business else "business",
        "historyStart": eligible_dates[0].isoformat() if eligible_dates else None,
        "historyEnd": eligible_dates[-1].isoformat() if eligible_dates else None,
        "contributingDates": len(contributing_dates),
        "sampleHoursByTimeBand": sample_hours_by_band,
        "floorsMwByTimeBand": floors_by_band,
        "preScaleMaxP95HalfWidthMw": (
            round(configured_max, 1) if configured_max is not None else None
        ),
        "p95HalfWidthScale": round(width_scale, 4),
        "maxP95HalfWidthMw": (
            round(configured_max * width_scale, 1)
            if configured_max is not None
            else None
        ),
    }
