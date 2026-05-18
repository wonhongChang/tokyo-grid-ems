"""Tests for daily operational forecast reports."""
from __future__ import annotations

import json
from pathlib import Path

from python.eval.daily_operation_report import (
    build_daily_operation_report,
    build_daily_operation_reports,
)


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
    assert report["summary"]["modelMaeMw"] > report["summary"]["tepcoMaeMw"]
    assert report["summary"]["verdict"] == "tepco_better"
    assert report["model"]["family"] == "lgbm_quantile_q50"
    assert report["topMisses"][0]["modelAbsErrorMw"] == 1300.0
    insight_codes = {insight["code"] for insight in report["insights"]}
    assert "morning_ramp_underestimated" in insight_codes
    assert "afternoon_plateau_underestimated" in insight_codes


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
