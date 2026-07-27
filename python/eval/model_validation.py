"""Temporal validation and promotion checks for the production forecaster."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from python.forecast.baseline import compute_forecast
from python.forecast.lgbm_model import LGBMForecaster

JST = ZoneInfo("Asia/Tokyo")

TIME_BANDS: tuple[tuple[str, int, int], ...] = (
    ("overnight", 0, 5),
    ("morning", 6, 10),
    ("daytime", 11, 15),
    ("late_afternoon", 16, 18),
    ("evening", 19, 23),
)


def _is_non_business_day(target: date) -> bool:
    try:
        import jpholiday

        return target.weekday() >= 5 or bool(jpholiday.is_holiday(target))
    except ImportError:
        return target.weekday() >= 5


def _observed_mask(cache: pd.DataFrame) -> pd.Series:
    mask = cache["actual_mw"].notna()
    if "actual_source" in cache.columns:
        mask &= (
            cache["actual_source"].fillna("observed")
            != "tepco_forecast_fallback"
        )
    return mask


def _deduplicated_observed(cache: pd.DataFrame) -> pd.DataFrame:
    """Return one observed row per timestamp for validation."""
    observed = cache.loc[_observed_mask(cache)].copy()
    return (
        observed.sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )


def _complete_dates(cache: pd.DataFrame) -> list[date]:
    observed = _deduplicated_observed(cache)[["ts", "actual_mw"]]
    counts = observed.groupby(observed["ts"].dt.date)["actual_mw"].count()
    return sorted(day for day, count in counts.items() if int(count) >= 24)


def _metric_rows(rows: Iterable[dict]) -> dict:
    values = list(rows)
    if not values:
        return {
            "hours": 0,
            "maeMw": None,
            "wapePct": None,
            "rmseMw": None,
            "maxErrorMw": None,
            "shapeDeltaMaeMw": None,
        }

    actual = np.asarray([row["actual"] for row in values], dtype=float)
    predicted = np.asarray([row["predicted"] for row in values], dtype=float)
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Validation metrics require finite actual and predicted values.")
    errors = predicted - actual
    denominator = float(np.abs(actual).sum())

    by_date: dict[date, list[dict]] = {}
    for row in values:
        by_date.setdefault(row["date"], []).append(row)
    shape_errors: list[float] = []
    for day_rows in by_date.values():
        ordered = sorted(day_rows, key=lambda row: row["hour"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["hour"] != previous["hour"] + 1:
                continue
            actual_delta = current["actual"] - previous["actual"]
            predicted_delta = current["predicted"] - previous["predicted"]
            shape_errors.append(abs(predicted_delta - actual_delta))

    return {
        "hours": int(len(values)),
        "maeMw": round(float(np.mean(np.abs(errors))), 1),
        "wapePct": round(float(np.abs(errors).sum() / denominator * 100.0), 3)
        if denominator > 0
        else None,
        "rmseMw": round(float(np.sqrt(np.mean(np.square(errors)))), 1),
        "maxErrorMw": round(float(np.max(np.abs(errors))), 1),
        "shapeDeltaMaeMw": round(float(np.mean(shape_errors)), 1)
        if shape_errors
        else None,
    }


def _metric_bundle(rows: list[dict]) -> dict:
    result = {"overall": _metric_rows(rows), "regimes": {}, "timeBands": {}}
    result["regimes"]["business"] = _metric_rows(
        row for row in rows if not row["isNonBusinessDay"]
    )
    result["regimes"]["nonBusiness"] = _metric_rows(
        row for row in rows if row["isNonBusinessDay"]
    )
    for name, start_hour, end_hour in TIME_BANDS:
        result["timeBands"][name] = _metric_rows(
            row for row in rows if start_hour <= row["hour"] <= end_hour
        )
    return result


def _target_weather_cache(cache: pd.DataFrame, target: date) -> pd.DataFrame:
    """Expose target-day weather while hiding target demand from inference."""
    cutoff = pd.Timestamp(target, tz=JST)
    target_end = cutoff + pd.Timedelta(days=1)
    result = cache[
        (cache["ts"] < cutoff)
        | ((cache["ts"] >= cutoff) & (cache["ts"] < target_end))
    ].copy()
    target_mask = (result["ts"] >= cutoff) & (result["ts"] < target_end)
    result.loc[target_mask, "actual_mw"] = np.nan
    if "actual_source" in result.columns:
        result.loc[target_mask, "actual_source"] = None
    return result


def _forecast_rows(
    cache: pd.DataFrame,
    validation_dates: list[date],
    forecaster: LGBMForecaster,
    config: dict,
) -> tuple[list[dict], list[dict]]:
    candidate_rows: list[dict] = []
    baseline_rows: list[dict] = []
    forecast_cfg = config.get("forecast", {})
    n_weeks = int(forecast_cfg.get("n_weeks", 12))
    min_samples = int(forecast_cfg.get("min_samples_per_slot", 4))

    observed = _deduplicated_observed(cache)
    for target in validation_dates:
        inference_cache = _target_weather_cache(cache, target)
        candidate = forecaster.predict(target, inference_cache)
        baseline = compute_forecast(
            cache[cache["ts"] < pd.Timestamp(target, tz=JST)],
            target,
            n_weeks,
            min_samples,
        )
        candidate_by_hour = {
            pd.Timestamp(point.ts).hour: float(point.forecast_mw)
            for point in candidate
        }
        baseline_by_hour = {
            pd.Timestamp(point.ts).hour: float(point.forecast_mw)
            for point in baseline
        }
        actual_rows = observed[observed["ts"].dt.date == target]
        is_non_business = _is_non_business_day(target)
        for _, row in actual_rows.iterrows():
            hour = int(row["ts"].hour)
            common = {
                "date": target,
                "hour": hour,
                "actual": float(row["actual_mw"]),
                "isNonBusinessDay": is_non_business,
            }
            if hour in candidate_by_hour:
                candidate_rows.append({
                    **common,
                    "predicted": candidate_by_hour[hour],
                })
            if hour in baseline_by_hour:
                baseline_rows.append({
                    **common,
                    "predicted": baseline_by_hour[hour],
                })
    return candidate_rows, baseline_rows


def _segment_passes(
    candidate: dict,
    baseline: dict,
    max_regression_ratio: float,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for section in ("regimes", "timeBands"):
        for name, candidate_metrics in candidate[section].items():
            baseline_metrics = baseline[section].get(name, {})
            candidate_mae = candidate_metrics.get("maeMw")
            baseline_mae = baseline_metrics.get("maeMw")
            candidate_hours = int(candidate_metrics.get("hours", 0))
            baseline_hours = int(baseline_metrics.get("hours", 0))
            if candidate_hours >= 24 and (
                candidate_mae is None
                or not np.isfinite(float(candidate_mae))
            ):
                failures.append(f"{section}.{name}.candidate_mae_invalid")
                continue
            if baseline_hours >= 24 and (
                baseline_mae is None
                or not np.isfinite(float(baseline_mae))
            ):
                failures.append(f"{section}.{name}.baseline_mae_invalid")
                continue
            if (
                candidate_hours < 24
                or baseline_hours < 24
                or candidate_mae is None
                or baseline_mae in (None, 0)
            ):
                continue
            if candidate_mae > baseline_mae * max_regression_ratio:
                failures.append(
                    f"{section}.{name}.mae_regression"
                )
    return not failures, failures


def _absolute_gate_failures(candidate: dict, promotion_config: dict) -> list[str]:
    failures: list[str] = []
    overall = candidate["overall"]
    limits = {
        "maeMw": (
            "max_validation_mae_mw",
            "overall.mae_above_absolute_limit",
        ),
        "wapePct": (
            "max_validation_wape_pct",
            "overall.wape_above_absolute_limit",
        ),
        "shapeDeltaMaeMw": (
            "max_validation_shape_delta_mae_mw",
            "overall.shape_error_above_absolute_limit",
        ),
        "maxErrorMw": (
            "max_validation_max_error_mw",
            "overall.max_error_above_absolute_limit",
        ),
    }
    for metric, (config_key, failure_name) in limits.items():
        value = overall.get(metric)
        limit = promotion_config.get(config_key)
        if limit is None:
            continue
        if value is None or not np.isfinite(float(value)):
            failures.append(f"overall.{metric}_invalid")
        elif value > float(limit):
            failures.append(failure_name)

    max_segment_mae = promotion_config.get("max_segment_mae_mw")
    max_segment_shape = promotion_config.get("max_segment_shape_delta_mae_mw")
    for section in ("regimes", "timeBands"):
        for name, metrics in candidate[section].items():
            if int(metrics.get("hours", 0)) < 24:
                continue
            mae = metrics.get("maeMw")
            if max_segment_mae is not None:
                if mae is None or not np.isfinite(float(mae)):
                    failures.append(f"{section}.{name}.mae_invalid")
                elif mae > float(max_segment_mae):
                    failures.append(f"{section}.{name}.mae_above_absolute_limit")
            shape = metrics.get("shapeDeltaMaeMw")
            if max_segment_shape is not None:
                if shape is None or not np.isfinite(float(shape)):
                    failures.append(f"{section}.{name}.shape_error_invalid")
                elif shape > float(max_segment_shape):
                    failures.append(
                        f"{section}.{name}.shape_error_above_absolute_limit"
                    )
    return failures


def build_temporal_validation_report(
    cache: pd.DataFrame,
    config: dict,
    *,
    window_days: int = 28,
    generated_at: str | None = None,
) -> dict:
    """Train before a rolling holdout and evaluate the current model contract."""
    normalized = cache.copy()
    normalized["ts"] = pd.to_datetime(normalized["ts"], utc=True).dt.tz_convert(
        "Asia/Tokyo"
    )
    normalized = (
        normalized.sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    complete_dates = _complete_dates(normalized)
    validation_dates = complete_dates[-max(1, int(window_days)):]
    if len(validation_dates) < 7:
        raise ValueError("Need at least 7 complete dates for temporal validation.")

    validation_start = validation_dates[0]
    train_cache = normalized[
        normalized["ts"] < pd.Timestamp(validation_start, tz=JST)
    ].copy()
    forecaster = LGBMForecaster(config=config)
    forecaster.fit(train_cache)
    candidate_rows, baseline_rows = _forecast_rows(
        normalized,
        validation_dates,
        forecaster,
        config,
    )
    candidate_metrics = _metric_bundle(candidate_rows)
    baseline_metrics = _metric_bundle(baseline_rows)
    expected_hours = len(validation_dates) * 24

    promotion_cfg = config.get("model_promotion", {})
    min_improvement_pct = float(
        promotion_cfg.get("min_mae_improvement_vs_baseline_pct", 5.0)
    )
    max_segment_regression_pct = float(
        promotion_cfg.get("max_segment_mae_regression_pct", 10.0)
    )
    candidate_mae = candidate_metrics["overall"]["maeMw"]
    baseline_mae = baseline_metrics["overall"]["maeMw"]
    improvement_pct = (
        (baseline_mae - candidate_mae) / baseline_mae * 100.0
        if candidate_mae is not None and baseline_mae not in (None, 0)
        else None
    )
    segment_ok, segment_failures = _segment_passes(
        candidate_metrics,
        baseline_metrics,
        1.0 + max_segment_regression_pct / 100.0,
    )
    failures = list(segment_failures)
    if int(candidate_metrics["overall"]["hours"]) != expected_hours:
        failures.append("candidate.incomplete_validation_coverage")
    if int(baseline_metrics["overall"]["hours"]) != expected_hours:
        failures.append("baseline.incomplete_validation_coverage")
    if improvement_pct is None or improvement_pct < min_improvement_pct:
        failures.append("overall.mae_improvement_below_threshold")
    failures.extend(_absolute_gate_failures(candidate_metrics, promotion_cfg))

    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at
        or pd.Timestamp.now(tz=JST).isoformat(timespec="seconds"),
        "methodology": {
            "type": "rolling_temporal_holdout",
            "weatherContext": "final_observed_weather",
            "demandLeakage": "target_day_actuals_removed",
            "windowDays": int(window_days),
            "expectedHours": expected_hours,
            "note": (
                "This validates the model contract before promotion. "
                "Operational serving behavior is evaluated separately."
            ),
        },
        "trainPeriod": {
            "start": str(train_cache["ts"].dt.date.min()),
            "end": str(train_cache["ts"].dt.date.max()),
            "rows": int(_observed_mask(train_cache).sum()),
        },
        "validationPeriod": {
            "start": validation_dates[0].isoformat(),
            "end": validation_dates[-1].isoformat(),
            "days": len(validation_dates),
        },
        "candidate": candidate_metrics,
        "baseline": baseline_metrics,
        "improvementPct": {
            "maeVsBaseline": round(float(improvement_pct), 2)
            if improvement_pct is not None
            else None,
        },
        "gate": {
            "passed": not failures and segment_ok,
            "failures": failures,
            "thresholds": {
                "minMaeImprovementVsBaselinePct": min_improvement_pct,
                "maxSegmentMaeRegressionPct": max_segment_regression_pct,
                "maxValidationMaeMw": promotion_cfg.get(
                    "max_validation_mae_mw"
                ),
                "maxValidationWapePct": promotion_cfg.get(
                    "max_validation_wape_pct"
                ),
                "maxValidationShapeDeltaMaeMw": promotion_cfg.get(
                    "max_validation_shape_delta_mae_mw"
                ),
                "maxValidationMaxErrorMw": promotion_cfg.get(
                    "max_validation_max_error_mw"
                ),
                "maxSegmentMaeMw": promotion_cfg.get("max_segment_mae_mw"),
                "maxSegmentShapeDeltaMaeMw": promotion_cfg.get(
                    "max_segment_shape_delta_mae_mw"
                ),
            },
        },
    }


def prediction_drift_report(
    champion: LGBMForecaster,
    challenger: LGBMForecaster,
    cache: pd.DataFrame,
    target_dates: Iterable[date],
    *,
    cache_by_date: Mapping[date, pd.DataFrame] | None = None,
) -> dict:
    deltas: list[dict] = []
    invalid: list[dict] = []
    targets = list(target_dates)
    for target in targets:
        target_cache = (
            cache_by_date.get(target, cache)
            if cache_by_date is not None
            else cache
        )
        champion_points = champion.predict(target, target_cache)
        challenger_points = challenger.predict(target, target_cache)
        champion_by_hour = {
            pd.Timestamp(point.ts).hour: float(point.forecast_mw)
            for point in champion_points
        }
        challenger_by_hour = {
            pd.Timestamp(point.ts).hour: float(point.forecast_mw)
            for point in challenger_points
        }
        for hour in range(24):
            champion_value = champion_by_hour.get(hour)
            challenger_value = challenger_by_hour.get(hour)
            if (
                champion_value is None
                or challenger_value is None
                or not np.isfinite(champion_value)
                or not np.isfinite(challenger_value)
            ):
                invalid.append({
                    "date": target.isoformat(),
                    "hour": hour,
                    "reason": "missing_or_nonfinite_prediction",
                })
                continue
            delta = challenger_value - champion_value
            if not np.isfinite(delta):
                invalid.append({
                    "date": target.isoformat(),
                    "hour": hour,
                    "reason": "nonfinite_delta",
                })
                continue
            deltas.append({
                "date": target.isoformat(),
                "hour": hour,
                "deltaMw": round(delta, 1),
            })
    absolute = np.asarray([abs(row["deltaMw"]) for row in deltas], dtype=float)
    expected_hours = len(targets) * 24
    valid = not invalid and len(deltas) == expected_hours
    return {
        "valid": valid,
        "expectedHours": expected_hours,
        "hours": len(deltas),
        "meanAbsDeltaMw": round(float(absolute.mean()), 1) if len(absolute) else None,
        "maxAbsDeltaMw": round(float(absolute.max()), 1) if len(absolute) else None,
        "invalidPredictionCount": len(invalid),
        "invalidPredictions": invalid[:10],
        "largestChanges": sorted(
            deltas,
            key=lambda row: abs(row["deltaMw"]),
            reverse=True,
        )[:5],
    }


def artifact_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config_fingerprint(config: dict) -> str:
    encoded = json.dumps(
        config,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
