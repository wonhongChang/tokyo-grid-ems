"""Build daily operational forecast reports from published actual/forecast JSON."""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

TIMEZONE = "Asia/Tokyo"
_CLOSE_MAE_GAP_MW = 100.0
_CLOSE_WAPE_GAP_PCT = 0.2
_RMSE_RISK_GAP_MW = 300.0

_TIME_BANDS = [
    ("overnight", "00-05", 0, 5),
    ("morning_ramp", "06-10", 6, 10),
    ("daytime", "11-15", 11, 15),
    ("late_afternoon", "16-18", 16, 18),
    ("evening", "19-23", 19, 23),
]

_MORNING_TRANSITION_HOURS = set(range(6, 12))
_NON_BUSINESS_MIDDAY_SHAPE_HOURS = set(range(11, 16))

_INTERNAL_CALENDAR_FEATURES = [
    "hour",
    "dayofweek",
    "month",
    "is_holiday",
    "is_weekend",
    "is_non_business_day",
    "consec_holiday_len",
    "days_since_holiday_end",
]

_INTERNAL_LAG_FEATURES = [
    "lag_24h",
    "lag_48h",
    "lag_168h",
    "lag_336h",
    "lag_24h_hourly_delta",
    "lag_168h_hourly_delta",
    "lag_last_biz_hour",
    "lag_last_nonhol_hour",
    "recent_same_business_type_mean",
    "recent_same_business_type_delta_mean",
    "business_midday_x_lag_24h_delta",
    "business_midday_x_recent_delta_mean",
    "lag_24h_business_type_mismatch",
    "lag_24h_mismatch_x_business_hour",
    "lag_24h_to_last_biz_gap",
    "lag_24h_to_same_business_type_gap",
    "lag_24h_gap_x_business_hour",
]

_INTERNAL_WEATHER_FEATURES = [
    "temp_c",
    "apparent_temp_c",
    "cooling_degree",
    "heating_degree",
    "apparent_cooling_degree",
    "temp_anomaly_7d",
    "temp_anomaly_doy",
    "temp_delta_24h",
    "cooling_delta_24h",
    "temp_delta_168h",
    "cooling_delta_168h",
    "temp_delta_1h",
    "temp_delta_2h",
    "apparent_temp_delta_1h",
    "cooling_delta_1h",
    "cooling_degree_3h_mean",
    "cooling_degree_6h_mean",
    "heating_degree_3h_mean",
    "heating_degree_6h_mean",
    "temp_72h_mean",
    "cooling_degree_72h_mean",
    "heating_degree_72h_mean",
    "business_late_afternoon_x_temp_delta_1h",
    "business_late_afternoon_x_cooling_delta_1h",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _clean_number(value: Any, digits: int = 3) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    if number.is_integer():
        return int(number)
    return round(number, digits)


def _model_family(model_name: str) -> str:
    if model_name.endswith("_intraday_residual"):
        return model_name.removesuffix("_intraday_residual")
    return model_name


def _metrics(rows: list[dict], prefix: str) -> dict:
    abs_key = f"{prefix}AbsErrorMw"
    error_key = f"{prefix}ErrorMw"
    abs_errors = [float(row[abs_key]) for row in rows]
    signed_errors = [float(row[error_key]) for row in rows]
    actual_sum = sum(float(row["actualMw"]) for row in rows)
    if not abs_errors:
        return {
            "maeMw": None,
            "wapePct": None,
            "rmseMw": None,
            "maxErrorMw": None,
            "maxErrorHour": None,
        }

    max_error_row = max(rows, key=lambda row: float(row[abs_key]))
    return {
        "maeMw": _mean(abs_errors),
        "wapePct": round(sum(abs_errors) / actual_sum * 100, 2) if actual_sum > 0 else None,
        "rmseMw": round(math.sqrt(sum(error ** 2 for error in signed_errors) / len(signed_errors)), 1),
        "maxErrorMw": round(float(max_error_row[abs_key]), 1),
        "maxErrorHour": int(max_error_row["hour"]),
    }


def _verdict(
    model_mae_mw: float | None,
    tepco_mae_mw: float | None,
    model_wape_pct: float | None = None,
    tepco_wape_pct: float | None = None,
    model_rmse_mw: float | None = None,
    tepco_rmse_mw: float | None = None,
) -> str:
    if model_mae_mw is None or tepco_mae_mw is None:
        return "insufficient"
    gap_mw = model_mae_mw - tepco_mae_mw
    if model_wape_pct is None or tepco_wape_pct is None:
        if abs(gap_mw) <= 50.0:
            return "close"
        return "model_better" if gap_mw < 0 else "tepco_better"

    wape_gap_pct = model_wape_pct - tepco_wape_pct
    if abs(gap_mw) <= _CLOSE_MAE_GAP_MW and abs(wape_gap_pct) <= _CLOSE_WAPE_GAP_PCT:
        return "close"
    if gap_mw < 0 and wape_gap_pct < 0:
        if (
            model_rmse_mw is not None
            and tepco_rmse_mw is not None
            and model_rmse_mw - tepco_rmse_mw > _RMSE_RISK_GAP_MW
        ):
            return "mixed"
        return "model_better"
    if gap_mw > 0 and wape_gap_pct > 0:
        if (
            model_rmse_mw is not None
            and tepco_rmse_mw is not None
            and tepco_rmse_mw - model_rmse_mw > _RMSE_RISK_GAP_MW
        ):
            return "mixed"
        return "tepco_better"
    return "mixed"


def _win_counts(rows: list[dict]) -> tuple[int, int, int]:
    model_wins = sum(1 for row in rows if row["modelAbsErrorMw"] < row["tepcoAbsErrorMw"])
    tepco_wins = sum(1 for row in rows if row["tepcoAbsErrorMw"] < row["modelAbsErrorMw"])
    ties = len(rows) - model_wins - tepco_wins
    return model_wins, tepco_wins, ties


def _comparable_rows_for_date(public_dir: Path, date_iso: str) -> tuple[list[dict], str]:
    actual_path = public_dir / "actual" / f"{date_iso}.json"
    forecast_path = public_dir / "forecast" / f"{date_iso}.json"
    if not actual_path.exists() or not forecast_path.exists():
        return [], "unknown"

    actual = _load_json(actual_path)
    forecast = _load_json(forecast_path)
    model_name = forecast.get("model", {}).get("name") or "unknown"
    forecast_by_hour = {
        point["ts"][11:13]: point
        for point in forecast.get("series", [])
        if point.get("forecastMw") is not None
    }

    rows: list[dict] = []
    for actual_point in actual.get("series", []):
        if actual_point.get("actualSource") == "tepco_forecast_fallback":
            continue
        hour = actual_point.get("ts", "")[11:13]
        forecast_point = forecast_by_hour.get(hour)
        if forecast_point is None:
            continue

        actual_mw = actual_point.get("actualMw")
        tepco_forecast_mw = actual_point.get("tepcoForecastMw")
        model_forecast_mw = forecast_point.get("forecastMw")
        if actual_mw is None or tepco_forecast_mw is None or model_forecast_mw is None:
            continue

        actual_value = float(actual_mw)
        model_value = float(model_forecast_mw)
        tepco_value = float(tepco_forecast_mw)
        rows.append({
            "hour": int(hour),
            "actualMw": round(actual_value, 1),
            "modelForecastMw": round(model_value, 1),
            "tepcoForecastMw": round(tepco_value, 1),
            "modelErrorMw": round(model_value - actual_value, 1),
            "tepcoErrorMw": round(tepco_value - actual_value, 1),
            "modelAbsErrorMw": round(abs(model_value - actual_value), 1),
            "tepcoAbsErrorMw": round(abs(tepco_value - actual_value), 1),
        })
    return rows, model_name


def _peak_summary(rows: list[dict]) -> dict | None:
    if not rows:
        return None

    actual_peak = max(rows, key=lambda row: row["actualMw"])
    model_peak = max(rows, key=lambda row: row["modelForecastMw"])
    tepco_peak = max(rows, key=lambda row: row["tepcoForecastMw"])

    return {
        "actual": {
            "hour": actual_peak["hour"],
            "actualMw": actual_peak["actualMw"],
        },
        "model": {
            "hour": model_peak["hour"],
            "forecastMw": model_peak["modelForecastMw"],
            "errorAtActualPeakMw": round(
                actual_peak["modelForecastMw"] - actual_peak["actualMw"], 1
            ),
            "timeErrorHours": model_peak["hour"] - actual_peak["hour"],
        },
        "tepco": {
            "hour": tepco_peak["hour"],
            "forecastMw": tepco_peak["tepcoForecastMw"],
            "errorAtActualPeakMw": round(
                actual_peak["tepcoForecastMw"] - actual_peak["actualMw"], 1
            ),
            "timeErrorHours": tepco_peak["hour"] - actual_peak["hour"],
        },
    }


def _band_summary(rows: list[dict]) -> list[dict]:
    result = []
    for code, label, start_hour, end_hour in _TIME_BANDS:
        band_rows = [
            row for row in rows
            if start_hour <= row["hour"] <= end_hour
        ]
        if not band_rows:
            continue
        model_mae = _mean([row["modelAbsErrorMw"] for row in band_rows])
        tepco_mae = _mean([row["tepcoAbsErrorMw"] for row in band_rows])
        model_bias = _mean([row["modelErrorMw"] for row in band_rows])
        result.append({
            "code": code,
            "label": label,
            "hours": len(band_rows),
            "modelMaeMw": model_mae,
            "tepcoMaeMw": tepco_mae,
            "modelBiasMw": model_bias,
            "verdict": _verdict(model_mae, tepco_mae),
        })
    return result


def _shape_transitions(rows: list[dict]) -> list[dict]:
    result = []
    previous: dict | None = None
    for row in sorted(rows, key=lambda item: item["hour"]):
        if previous is None:
            previous = row
            continue
        if row["hour"] != previous["hour"] + 1:
            previous = row
            continue

        actual_delta = row["actualMw"] - previous["actualMw"]
        model_delta = row["modelForecastMw"] - previous["modelForecastMw"]
        tepco_delta = row["tepcoForecastMw"] - previous["tepcoForecastMw"]
        model_delta_error = model_delta - actual_delta
        tepco_delta_error = tepco_delta - actual_delta
        result.append({
            "fromHour": previous["hour"],
            "toHour": row["hour"],
            "actualDeltaMw": round(actual_delta, 1),
            "modelDeltaMw": round(model_delta, 1),
            "tepcoDeltaMw": round(tepco_delta, 1),
            "modelDeltaErrorMw": round(model_delta_error, 1),
            "tepcoDeltaErrorMw": round(tepco_delta_error, 1),
            "modelAbsDeltaErrorMw": round(abs(model_delta_error), 1),
            "tepcoAbsDeltaErrorMw": round(abs(tepco_delta_error), 1),
        })
        previous = row
    return result


def _shape_summary(rows: list[dict]) -> dict:
    transitions = _shape_transitions(rows)
    if not transitions:
        return {
            "transitionHours": 0,
            "largeShapeBreaks": [],
        }

    large_breaks = sorted(
        [
            transition for transition in transitions
            if transition["modelAbsDeltaErrorMw"] >= 1500.0
        ],
        key=lambda transition: transition["modelAbsDeltaErrorMw"],
        reverse=True,
    )[:5]

    return {
        "transitionHours": len(transitions),
        "modelDeltaMaeMw": _mean([
            transition["modelAbsDeltaErrorMw"] for transition in transitions
        ]),
        "tepcoDeltaMaeMw": _mean([
            transition["tepcoAbsDeltaErrorMw"] for transition in transitions
        ]),
        "maxActualRiseMw": max(transition["actualDeltaMw"] for transition in transitions),
        "maxActualDropMw": min(transition["actualDeltaMw"] for transition in transitions),
        "maxModelRiseMw": max(transition["modelDeltaMw"] for transition in transitions),
        "maxModelDropMw": min(transition["modelDeltaMw"] for transition in transitions),
        "largestDeltaMiss": max(
            transitions,
            key=lambda transition: transition["modelAbsDeltaErrorMw"],
        ),
        "largeShapeBreaks": large_breaks,
    }


def _add_insight(insights: list[dict], code: str, severity: str, title: str, evidence: dict) -> None:
    if any(insight["code"] == code for insight in insights):
        return
    insights.append({
        "code": code,
        "severity": severity,
        "title": title,
        "evidence": evidence,
    })


def _build_insights(
    summary: dict,
    peak: dict | None,
    bands: list[dict],
    top_misses: list[dict],
    shape: dict | None = None,
) -> list[dict]:
    insights: list[dict] = []

    if summary["verdict"] == "model_better":
        _add_insight(
            insights,
            "model_closer_overall",
            "info",
            "The model was closer than TEPCO overall.",
            {
                "maeGapMw": summary["maeGapMw"],
                "wapeGapPct": summary.get("wapeGapPct"),
            },
        )
    elif summary["verdict"] == "tepco_better":
        _add_insight(
            insights,
            "tepco_closer_overall",
            "warning",
            "TEPCO was closer overall.",
            {
                "maeGapMw": summary["maeGapMw"],
                "wapeGapPct": summary.get("wapeGapPct"),
            },
        )
    elif summary["verdict"] == "mixed":
        _add_insight(
            insights,
            "mixed_operational_assessment",
            "info",
            "Average error and large-error risk pointed in different directions.",
            {
                "maeGapMw": summary.get("maeGapMw"),
                "wapeGapPct": summary.get("wapeGapPct"),
                "modelRmseMw": summary.get("modelRmseMw"),
                "tepcoRmseMw": summary.get("tepcoRmseMw"),
            },
        )

    for band in bands:
        bias = band.get("modelBiasMw")
        if bias is None:
            continue
        if band["code"] == "morning_ramp" and bias <= -500.0:
            _add_insight(
                insights,
                "morning_ramp_underestimated",
                "warning",
                "Morning demand rose faster than the model expected.",
                {"band": band["label"], "modelBiasMw": bias},
            )
        if band["code"] == "morning_ramp" and bias >= 500.0:
            _add_insight(
                insights,
                "morning_ramp_overestimated",
                "info",
                "Morning demand was lower than the model expected.",
                {"band": band["label"], "modelBiasMw": bias},
            )
        if band["code"] == "late_afternoon" and bias <= -500.0:
            _add_insight(
                insights,
                "afternoon_plateau_underestimated",
                "warning",
                "Late afternoon demand stayed higher than the model expected.",
                {"band": band["label"], "modelBiasMw": bias},
            )
        if band["code"] == "daytime" and bias <= -700.0:
            _add_insight(
                insights,
                "daytime_level_underestimated",
                "warning",
                "Daytime demand level was underestimated.",
                {"band": band["label"], "modelBiasMw": bias},
            )

    if top_misses and top_misses[0]["modelAbsErrorMw"] >= 1200.0:
        _add_insight(
            insights,
            "large_single_hour_miss",
            "warning",
            "One or more hours had a large model error.",
            {
                "hour": top_misses[0]["hour"],
                "modelAbsErrorMw": top_misses[0]["modelAbsErrorMw"],
            },
        )

    if shape and shape.get("largeShapeBreaks"):
        largest_break = shape["largeShapeBreaks"][0]
        if largest_break["modelDeltaErrorMw"] <= -1500.0:
            _add_insight(
                insights,
                "sharp_model_drop_mismatch",
                "warning",
                "The model line dropped faster than actual demand.",
                {
                    "fromHour": largest_break["fromHour"],
                    "toHour": largest_break["toHour"],
                    "modelDeltaMw": largest_break["modelDeltaMw"],
                    "actualDeltaMw": largest_break["actualDeltaMw"],
                },
            )
        elif largest_break["modelDeltaErrorMw"] >= 1500.0:
            _add_insight(
                insights,
                "sharp_model_rise_mismatch",
                "warning",
                "The model line rose faster than actual demand.",
                {
                    "fromHour": largest_break["fromHour"],
                    "toHour": largest_break["toHour"],
                    "modelDeltaMw": largest_break["modelDeltaMw"],
                    "actualDeltaMw": largest_break["actualDeltaMw"],
                },
            )

    if peak:
        model_peak = peak["model"]
        if abs(model_peak["timeErrorHours"]) >= 2:
            _add_insight(
                insights,
                "peak_timing_miss",
                "warning",
                "The model peak occurred at a different hour than the actual peak.",
                {"timeErrorHours": model_peak["timeErrorHours"]},
            )
        if model_peak["errorAtActualPeakMw"] <= -800.0:
            _add_insight(
                insights,
                "peak_level_underestimated",
                "warning",
                "The actual peak level was higher than the model expected.",
                {"errorAtActualPeakMw": model_peak["errorAtActualPeakMw"]},
            )
        if model_peak["errorAtActualPeakMw"] >= 800.0:
            _add_insight(
                insights,
                "peak_level_overestimated",
                "info",
                "The actual peak level was lower than the model expected.",
                {"errorAtActualPeakMw": model_peak["errorAtActualPeakMw"]},
            )

    return insights[:5]


def build_daily_operation_report(
    public_dir: Path,
    date_iso: str,
    generated_at: str,
    min_hours: int = 20,
) -> dict:
    rows, model_name = _comparable_rows_for_date(public_dir, date_iso)
    model_family = _model_family(model_name)
    if len(rows) < min_hours:
        return {
            "schemaVersion": "1.0.0",
            "timezone": TIMEZONE,
            "generatedAt": generated_at,
            "date": date_iso,
            "availability": "insufficient",
            "model": {"name": model_name, "family": model_family},
            "summary": {"comparableHours": len(rows)},
            "insights": [],
        }

    model_advantage_hours, tepco_advantage_hours, equal_hours = _win_counts(rows)
    model_metrics = _metrics(rows, "model")
    tepco_metrics = _metrics(rows, "tepco")
    model_mae = model_metrics["maeMw"]
    tepco_mae = tepco_metrics["maeMw"]
    summary = {
        "comparableHours": len(rows),
        "modelMaeMw": model_mae,
        "tepcoMaeMw": tepco_mae,
        "modelWapePct": model_metrics["wapePct"],
        "tepcoWapePct": tepco_metrics["wapePct"],
        "modelRmseMw": model_metrics["rmseMw"],
        "tepcoRmseMw": tepco_metrics["rmseMw"],
        "modelMaxErrorMw": model_metrics["maxErrorMw"],
        "tepcoMaxErrorMw": tepco_metrics["maxErrorMw"],
        "modelMaxErrorHour": model_metrics["maxErrorHour"],
        "tepcoMaxErrorHour": tepco_metrics["maxErrorHour"],
        "maeGapMw": (
            round(model_mae - tepco_mae, 1)
            if model_mae is not None and tepco_mae is not None
            else None
        ),
        "wapeGapPct": (
            round(model_metrics["wapePct"] - tepco_metrics["wapePct"], 2)
            if model_metrics["wapePct"] is not None and tepco_metrics["wapePct"] is not None
            else None
        ),
        "verdict": _verdict(
            model_mae,
            tepco_mae,
            model_metrics["wapePct"],
            tepco_metrics["wapePct"],
            model_metrics["rmseMw"],
            tepco_metrics["rmseMw"],
        ),
        "modelWins": model_advantage_hours,
        "tepcoWins": tepco_advantage_hours,
        "ties": equal_hours,
        "modelAdvantageHours": model_advantage_hours,
        "tepcoAdvantageHours": tepco_advantage_hours,
        "equalHours": equal_hours,
        "modelAdvantageRate": round(model_advantage_hours / len(rows), 3) if rows else None,
    }
    peak = _peak_summary(rows)
    time_bands = _band_summary(rows)
    shape = _shape_summary(rows)
    top_misses = sorted(
        rows,
        key=lambda row: row["modelAbsErrorMw"],
        reverse=True,
    )[:3]
    insights = _build_insights(summary, peak, time_bands, top_misses, shape)

    return {
        "schemaVersion": "1.0.0",
        "timezone": TIMEZONE,
        "generatedAt": generated_at,
        "date": date_iso,
        "availability": "ok",
        "model": {"name": model_name, "family": model_family},
        "summary": summary,
        "peak": peak,
        "timeBands": time_bands,
        "shape": shape,
        "topMisses": top_misses,
        "insights": insights,
    }


def _index_summary(report: dict) -> dict:
    return {
        "date": report["date"],
        "availability": report["availability"],
        "model": report.get("model"),
        "summary": report.get("summary"),
        "insights": report.get("insights", [])[:3],
    }


def _report_cutoff_date(generated_at: str) -> date | None:
    try:
        return datetime.fromisoformat(generated_at).date()
    except ValueError:
        return None


def build_daily_operation_reports(
    public_dir: Path,
    generated_at: str,
    max_days: int = 14,
    min_hours: int = 20,
) -> tuple[dict, list[dict]]:
    actual_dir = public_dir / "actual"
    if not actual_dir.exists():
        dates: list[str] = []
    else:
        dates = sorted(path.stem for path in actual_dir.glob("*.json"))

    reports: list[dict] = []
    cutoff_date = _report_cutoff_date(generated_at)
    if cutoff_date is not None:
        dates = [
            date_iso for date_iso in dates
            if date.fromisoformat(date_iso) < cutoff_date
        ]

    for date_iso in dates[-max_days:]:
        report = build_daily_operation_report(
            public_dir,
            date_iso,
            generated_at,
            min_hours=min_hours,
        )
        if report["availability"] == "ok":
            reports.append(report)

    return {
        "schemaVersion": "1.0.0",
        "timezone": TIMEZONE,
        "generatedAt": generated_at,
        "availability": "ok" if reports else "not_yet_available",
        "latest": reports[-1] if reports else None,
        "reports": [_index_summary(report) for report in reports],
    }, reports


def _feature_rows_by_hour(
    cache,
    target_date: date,
    config: dict | None,
) -> tuple[dict[int, dict], str | None]:
    try:
        from python.forecast.feature_builder import build_inference_features
        feature_cache = cache.copy()
        if "ts" in feature_cache.columns and "actual_mw" in feature_cache.columns:
            target_mask = feature_cache["ts"].dt.date == target_date
            feature_cache.loc[target_mask, "actual_mw"] = float("nan")
        features = build_inference_features(
            feature_cache,
            target_date,
            config,
            include_context=True,
        )
    except Exception as e:
        return {}, str(e)

    return {
        int(row["hour"]): row.to_dict()
        for _, row in features.iterrows()
    }, None


def _pick_feature_group(feature_row: dict | None, columns: list[str]) -> dict:
    if not feature_row:
        return {}
    return {
        column: _clean_number(feature_row.get(column))
        for column in columns
        if column in feature_row
    }


def _internal_diagnostic_rows(rows: list[dict], feature_rows: dict[int, dict]) -> list[dict]:
    result = []
    for row in rows:
        feature_row = feature_rows.get(row["hour"])
        result.append({
            **row,
            "calendarFeatures": _pick_feature_group(feature_row, _INTERNAL_CALENDAR_FEATURES),
            "lagFeatures": _pick_feature_group(feature_row, _INTERNAL_LAG_FEATURES),
            "weatherFeatures": _pick_feature_group(feature_row, _INTERNAL_WEATHER_FEATURES),
        })
    return result


def _operational_calibration_rows_by_hour(public_dir: Path, date_iso: str) -> dict[int, dict]:
    path = public_dir / "reports" / "internal" / "operational-calibration" / f"{date_iso}.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}

    result = {}
    for row in payload.get("hourlyDiagnostics", []):
        hour = _clean_number(row.get("hour"), digits=0)
        if hour is None:
            continue
        result[int(hour)] = row
    return result


def _weather_source_category(source: Any) -> str | None:
    if source is None:
        return None
    text = str(source).upper()
    if not text:
        return None
    if any(token in text for token in ["AMEDAS", "OBSERVED", "ACTUAL"]):
        return "observed"
    if any(token in text for token in ["OPEN_METEO", "FORWARD_FILL", "SEASONAL", "FALLBACK"]):
        return "fallback"
    if "JMA" in text or "FORECAST" in text:
        return "forecast"
    return "unknown"


def _weather_context_by_hour(cache, target_date: date) -> dict[int, dict]:
    if cache is None or not hasattr(cache, "iterrows"):
        return {}

    result: dict[int, dict] = {}
    for _, row in cache.iterrows():
        ts = row.get("ts") if hasattr(row, "get") else None
        if ts is None or not hasattr(ts, "date") or ts.date() != target_date:
            continue
        hour = getattr(ts, "hour", None)
        if hour is None:
            continue
        source = row.get("weather_source") if hasattr(row, "get") else None
        result[int(hour)] = {
            "humidityPct": _clean_number(row.get("humidity_pct") if hasattr(row, "get") else None, 1),
            "discomfortIndex": _clean_number(row.get("discomfort_index") if hasattr(row, "get") else None, 1),
            "weatherSource": str(source) if source is not None else None,
            "weatherSourceConfidence": _weather_source_category(source),
        }
    return result


def _first_clean_number(*values: Any, digits: int = 1) -> int | float | None:
    for value in values:
        cleaned = _clean_number(value, digits=digits)
        if cleaned is not None:
            return cleaned
    return None


def _morning_cause_tags(entry: dict) -> list[str]:
    tags: list[str] = []
    model_error = entry.get("modelErrorMw")
    abs_model_error = abs(float(model_error)) if model_error is not None else 0.0
    lag_excess = entry.get("morningLagDeltaExcessMw")
    cooling_delta = entry.get("coolingDelta24hC")
    humidity = entry.get("humidityPct")
    discomfort = entry.get("discomfortIndex")
    mismatch = entry.get("lag24BusinessTypeMismatch")
    residual = entry.get("residualAdjustmentMw")
    pre_calibration = entry.get("preCalibrationForecastMw")
    post_calibration = entry.get("postCalibrationForecastMw")
    actual = entry.get("actualMw")
    published_gap = entry.get("publishedVsRecalculatedGapMw")

    if (
        model_error is not None
        and float(model_error) >= 500.0
        and lag_excess is not None
        and float(lag_excess) >= 800.0
        and cooling_delta is not None
        and float(cooling_delta) <= -1.0
    ):
        tags.append("lag-overheat/cooler-day")

    if (
        model_error is not None
        and float(model_error) <= -500.0
        and (
            (humidity is not None and float(humidity) >= 70.0)
            or (discomfort is not None and float(discomfort) >= 75.0)
        )
    ):
        tags.append("humidity-ramp")

    if mismatch is not None and float(mismatch) > 0 and abs_model_error >= 500.0:
        tags.append("business-return")

    if (
        residual is not None
        and abs(float(residual)) >= 300.0
        and pre_calibration is not None
        and post_calibration is not None
        and actual is not None
    ):
        pre_error = float(pre_calibration) - float(actual)
        post_error = float(post_calibration) - float(actual)
        if abs(post_error) >= abs(pre_error) + 300.0:
            tags.append("intraday-carryover")

    if published_gap is not None and abs(float(published_gap)) >= 500.0 and abs_model_error >= 500.0:
        tags.append("freeze")

    return tags


def _morning_transition_registry(
    diagnostic_rows: list[dict],
    calibration_rows: dict[int, dict],
    weather_context: dict[int, dict],
) -> dict:
    entries = []
    for row in diagnostic_rows:
        hour = int(row["hour"])
        if hour not in _MORNING_TRANSITION_HOURS:
            continue
        calibration_row = calibration_rows.get(hour, {})
        lag_features = row.get("lagFeatures", {})
        weather_features = row.get("weatherFeatures", {})
        cache_weather = weather_context.get(hour, {})
        stage_forecasts = calibration_row.get("forecastMwByStage", {})

        raw_forecast = _first_clean_number(stage_forecasts.get("raw_lgbm"), digits=1)
        pre_calibration = _first_clean_number(
            calibration_row.get("preCalibrationForecastMw"),
            stage_forecasts.get("pre_calibration"),
            digits=1,
        )
        post_calibration = _first_clean_number(
            calibration_row.get("postCalibrationForecastMw"),
            digits=1,
        )
        served_forecast = _clean_number(row.get("modelForecastMw"), digits=1)
        actual = _clean_number(row.get("actualMw"), digits=1)
        lag_delta = _first_clean_number(
            calibration_row.get("lag24DeltaMw"),
            lag_features.get("lag_24h_hourly_delta"),
            digits=1,
        )
        recent_delta = _first_clean_number(
            calibration_row.get("recentSameBusinessTypeDeltaMw"),
            lag_features.get("recent_same_business_type_delta_mean"),
            digits=1,
        )
        lag_delta_excess = None
        if lag_delta is not None and recent_delta is not None:
            lag_delta_excess = round(float(lag_delta) - float(recent_delta), 1)

        published_gap = None
        if served_forecast is not None and post_calibration is not None:
            published_gap = round(float(served_forecast) - float(post_calibration), 1)

        entry = {
            "hour": hour,
            "rawForecastMw": raw_forecast,
            "preCalibrationForecastMw": pre_calibration,
            "postCalibrationForecastMw": post_calibration,
            "servedForecastMw": served_forecast,
            "actualMw": actual,
            "modelErrorMw": _clean_number(row.get("modelErrorMw"), digits=1),
            "publishedVsRecalculatedGapMw": published_gap,
            "lag24HourlyDeltaMw": lag_delta,
            "recentSameBusinessTypeDeltaMeanMw": recent_delta,
            "morningLagDeltaExcessMw": lag_delta_excess,
            "lag24BusinessTypeMismatch": _clean_number(
                lag_features.get("lag_24h_business_type_mismatch"),
                digits=1,
            ),
            "tempC": _clean_number(weather_features.get("temp_c"), digits=1),
            "coolingDelta24hC": _clean_number(weather_features.get("cooling_delta_24h"), digits=1),
            "humidityPct": cache_weather.get("humidityPct"),
            "discomfortIndex": cache_weather.get("discomfortIndex"),
            "weatherSource": cache_weather.get("weatherSource"),
            "weatherSourceConfidence": cache_weather.get("weatherSourceConfidence"),
            "residualAdjustmentMw": _clean_number(
                calibration_row.get("residualAdjustmentMw"),
                digits=1,
            ),
        }
        entry["causeTags"] = _morning_cause_tags(entry)
        entries.append(entry)

    tag_counts: dict[str, int] = {}
    for entry in entries:
        for tag in entry["causeTags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    max_error_entry = None
    if entries:
        max_error_entry = max(
            entries,
            key=lambda entry: abs(float(entry["modelErrorMw"] or 0.0)),
        )

    lag_excess_values = [
        float(entry["morningLagDeltaExcessMw"])
        for entry in entries
        if entry.get("morningLagDeltaExcessMw") is not None
    ]
    cooling_delta_values = [
        float(entry["coolingDelta24hC"])
        for entry in entries
        if entry.get("coolingDelta24hC") is not None
    ]
    published_gap_values = [
        abs(float(entry["publishedVsRecalculatedGapMw"]))
        for entry in entries
        if entry.get("publishedVsRecalculatedGapMw") is not None
    ]

    return {
        "schemaVersion": "1.0.0",
        "hours": sorted(_MORNING_TRANSITION_HOURS),
        "summary": {
            "rows": len(entries),
            "modelMaeMw": _mean([
                abs(float(entry["modelErrorMw"]))
                for entry in entries
                if entry.get("modelErrorMw") is not None
            ]),
            "modelBiasMw": _mean([
                float(entry["modelErrorMw"])
                for entry in entries
                if entry.get("modelErrorMw") is not None
            ]),
            "maxErrorHour": max_error_entry["hour"] if max_error_entry else None,
            "maxAbsErrorMw": (
                abs(float(max_error_entry["modelErrorMw"]))
                if max_error_entry and max_error_entry.get("modelErrorMw") is not None
                else None
            ),
            "morningLagDeltaExcessMeanMw": _mean(lag_excess_values),
            "coolingDelta24hMeanC": _mean(cooling_delta_values),
            "publishedVsRecalculatedGapMaxAbsMw": (
                round(max(published_gap_values), 1)
                if published_gap_values
                else None
            ),
            "causeTagCounts": tag_counts,
        },
        "tagDefinitions": {
            "lag-overheat/cooler-day": (
                "lag_24h ramp exceeds recent same-business ramp while cooling load falls, "
                "and the served model overpredicts."
            ),
            "humidity-ramp": (
                "morning demand is underpredicted while humidity or discomfort is high enough "
                "to indicate early cooling demand."
            ),
            "business-return": (
                "today and lag_24h differ in business/non-business type, with a material "
                "morning error."
            ),
            "intraday-carryover": (
                "post-calibration residual carryover worsens the pre-calibration error."
            ),
            "freeze": (
                "served forecast differs materially from the latest recalculated post-calibration line."
            ),
        },
        "rows": entries,
    }


def _clean_delta(current: Any, previous: Any, digits: int = 1) -> int | float | None:
    current_number = _clean_number(current, digits=digits)
    previous_number = _clean_number(previous, digits=digits)
    if current_number is None or previous_number is None:
        return None
    return _clean_number(float(current_number) - float(previous_number), digits=digits)


def _non_business_midday_shape_tags(entry: dict) -> list[str]:
    tags: list[str] = []
    model_error = entry.get("modelErrorMw")
    abs_model_error = abs(float(model_error)) if model_error is not None else 0.0
    actual_delta = entry.get("actualDeltaMw")
    forecast_delta = entry.get("servedForecastDeltaMw")
    shape_delta_error = entry.get("modelShapeDeltaErrorMw")
    cooling_delta = entry.get("coolingDelta24hC")
    temp_anomaly = entry.get("tempAnomaly7dC")
    apparent_cooling = entry.get("apparentCoolingDegreeC")
    lag_delta = entry.get("lag24HourlyDeltaMw")
    recent_delta = entry.get("recentSameBusinessTypeDeltaMeanMw")
    published_gap = entry.get("publishedVsRecalculatedGapMw")

    cooling_context = (
        (cooling_delta is not None and float(cooling_delta) >= 1.0)
        or (temp_anomaly is not None and float(temp_anomaly) >= 2.0)
        or (apparent_cooling is not None and float(apparent_cooling) >= 5.0)
    )

    if (
        model_error is not None
        and float(model_error) <= -500.0
        and actual_delta is not None
        and float(actual_delta) >= 500.0
        and cooling_context
    ):
        tags.append("weekend-cooling-ramp-underpredicted")

    if (
        actual_delta is not None
        and float(actual_delta) >= 500.0
        and forecast_delta is not None
        and float(forecast_delta) <= -300.0
    ):
        tags.append("model-dropped-against-actual-rise")

    if (
        shape_delta_error is not None
        and float(shape_delta_error) <= -800.0
        and actual_delta is not None
        and float(actual_delta) >= 300.0
    ):
        tags.append("rebound-shape-underfit")

    if (
        lag_delta is not None
        and recent_delta is not None
        and actual_delta is not None
        and float(actual_delta) >= 500.0
        and float(lag_delta) <= 0.0
        and float(recent_delta) >= 0.0
    ):
        tags.append("lag-shape-conflict")

    if published_gap is not None and abs(float(published_gap)) >= 500.0 and abs_model_error >= 500.0:
        tags.append("freeze")

    return tags


def _stage_forecast_value(calibration_row: dict, stage: str) -> int | float | None:
    stage_forecasts = calibration_row.get("forecastMwByStage", {})
    if stage == "raw_lgbm":
        return _first_clean_number(stage_forecasts.get("raw_lgbm"), digits=1)
    if stage == "pre_calibration":
        return _first_clean_number(
            calibration_row.get("preCalibrationForecastMw"),
            stage_forecasts.get("pre_calibration"),
            digits=1,
        )
    if stage == "post_calibration":
        return _first_clean_number(
            calibration_row.get("postCalibrationForecastMw"),
            digits=1,
        )
    return None


def _non_business_midday_shape_registry(
    diagnostic_rows: list[dict],
    calibration_rows: dict[int, dict],
    weather_context: dict[int, dict],
) -> dict:
    entries = []
    rows_by_hour = {
        int(row["hour"]): row
        for row in diagnostic_rows
        if row.get("hour") is not None
    }
    for row in diagnostic_rows:
        hour = int(row["hour"])
        if hour not in _NON_BUSINESS_MIDDAY_SHAPE_HOURS:
            continue

        calendar_features = row.get("calendarFeatures", {})
        if _clean_number(calendar_features.get("is_non_business_day"), digits=0) != 1:
            continue

        previous_row = rows_by_hour.get(hour - 1)
        calibration_row = calibration_rows.get(hour, {})
        previous_calibration_row = calibration_rows.get(hour - 1, {})
        lag_features = row.get("lagFeatures", {})
        weather_features = row.get("weatherFeatures", {})
        cache_weather = weather_context.get(hour, {})

        raw_forecast = _stage_forecast_value(calibration_row, "raw_lgbm")
        pre_calibration = _stage_forecast_value(calibration_row, "pre_calibration")
        post_calibration = _stage_forecast_value(calibration_row, "post_calibration")
        served_forecast = _clean_number(row.get("modelForecastMw"), digits=1)
        actual = _clean_number(row.get("actualMw"), digits=1)

        served_delta = _clean_delta(
            served_forecast,
            previous_row.get("modelForecastMw") if previous_row else None,
            digits=1,
        )
        actual_delta = _clean_delta(
            actual,
            previous_row.get("actualMw") if previous_row else None,
            digits=1,
        )
        raw_delta = _clean_delta(
            raw_forecast,
            _stage_forecast_value(previous_calibration_row, "raw_lgbm"),
            digits=1,
        )
        pre_delta = _clean_delta(
            pre_calibration,
            _stage_forecast_value(previous_calibration_row, "pre_calibration"),
            digits=1,
        )
        post_delta = _clean_delta(
            post_calibration,
            _stage_forecast_value(previous_calibration_row, "post_calibration"),
            digits=1,
        )
        shape_delta_error = None
        if served_delta is not None and actual_delta is not None:
            shape_delta_error = round(float(served_delta) - float(actual_delta), 1)

        lag_delta = _first_clean_number(
            calibration_row.get("lag24DeltaMw"),
            lag_features.get("lag_24h_hourly_delta"),
            digits=1,
        )
        lag168_delta = _first_clean_number(
            calibration_row.get("lag168DeltaMw"),
            lag_features.get("lag_168h_hourly_delta"),
            digits=1,
        )
        recent_delta = _first_clean_number(
            calibration_row.get("recentSameBusinessTypeDeltaMw"),
            lag_features.get("recent_same_business_type_delta_mean"),
            digits=1,
        )
        lag_delta_excess = None
        if lag_delta is not None and recent_delta is not None:
            lag_delta_excess = round(float(lag_delta) - float(recent_delta), 1)

        published_gap = None
        if served_forecast is not None and post_calibration is not None:
            published_gap = round(float(served_forecast) - float(post_calibration), 1)

        entry = {
            "hour": hour,
            "rawForecastMw": raw_forecast,
            "preCalibrationForecastMw": pre_calibration,
            "postCalibrationForecastMw": post_calibration,
            "servedForecastMw": served_forecast,
            "actualMw": actual,
            "modelErrorMw": _clean_number(row.get("modelErrorMw"), digits=1),
            "publishedVsRecalculatedGapMw": published_gap,
            "rawForecastDeltaMw": raw_delta,
            "preCalibrationForecastDeltaMw": pre_delta,
            "postCalibrationForecastDeltaMw": post_delta,
            "servedForecastDeltaMw": served_delta,
            "actualDeltaMw": actual_delta,
            "modelShapeDeltaErrorMw": shape_delta_error,
            "lag24HourlyDeltaMw": lag_delta,
            "lag168HourlyDeltaMw": lag168_delta,
            "recentSameBusinessTypeDeltaMeanMw": recent_delta,
            "nonBusinessMiddayLagDeltaExcessMw": lag_delta_excess,
            "lag24BusinessTypeMismatch": _clean_number(
                lag_features.get("lag_24h_business_type_mismatch"),
                digits=1,
            ),
            "tempC": _clean_number(weather_features.get("temp_c"), digits=1),
            "apparentTempC": _clean_number(weather_features.get("apparent_temp_c"), digits=1),
            "tempDelta24hC": _clean_number(weather_features.get("temp_delta_24h"), digits=1),
            "coolingDelta24hC": _clean_number(weather_features.get("cooling_delta_24h"), digits=1),
            "tempAnomaly7dC": _clean_number(weather_features.get("temp_anomaly_7d"), digits=1),
            "apparentCoolingDegreeC": _clean_number(
                weather_features.get("apparent_cooling_degree"),
                digits=1,
            ),
            "tempDelta1hC": _clean_number(weather_features.get("temp_delta_1h"), digits=1),
            "apparentTempDelta1hC": _clean_number(
                weather_features.get("apparent_temp_delta_1h"),
                digits=1,
            ),
            "humidityPct": cache_weather.get("humidityPct"),
            "discomfortIndex": cache_weather.get("discomfortIndex"),
            "weatherSource": cache_weather.get("weatherSource"),
            "weatherSourceConfidence": cache_weather.get("weatherSourceConfidence"),
            "residualAdjustmentMw": _clean_number(
                calibration_row.get("residualAdjustmentMw"),
                digits=1,
            ),
        }
        entry["causeTags"] = _non_business_midday_shape_tags(entry)
        entries.append(entry)

    tag_counts: dict[str, int] = {}
    for entry in entries:
        for tag in entry["causeTags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    max_error_entry = None
    if entries:
        max_error_entry = max(
            entries,
            key=lambda entry: abs(float(entry["modelErrorMw"] or 0.0)),
        )
    shape_entries = [
        entry for entry in entries
        if entry.get("modelShapeDeltaErrorMw") is not None
    ]
    max_shape_entry = None
    if shape_entries:
        max_shape_entry = max(
            shape_entries,
            key=lambda entry: abs(float(entry["modelShapeDeltaErrorMw"] or 0.0)),
        )

    published_gap_values = [
        abs(float(entry["publishedVsRecalculatedGapMw"]))
        for entry in entries
        if entry.get("publishedVsRecalculatedGapMw") is not None
    ]
    cooling_delta_values = [
        float(entry["coolingDelta24hC"])
        for entry in entries
        if entry.get("coolingDelta24hC") is not None
    ]
    shape_delta_values = [
        float(entry["modelShapeDeltaErrorMw"])
        for entry in shape_entries
    ]

    return {
        "schemaVersion": "1.0.0",
        "hours": sorted(_NON_BUSINESS_MIDDAY_SHAPE_HOURS),
        "summary": {
            "rows": len(entries),
            "modelMaeMw": _mean([
                abs(float(entry["modelErrorMw"]))
                for entry in entries
                if entry.get("modelErrorMw") is not None
            ]),
            "modelBiasMw": _mean([
                float(entry["modelErrorMw"])
                for entry in entries
                if entry.get("modelErrorMw") is not None
            ]),
            "maxErrorHour": max_error_entry["hour"] if max_error_entry else None,
            "maxAbsErrorMw": (
                abs(float(max_error_entry["modelErrorMw"]))
                if max_error_entry and max_error_entry.get("modelErrorMw") is not None
                else None
            ),
            "maxShapeDeltaErrorHour": max_shape_entry["hour"] if max_shape_entry else None,
            "maxAbsShapeDeltaErrorMw": (
                abs(float(max_shape_entry["modelShapeDeltaErrorMw"]))
                if max_shape_entry and max_shape_entry.get("modelShapeDeltaErrorMw") is not None
                else None
            ),
            "shapeDeltaBiasMw": _mean(shape_delta_values),
            "coolingDelta24hMeanC": _mean(cooling_delta_values),
            "actualRiseModelDropHours": [
                entry["hour"]
                for entry in entries
                if entry.get("actualDeltaMw") is not None
                and entry.get("servedForecastDeltaMw") is not None
                and float(entry["actualDeltaMw"]) >= 500.0
                and float(entry["servedForecastDeltaMw"]) <= 0.0
            ],
            "publishedVsRecalculatedGapMaxAbsMw": (
                round(max(published_gap_values), 1)
                if published_gap_values
                else None
            ),
            "causeTagCounts": tag_counts,
        },
        "tagDefinitions": {
            "weekend-cooling-ramp-underpredicted": (
                "non-business midday demand rose under warm or cooling-load context, "
                "while the served model underpredicted materially."
            ),
            "model-dropped-against-actual-rise": (
                "served forecast fell from the previous hour while actual demand rose."
            ),
            "rebound-shape-underfit": (
                "served forecast hour-to-hour shape was materially below the actual shape."
            ),
            "lag-shape-conflict": (
                "lag_24h shape failed to support an observed non-business midday rebound."
            ),
            "freeze": (
                "served forecast differs materially from the latest recalculated post-calibration line."
            ),
        },
        "rows": entries,
    }


def _feature_band_means(rows: list[dict], group_name: str, feature_name: str) -> list[dict]:
    result = []
    for code, label, start_hour, end_hour in _TIME_BANDS:
        values = [
            row.get(group_name, {}).get(feature_name)
            for row in rows
            if start_hour <= row["hour"] <= end_hour
        ]
        numeric = [float(value) for value in values if value is not None]
        if not numeric:
            continue
        result.append({
            "code": code,
            "label": label,
            "mean": _mean(numeric),
        })
    return result


def _numeric_feature_values(rows: list[dict], group_name: str, feature_name: str) -> list[float]:
    values = [
        row.get(group_name, {}).get(feature_name)
        for row in rows
    ]
    return [float(value) for value in values if value is not None]


def _day_level_regime(rows: list[dict]) -> dict:
    """Summarize full-day lag/weather regime without imposing an hour-specific guard."""
    if not rows:
        return {
            "hours": 0,
            "flags": [],
        }

    lag_gap_values = _numeric_feature_values(
        rows,
        "lagFeatures",
        "lag_24h_to_same_business_type_gap",
    )
    temp_delta_values = _numeric_feature_values(
        rows,
        "weatherFeatures",
        "temp_delta_24h",
    )
    cooling_delta_values = _numeric_feature_values(
        rows,
        "weatherFeatures",
        "cooling_delta_24h",
    )
    temp_anomaly_values = _numeric_feature_values(
        rows,
        "weatherFeatures",
        "temp_anomaly_7d",
    )
    cooling_memory_values = _numeric_feature_values(
        rows,
        "weatherFeatures",
        "cooling_degree_72h_mean",
    )
    model_bias = _mean([row["modelErrorMw"] for row in rows])
    model_mae = _mean([row["modelAbsErrorMw"] for row in rows])

    lag_overheat_values = [
        max(0.0, -value)
        for value in lag_gap_values
    ]
    temp_drop_values = [
        max(0.0, -value)
        for value in temp_delta_values
    ]
    flags = []
    lag_overheat_mean = _mean(lag_overheat_values)
    temp_delta_mean = _mean(temp_delta_values)
    cooling_delta_mean = _mean(cooling_delta_values)
    temp_anomaly_mean = _mean(temp_anomaly_values)
    if lag_overheat_mean is not None and lag_overheat_mean >= 800.0:
        flags.append("lag24_above_recent_same_business_type")
    if temp_delta_mean is not None and temp_delta_mean <= -2.0:
        flags.append("cooler_than_previous_day")
    if cooling_delta_mean is not None and cooling_delta_mean <= -0.5:
        flags.append("lower_cooling_load_than_previous_day")
    if temp_anomaly_mean is not None and temp_anomaly_mean <= -2.0:
        flags.append("cooler_than_recent_week")
    if model_bias is not None and model_bias >= 500.0:
        flags.append("model_overpredicted")
    if model_bias is not None and model_bias <= -500.0:
        flags.append("model_underpredicted")
    if (
        "lag24_above_recent_same_business_type" in flags
        and "cooler_than_previous_day" in flags
    ):
        flags.append("cool_lag_overheat_regime")

    return {
        "hours": len(rows),
        "modelBiasMw": model_bias,
        "modelMaeMw": model_mae,
        "lag24ToSameBusinessTypeGapMeanMw": _mean(lag_gap_values),
        "lag24OverheatMeanMw": lag_overheat_mean,
        "lag24OverheatHours": sum(1 for value in lag_overheat_values if value >= 500.0),
        "tempDelta24hMeanC": temp_delta_mean,
        "tempDrop24hMeanC": _mean(temp_drop_values),
        "coolingDelta24hMeanC": cooling_delta_mean,
        "tempAnomaly7dMeanC": temp_anomaly_mean,
        "coolingDegree72hMeanC": _mean(cooling_memory_values),
        "flags": flags,
    }


def _weather_delta_risk_by_band(rows: list[dict]) -> list[dict]:
    result = []
    for code, label, start_hour, end_hour in _TIME_BANDS:
        band_rows = [
            row for row in rows
            if start_hour <= row["hour"] <= end_hour
        ]
        cooling_values = [
            row.get("weatherFeatures", {}).get("cooling_delta_24h")
            for row in band_rows
        ]
        temp_values = [
            row.get("weatherFeatures", {}).get("temp_delta_24h")
            for row in band_rows
        ]
        cooling_numeric = [float(value) for value in cooling_values if value is not None]
        temp_numeric = [float(value) for value in temp_values if value is not None]
        if not cooling_numeric and not temp_numeric:
            continue

        model_bias = _mean([row["modelErrorMw"] for row in band_rows])
        model_mae = _mean([row["modelAbsErrorMw"] for row in band_rows])
        cooling_mean = _mean(cooling_numeric)
        temp_mean = _mean(temp_numeric)
        assessment = "neutral"
        if cooling_mean is not None and model_bias is not None:
            if cooling_mean >= 1.0 and model_bias <= -500.0:
                assessment = "warming_underpredicted"
            elif cooling_mean >= 1.0 and model_bias >= 500.0:
                assessment = "warming_overweighted"
            elif cooling_mean <= -1.0 and model_bias <= -500.0:
                assessment = "cooling_drop_underweighted"
            elif cooling_mean <= -1.0 and model_bias >= 500.0:
                assessment = "cooling_drop_overweighted"

        result.append({
            "code": code,
            "label": label,
            "hours": len(band_rows),
            "tempDelta24hMean": temp_mean,
            "coolingDelta24hMean": cooling_mean,
            "modelBiasMw": model_bias,
            "modelMaeMw": model_mae,
            "assessment": assessment,
        })
    return result


def _morning_transition_index_summary(diagnostics: list[dict]) -> dict:
    tag_counts: dict[str, int] = {}
    report_summaries = []
    for diagnostic in diagnostics:
        morning = diagnostic.get("morningTransitionDiagnostics") or {}
        summary = morning.get("summary") or {}
        for tag, count in (summary.get("causeTagCounts") or {}).items():
            tag_counts[tag] = tag_counts.get(tag, 0) + int(count)
        report_summaries.append({
            "date": diagnostic.get("date"),
            "rows": summary.get("rows"),
            "modelMaeMw": summary.get("modelMaeMw"),
            "modelBiasMw": summary.get("modelBiasMw"),
            "maxErrorHour": summary.get("maxErrorHour"),
            "maxAbsErrorMw": summary.get("maxAbsErrorMw"),
            "causeTagCounts": summary.get("causeTagCounts", {}),
        })

    return {
        "windowDays": len(diagnostics),
        "hours": sorted(_MORNING_TRANSITION_HOURS),
        "causeTagCounts": tag_counts,
        "reports": report_summaries,
    }


def _non_business_midday_shape_index_summary(diagnostics: list[dict]) -> dict:
    tag_counts: dict[str, int] = {}
    report_summaries = []
    for diagnostic in diagnostics:
        registry = diagnostic.get("nonBusinessMiddayShapeDiagnostics") or {}
        summary = registry.get("summary") or {}
        for tag, count in (summary.get("causeTagCounts") or {}).items():
            tag_counts[tag] = tag_counts.get(tag, 0) + int(count)
        report_summaries.append({
            "date": diagnostic.get("date"),
            "rows": summary.get("rows"),
            "modelMaeMw": summary.get("modelMaeMw"),
            "modelBiasMw": summary.get("modelBiasMw"),
            "maxErrorHour": summary.get("maxErrorHour"),
            "maxAbsErrorMw": summary.get("maxAbsErrorMw"),
            "maxShapeDeltaErrorHour": summary.get("maxShapeDeltaErrorHour"),
            "maxAbsShapeDeltaErrorMw": summary.get("maxAbsShapeDeltaErrorMw"),
            "actualRiseModelDropHours": summary.get("actualRiseModelDropHours", []),
            "causeTagCounts": summary.get("causeTagCounts", {}),
        })

    return {
        "windowDays": len(diagnostics),
        "hours": sorted(_NON_BUSINESS_MIDDAY_SHAPE_HOURS),
        "causeTagCounts": tag_counts,
        "reports": report_summaries,
    }


def build_internal_daily_diagnostic(
    public_dir: Path,
    date_iso: str,
    generated_at: str,
    cache,
    config: dict | None = None,
    min_hours: int = 20,
) -> dict:
    rows, model_name = _comparable_rows_for_date(public_dir, date_iso)
    model_family = _model_family(model_name)
    target_date = date.fromisoformat(date_iso)
    feature_rows, feature_error = _feature_rows_by_hour(cache, target_date, config)
    diagnostic_rows = _internal_diagnostic_rows(rows, feature_rows)
    calibration_rows = _operational_calibration_rows_by_hour(public_dir, date_iso)
    weather_context = _weather_context_by_hour(cache, target_date)
    morning_transition = _morning_transition_registry(
        diagnostic_rows,
        calibration_rows,
        weather_context,
    )
    non_business_midday_shape = _non_business_midday_shape_registry(
        diagnostic_rows,
        calibration_rows,
        weather_context,
    )
    public_report = build_daily_operation_report(
        public_dir,
        date_iso,
        generated_at,
        min_hours=min_hours,
    )

    return {
        "schemaVersion": "1.0.0",
        "timezone": TIMEZONE,
        "generatedAt": generated_at,
        "date": date_iso,
        "availability": "ok" if len(rows) >= min_hours else "insufficient",
        "visibility": {
            "intendedUse": "internal_model_diagnostics",
            "containsInternalFeatureNames": True,
            "uiVisible": False,
            "storedWithOperationalOutputs": True,
        },
        "model": {"name": model_name, "family": model_family},
        "operationReport": public_report,
        "featureBuildError": feature_error,
        "diagnosticSummary": {
            "lag24ToSameBusinessTypeGapByBand": _feature_band_means(
                diagnostic_rows,
                "lagFeatures",
                "lag_24h_to_same_business_type_gap",
            ),
            "lag24HourlyDeltaByBand": _feature_band_means(
                diagnostic_rows,
                "lagFeatures",
                "lag_24h_hourly_delta",
            ),
            "recentSameBusinessTypeDeltaByBand": _feature_band_means(
                diagnostic_rows,
                "lagFeatures",
                "recent_same_business_type_delta_mean",
            ),
            "tempAnomaly7dByBand": _feature_band_means(
                diagnostic_rows,
                "weatherFeatures",
                "temp_anomaly_7d",
            ),
            "tempDelta24hByBand": _feature_band_means(
                diagnostic_rows,
                "weatherFeatures",
                "temp_delta_24h",
            ),
            "coolingDelta24hByBand": _feature_band_means(
                diagnostic_rows,
                "weatherFeatures",
                "cooling_delta_24h",
            ),
            "coolingDegree3hMeanByBand": _feature_band_means(
                diagnostic_rows,
                "weatherFeatures",
                "cooling_degree_3h_mean",
            ),
            "dayLevelRegime": _day_level_regime(diagnostic_rows),
            "weatherDeltaRiskByBand": _weather_delta_risk_by_band(diagnostic_rows),
            "morningTransition": morning_transition.get("summary"),
            "nonBusinessMiddayShape": non_business_midday_shape.get("summary"),
        },
        "morningTransitionDiagnostics": morning_transition,
        "nonBusinessMiddayShapeDiagnostics": non_business_midday_shape,
        "rows": diagnostic_rows,
    }


def build_internal_daily_diagnostics(
    public_dir: Path,
    generated_at: str,
    cache,
    config: dict | None = None,
    max_days: int = 14,
    min_hours: int = 20,
) -> tuple[dict, list[dict]]:
    actual_dir = public_dir / "actual"
    if not actual_dir.exists():
        dates: list[str] = []
    else:
        dates = sorted(path.stem for path in actual_dir.glob("*.json"))

    cutoff_date = _report_cutoff_date(generated_at)
    if cutoff_date is not None:
        dates = [
            date_iso for date_iso in dates
            if date.fromisoformat(date_iso) < cutoff_date
        ]

    diagnostics = [
        build_internal_daily_diagnostic(
            public_dir,
            date_iso,
            generated_at,
            cache,
            config=config,
            min_hours=min_hours,
        )
        for date_iso in dates[-max_days:]
    ]
    diagnostics = [
        diagnostic for diagnostic in diagnostics
        if diagnostic["availability"] == "ok"
    ]
    morning_transition_summary = _morning_transition_index_summary(diagnostics)
    non_business_midday_shape_summary = _non_business_midday_shape_index_summary(diagnostics)

    return {
        "schemaVersion": "1.0.0",
        "timezone": TIMEZONE,
        "generatedAt": generated_at,
        "availability": "ok" if diagnostics else "not_yet_available",
        "visibility": {
            "intendedUse": "internal_model_diagnostics",
            "containsInternalFeatureNames": True,
            "uiVisible": False,
            "storedWithOperationalOutputs": True,
        },
        "latest": {
            "date": diagnostics[-1]["date"],
            "model": diagnostics[-1]["model"],
            "operationSummary": diagnostics[-1]["operationReport"].get("summary"),
            "morningTransition": (
                diagnostics[-1]
                .get("morningTransitionDiagnostics", {})
                .get("summary")
            ),
            "nonBusinessMiddayShape": (
                diagnostics[-1]
                .get("nonBusinessMiddayShapeDiagnostics", {})
                .get("summary")
            ),
        } if diagnostics else None,
        "morningTransition": morning_transition_summary,
        "nonBusinessMiddayShape": non_business_midday_shape_summary,
        "reports": [
            {
                "date": diagnostic["date"],
                "model": diagnostic["model"],
                "availability": diagnostic["availability"],
                "operationSummary": diagnostic["operationReport"].get("summary"),
                "morningTransition": (
                    diagnostic
                    .get("morningTransitionDiagnostics", {})
                    .get("summary")
                ),
                "nonBusinessMiddayShape": (
                    diagnostic
                    .get("nonBusinessMiddayShapeDiagnostics", {})
                    .get("summary")
                ),
                "featureBuildError": diagnostic.get("featureBuildError"),
            }
            for diagnostic in diagnostics
        ],
    }, diagnostics
