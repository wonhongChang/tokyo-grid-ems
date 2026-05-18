"""Build daily operational forecast reports from published actual/forecast JSON."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

TIMEZONE = "Asia/Tokyo"

_TIME_BANDS = [
    ("overnight", "00-05", 0, 5),
    ("morning_ramp", "06-10", 6, 10),
    ("daytime", "11-15", 11, 15),
    ("late_afternoon", "16-18", 16, 18),
    ("evening", "19-23", 19, 23),
]

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
    "lag_last_biz_hour",
    "lag_last_nonhol_hour",
    "recent_same_business_type_mean",
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


def _verdict(model_mae_mw: float | None, tepco_mae_mw: float | None) -> str:
    if model_mae_mw is None or tepco_mae_mw is None:
        return "insufficient"
    gap_mw = model_mae_mw - tepco_mae_mw
    if abs(gap_mw) <= 50.0:
        return "close"
    return "model_better" if gap_mw < 0 else "tepco_better"


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


def _add_insight(insights: list[dict], code: str, severity: str, title: str, evidence: dict) -> None:
    if any(insight["code"] == code for insight in insights):
        return
    insights.append({
        "code": code,
        "severity": severity,
        "title": title,
        "evidence": evidence,
    })


def _build_insights(summary: dict, peak: dict | None, bands: list[dict], top_misses: list[dict]) -> list[dict]:
    insights: list[dict] = []

    if summary["verdict"] == "model_better":
        _add_insight(
            insights,
            "model_closer_overall",
            "info",
            "The model was closer than TEPCO overall.",
            {"maeGapMw": summary["maeGapMw"]},
        )
    elif summary["verdict"] == "tepco_better":
        _add_insight(
            insights,
            "tepco_closer_overall",
            "warning",
            "TEPCO was closer overall.",
            {"maeGapMw": summary["maeGapMw"]},
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

    model_wins, tepco_wins, ties = _win_counts(rows)
    model_mae = _mean([row["modelAbsErrorMw"] for row in rows])
    tepco_mae = _mean([row["tepcoAbsErrorMw"] for row in rows])
    summary = {
        "comparableHours": len(rows),
        "modelMaeMw": model_mae,
        "tepcoMaeMw": tepco_mae,
        "maeGapMw": (
            round(model_mae - tepco_mae, 1)
            if model_mae is not None and tepco_mae is not None
            else None
        ),
        "verdict": _verdict(model_mae, tepco_mae),
        "modelWins": model_wins,
        "tepcoWins": tepco_wins,
        "ties": ties,
    }
    peak = _peak_summary(rows)
    time_bands = _band_summary(rows)
    top_misses = sorted(
        rows,
        key=lambda row: row["modelAbsErrorMw"],
        reverse=True,
    )[:3]
    insights = _build_insights(summary, peak, time_bands, top_misses)

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
        features = build_inference_features(feature_cache, target_date, config)
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
        },
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
        } if diagnostics else None,
        "reports": [
            {
                "date": diagnostic["date"],
                "model": diagnostic["model"],
                "availability": diagnostic["availability"],
                "operationSummary": diagnostic["operationReport"].get("summary"),
                "featureBuildError": diagnostic.get("featureBuildError"),
            }
            for diagnostic in diagnostics
        ],
    }, diagnostics
