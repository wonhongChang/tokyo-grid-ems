"""Tests for daily operational forecast reports."""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from python.eval.daily_operation_report import (
    build_daily_operation_report,
    build_daily_operation_reports,
    build_internal_daily_diagnostic,
    build_internal_daily_diagnostics,
)

JST = ZoneInfo("Asia/Tokyo")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_day(tmp_path: Path, date_iso: str, model_values: list[float], actual_values: list[float]) -> None:
    _write_json(tmp_path / "actual" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "actualMw": actual_values[hour],
                "tepcoForecastMw": actual_values[hour] + (100 if hour < 12 else -100),
                "usagePct": 85.0,
                "supplyMw": 40_000.0,
            }
            for hour in range(24)
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "model": {"name": "lgbm_quantile_q50_intraday_residual"},
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "forecastMw": model_values[hour],
            }
            for hour in range(24)
        ],
    })


def _make_feature_cache(start: str = "2026-04-01", days: int = 49) -> pd.DataFrame:
    timestamps = pd.date_range(pd.Timestamp(start, tz=JST), periods=days * 24, freq="h")
    return pd.DataFrame({
        "ts": timestamps,
        "actual_mw": [
            25_000.0 + ts.hour * 100 + (2_000.0 if ts.weekday() < 5 else -2_000.0)
            for ts in timestamps
        ],
        "forecast_mw": [
            25_000.0 + ts.hour * 100
            for ts in timestamps
        ],
        "usage_pct": [80.0] * len(timestamps),
        "supply_mw": [40_000.0] * len(timestamps),
        "temp_c": [
            18.0 + ts.hour * 0.3
            for ts in timestamps
        ],
        "apparent_temp_c": [
            18.5 + ts.hour * 0.3
            for ts in timestamps
        ],
    })


def test_daily_operation_report_summarizes_previous_day_accuracy(tmp_path):
    date_iso = "2026-05-18"
    actual_values = [20_000.0 + hour * 100 for hour in range(24)]
    model_values = actual_values.copy()
    for hour in range(6, 11):
        model_values[hour] -= 900.0
    for hour in range(16, 19):
        model_values[hour] -= 1300.0

    _write_day(tmp_path, date_iso, model_values, actual_values)

    report = build_daily_operation_report(
        tmp_path,
        date_iso,
        generated_at="2026-05-19T08:20:00+09:00",
    )

    assert report["availability"] == "ok"
    assert report["date"] == date_iso
    assert report["summary"]["comparableHours"] == 24
    assert report["summary"]["tepcoMaeMw"] == 100.0
    assert report["summary"]["tepcoWapePct"] == 0.47
    assert report["summary"]["tepcoRmseMw"] == 100.0
    assert report["summary"]["tepcoMaxErrorMw"] == 100.0
    assert report["summary"]["modelMaeMw"] > report["summary"]["tepcoMaeMw"]
    assert report["summary"]["modelMaeMw"] == 350.0
    assert report["summary"]["modelWapePct"] == 1.65
    assert report["summary"]["modelRmseMw"] == 616.4
    assert report["summary"]["modelMaxErrorMw"] == 1300.0
    assert report["summary"]["modelMaxErrorHour"] == 16
    assert report["summary"]["verdict"] == "tepco_better"
    assert report["summary"]["modelAdvantageHours"] == 16
    assert report["summary"]["tepcoAdvantageHours"] == 8
    assert report["model"]["family"] == "lgbm_quantile_q50"
    assert report["topMisses"][0]["modelAbsErrorMw"] == 1300.0
    assert report["shape"]["transitionHours"] == 23
    insight_codes = {insight["code"] for insight in report["insights"]}
    assert "morning_ramp_underestimated" in insight_codes
    assert "afternoon_plateau_underestimated" in insight_codes


def test_daily_operation_report_flags_implausible_shape_drop(tmp_path):
    date_iso = "2026-05-18"
    actual_values = [30_000.0 for _ in range(24)]
    actual_values[16] = 29_900.0
    model_values = actual_values.copy()
    model_values[15] = 31_000.0
    model_values[16] = 27_000.0

    _write_day(tmp_path, date_iso, model_values, actual_values)

    report = build_daily_operation_report(
        tmp_path,
        date_iso,
        generated_at="2026-05-19T08:20:00+09:00",
    )

    shape = report["shape"]
    assert shape["maxModelDropMw"] == pytest.approx(-4_000.0)
    assert shape["largeShapeBreaks"][0]["fromHour"] == 15
    assert shape["largeShapeBreaks"][0]["toHour"] == 16
    insight_codes = {insight["code"] for insight in report["insights"]}
    assert "sharp_model_drop_mismatch" in insight_codes


def test_daily_operation_report_skips_tepco_fallback_actuals(tmp_path):
    date_iso = "2026-05-18"
    _write_json(tmp_path / "actual" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "actualMw": 20_000.0,
                "actualSource": "tepco_forecast_fallback",
                "tepcoForecastMw": 20_000.0,
            }
            for hour in range(24)
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "forecastMw": 20_000.0,
            }
            for hour in range(24)
        ],
    })

    report = build_daily_operation_report(tmp_path, date_iso, generated_at="now")

    assert report["availability"] == "insufficient"
    assert report["summary"]["comparableHours"] == 0


def test_daily_operation_report_index_uses_latest_available_report(tmp_path):
    actual_values = [20_000.0 + hour * 100 for hour in range(24)]
    _write_day(tmp_path, "2026-05-17", actual_values, actual_values)
    _write_day(tmp_path, "2026-05-18", actual_values, actual_values)

    index, reports = build_daily_operation_reports(
        tmp_path,
        generated_at="2026-05-19T08:20:00+09:00",
    )

    assert index["availability"] == "ok"
    assert index["latest"]["date"] == "2026-05-18"
    assert [report["date"] for report in reports] == ["2026-05-17", "2026-05-18"]


def test_daily_operation_report_index_excludes_generation_day(tmp_path):
    actual_values = [20_000.0 + hour * 100 for hour in range(24)]
    _write_day(tmp_path, "2026-05-18", actual_values, actual_values)
    _write_day(tmp_path, "2026-05-19", actual_values, actual_values)

    index, reports = build_daily_operation_reports(
        tmp_path,
        generated_at="2026-05-19T08:20:00+09:00",
    )

    assert index["latest"]["date"] == "2026-05-18"
    assert [report["date"] for report in reports] == ["2026-05-18"]


def test_internal_daily_diagnostic_includes_lag_and_weather_features(tmp_path):
    date_iso = "2026-05-18"
    actual_values = [27_000.0 + hour * 100 for hour in range(24)]
    model_values = [value - 500.0 for value in actual_values]
    _write_day(tmp_path, date_iso, model_values, actual_values)

    diagnostic = build_internal_daily_diagnostic(
        tmp_path,
        date_iso,
        generated_at="2026-05-19T08:20:00+09:00",
        cache=_make_feature_cache(),
        config={},
    )

    assert diagnostic["availability"] == "ok"
    assert diagnostic["visibility"]["containsInternalFeatureNames"] is True
    assert diagnostic["visibility"]["uiVisible"] is False
    assert diagnostic["visibility"]["storedWithOperationalOutputs"] is True
    assert diagnostic["featureBuildError"] is None
    first_row = diagnostic["rows"][0]
    assert "lag_24h" in first_row["lagFeatures"]
    assert "lag_24h_hourly_delta" in first_row["lagFeatures"]
    assert "lag_24h_to_same_business_type_gap" in first_row["lagFeatures"]
    assert "business_midday_x_lag_24h_delta" in first_row["lagFeatures"]
    assert "temp_delta_24h" in first_row["weatherFeatures"]
    assert "temp_72h_mean" in first_row["weatherFeatures"]
    summary = diagnostic["diagnosticSummary"]
    assert summary["lag24HourlyDeltaByBand"]
    assert summary["recentSameBusinessTypeDeltaByBand"]
    assert summary["coolingDelta24hByBand"]
    assert summary["coolingDegree3hMeanByBand"]
    assert summary["dayLevelRegime"]["hours"] == 24
    assert "lag24OverheatMeanMw" in summary["dayLevelRegime"]
    assert "tempDelta24hMeanC" in summary["dayLevelRegime"]
    assert "flags" in summary["dayLevelRegime"]
    assert summary["weatherDeltaRiskByBand"]
    assert summary["morningTransition"]["rows"] == 6
    assert "morningTransitionDiagnostics" in diagnostic


def test_internal_daily_diagnostic_builds_morning_transition_registry(tmp_path):
    date_iso = "2026-05-18"
    actual_values = [30_000.0 + hour * 100 for hour in range(24)]
    model_values = actual_values.copy()
    model_values[10] = actual_values[10] + 1_500.0
    _write_day(tmp_path, date_iso, model_values, actual_values)
    _write_json(
        tmp_path
        / "reports"
        / "internal"
        / "operational-calibration"
        / f"{date_iso}.json",
        {
            "date": date_iso,
            "hourlyDiagnostics": [
                {
                    "hour": 10,
                    "forecastMwByStage": {
                        "raw_lgbm": actual_values[10] + 900.0,
                        "pre_calibration": actual_values[10],
                    },
                    "preCalibrationForecastMw": actual_values[10],
                    "postCalibrationForecastMw": actual_values[10] - 500.0,
                    "lag24DeltaMw": 2_400.0,
                    "recentSameBusinessTypeDeltaMw": 700.0,
                    "residualAdjustmentMw": -500.0,
                }
            ],
        },
    )
    cache = _make_feature_cache()
    target_mask = cache["ts"].dt.strftime("%Y-%m-%dT%H") == f"{date_iso}T10"
    cache.loc[target_mask, "humidity_pct"] = 78.0
    cache.loc[target_mask, "discomfort_index"] = 76.5
    cache.loc[target_mask, "weather_source"] = "AMEDAS_ACTUAL"

    diagnostic = build_internal_daily_diagnostic(
        tmp_path,
        date_iso,
        generated_at="2026-05-19T08:20:00+09:00",
        cache=cache,
        config={},
    )

    registry = diagnostic["morningTransitionDiagnostics"]
    hour_10 = next(row for row in registry["rows"] if row["hour"] == 10)
    assert hour_10["rawForecastMw"] == pytest.approx(actual_values[10] + 900.0)
    assert hour_10["preCalibrationForecastMw"] == pytest.approx(actual_values[10])
    assert hour_10["postCalibrationForecastMw"] == pytest.approx(actual_values[10] - 500.0)
    assert hour_10["servedForecastMw"] == pytest.approx(actual_values[10] + 1_500.0)
    assert hour_10["publishedVsRecalculatedGapMw"] == pytest.approx(2_000.0)
    assert hour_10["morningLagDeltaExcessMw"] == pytest.approx(1_700.0)
    assert hour_10["humidityPct"] == pytest.approx(78.0)
    assert hour_10["discomfortIndex"] == pytest.approx(76.5)
    assert hour_10["weatherSourceConfidence"] == "observed"
    assert "intraday-carryover" in hour_10["causeTags"]
    assert "freeze" in hour_10["causeTags"]
    assert registry["summary"]["causeTagCounts"]["freeze"] == 1


def test_internal_daily_diagnostics_index_points_to_latest_report(tmp_path):
    actual_values = [20_000.0 + hour * 100 for hour in range(24)]
    _write_day(tmp_path, "2026-05-17", actual_values, actual_values)
    _write_day(tmp_path, "2026-05-18", actual_values, actual_values)

    index, diagnostics = build_internal_daily_diagnostics(
        tmp_path,
        generated_at="2026-05-19T08:20:00+09:00",
        cache=_make_feature_cache(),
        config={},
    )

    assert index["availability"] == "ok"
    assert index["visibility"]["uiVisible"] is False
    assert index["visibility"]["storedWithOperationalOutputs"] is True
    assert index["latest"]["date"] == "2026-05-18"
    assert index["latest"]["morningTransition"]["rows"] == 6
    assert index["morningTransition"]["windowDays"] == 2
    assert index["morningTransition"]["hours"] == [6, 7, 8, 9, 10, 11]
    assert [diagnostic["date"] for diagnostic in diagnostics] == ["2026-05-17", "2026-05-18"]
