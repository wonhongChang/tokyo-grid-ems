"""Tests for temporal model validation and promotion safeguards."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from python.eval.model_validation import (
    _absolute_gate_failures,
    _complete_dates,
    _metric_rows,
    _segment_passes,
    prediction_drift_report,
)
from python.forecast.baseline import HourlyForecast


def test_complete_dates_excludes_forecast_fallback_actuals():
    timestamps = pd.date_range(
        "2026-07-01T00:00:00+09:00",
        periods=48,
        freq="h",
    )
    cache = pd.DataFrame({
        "ts": timestamps,
        "actual_mw": [30_000.0] * 48,
        "actual_source": ["observed"] * 24
        + ["tepco_forecast_fallback"] * 24,
    })

    assert _complete_dates(cache) == [date(2026, 7, 1)]


def test_metric_rows_reports_level_and_shape_errors():
    rows = [
        {
            "date": date(2026, 7, 1),
            "hour": 0,
            "actual": 100.0,
            "predicted": 110.0,
        },
        {
            "date": date(2026, 7, 1),
            "hour": 1,
            "actual": 120.0,
            "predicted": 125.0,
        },
    ]

    metrics = _metric_rows(rows)

    assert metrics["maeMw"] == pytest.approx(7.5)
    assert metrics["rmseMw"] == pytest.approx(7.9)
    assert metrics["shapeDeltaMaeMw"] == pytest.approx(5.0)


def test_segment_gate_rejects_large_time_band_regression():
    candidate = {
        "regimes": {
            "business": {"hours": 48, "maeMw": 100.0},
        },
        "timeBands": {
            "morning": {"hours": 28, "maeMw": 130.0},
        },
    }
    baseline = {
        "regimes": {
            "business": {"hours": 48, "maeMw": 100.0},
        },
        "timeBands": {
            "morning": {"hours": 28, "maeMw": 100.0},
        },
    }

    passed, failures = _segment_passes(candidate, baseline, 1.10)

    assert not passed
    assert failures == ["timeBands.morning.mae_regression"]


def test_absolute_gate_rejects_bad_overall_and_segment_metrics():
    candidate = {
        "overall": {
            "maeMw": 1_100.0,
            "wapePct": 3.2,
            "shapeDeltaMaeMw": 700.0,
            "maxErrorMw": 6_000.0,
        },
        "regimes": {
            "business": {
                "hours": 48,
                "maeMw": 900.0,
                "shapeDeltaMaeMw": 600.0,
            },
        },
        "timeBands": {
            "morning": {
                "hours": 28,
                "maeMw": 1_600.0,
                "shapeDeltaMaeMw": 1_200.0,
            },
        },
    }
    failures = _absolute_gate_failures(candidate, {
        "max_validation_mae_mw": 1_000,
        "max_validation_wape_pct": 3.0,
        "max_validation_shape_delta_mae_mw": 750,
        "max_validation_max_error_mw": 6_500,
        "max_segment_mae_mw": 1_500,
        "max_segment_shape_delta_mae_mw": 1_100,
    })

    assert "overall.mae_above_absolute_limit" in failures
    assert "overall.wape_above_absolute_limit" in failures
    assert "timeBands.morning.mae_above_absolute_limit" in failures
    assert "timeBands.morning.shape_error_above_absolute_limit" in failures


class _FakeForecaster:
    def __init__(self, offset: float):
        self.offset = offset

    def predict(self, target: date, cache: pd.DataFrame):
        del cache
        base = pd.Timestamp(target, tz="Asia/Tokyo")
        return [
            HourlyForecast(
                ts=(base + pd.Timedelta(hours=hour)).to_pydatetime(),
                forecast_mw=30_000.0 + hour + self.offset,
                p95_lower_mw=29_000.0,
                p95_upper_mw=31_000.0,
                p99_lower_mw=28_000.0,
                p99_upper_mw=32_000.0,
            )
            for hour in range(24)
        ]


def test_prediction_drift_report_quantifies_challenger_change():
    report = prediction_drift_report(
        _FakeForecaster(0.0),
        _FakeForecaster(250.0),
        pd.DataFrame(),
        [date(2026, 7, 27)],
    )

    assert report["hours"] == 24
    assert report["meanAbsDeltaMw"] == pytest.approx(250.0)
    assert report["maxAbsDeltaMw"] == pytest.approx(250.0)
    assert len(report["largestChanges"]) == 5
