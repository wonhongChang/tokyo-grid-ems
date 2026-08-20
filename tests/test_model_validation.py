"""Tests for temporal model validation and promotion safeguards."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from python.eval.model_validation import (
    _absolute_gate_failures,
    _complete_dates,
    _contract_comparison,
    _metric_rows,
    _recovery_gate,
    _segment_passes,
    config_fingerprint,
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


def test_complete_dates_counts_duplicate_timestamps_once():
    timestamps = list(pd.date_range(
        "2026-07-01T00:00:00+09:00",
        periods=24,
        freq="h",
    ))
    cache = pd.DataFrame({
        "ts": timestamps + [timestamps[0]],
        "actual_mw": [30_000.0] * 25,
        "actual_source": ["observed"] * 25,
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
    assert metrics["meanBiasMw"] == pytest.approx(7.5)
    assert metrics["rmseMw"] == pytest.approx(7.9)
    assert metrics["shapeDeltaMaeMw"] == pytest.approx(5.0)


def test_metric_rows_rejects_nonfinite_values():
    with pytest.raises(ValueError, match="finite"):
        _metric_rows([{
            "date": date(2026, 7, 1),
            "hour": 0,
            "actual": 100.0,
            "predicted": float("nan"),
        }])


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


def test_absolute_gate_rejects_nonfinite_metrics():
    candidate = {
        "overall": {
            "maeMw": float("nan"),
            "wapePct": 2.0,
            "shapeDeltaMaeMw": 500.0,
            "maxErrorMw": 2_000.0,
        },
        "regimes": {},
        "timeBands": {},
    }

    failures = _absolute_gate_failures(candidate, {
        "max_validation_mae_mw": 1_000,
        "max_validation_wape_pct": 3.0,
        "max_validation_shape_delta_mae_mw": 750,
        "max_validation_max_error_mw": 6_500,
    })

    assert "overall.maeMw_invalid" in failures


def _comparison_metrics(mae: float, wape: float, *, segment_mae: float) -> dict:
    return {
        "overall": {
            "hours": 672,
            "maeMw": mae,
            "wapePct": wape,
            "rmseMw": mae * 1.2,
            "maxErrorMw": 4_000.0,
            "shapeDeltaMaeMw": 600.0,
        },
        "regimes": {
            "business": {
                "hours": 480,
                "maeMw": segment_mae,
                "shapeDeltaMaeMw": 600.0,
            },
        },
        "timeBands": {
            "morning": {
                "hours": 140,
                "maeMw": segment_mae,
                "shapeDeltaMaeMw": 700.0,
            },
        },
    }


def test_contract_comparison_requires_material_champion_improvement():
    candidate = _comparison_metrics(900.0, 2.5, segment_mae=950.0)
    champion = _comparison_metrics(1_000.0, 2.8, segment_mae=1_000.0)

    comparison = _contract_comparison(candidate, champion, {
        "min_mae_improvement_vs_champion_pct": 5.0,
        "max_segment_regression_vs_champion_pct": 5.0,
    })

    assert comparison["gate"]["passed"] is True
    assert comparison["improvementPct"]["mae"] == pytest.approx(10.0)


def test_recovery_gate_rejects_candidate_that_improves_mae_but_not_wape():
    candidate = _comparison_metrics(850.0, 2.75, segment_mae=850.0)
    champion = _comparison_metrics(1_000.0, 2.8, segment_mae=1_000.0)

    gate = _recovery_gate(candidate, champion, {
        "recovery_min_improvement_pct": 10.0,
        "recovery_max_risk_regression_pct": 5.0,
        "recovery_min_weak_segment_improvement_pct": 10.0,
    })

    assert gate["passed"] is False
    assert "overall.wapePct_recovery_improvement_below_threshold" in gate["failures"]


def test_config_fingerprint_ignores_non_artifact_operating_settings():
    base = {
        "forecast": {"n_weeks": 12},
        "weather_features": {"cooling_base_temp_c": 22.0},
        "interval_calibration": {"min_p95_half_width_mw": 500},
        "forecast_snapshots": {"retention_days": 21},
    }
    changed = {
        **base,
        "forecast_snapshots": {"retention_days": 120},
        "model_promotion": {"validation_window_days": 84},
    }

    assert config_fingerprint(base) == config_fingerprint(changed)


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
    assert report["expectedHours"] == 24
    assert report["valid"] is True
    assert report["meanAbsDeltaMw"] == pytest.approx(250.0)
    assert report["maxAbsDeltaMw"] == pytest.approx(250.0)
    assert len(report["largestChanges"]) == 5


def test_prediction_drift_report_marks_nonfinite_prediction_invalid():
    class NonFiniteForecaster(_FakeForecaster):
        def predict(self, target: date, cache: pd.DataFrame):
            points = super().predict(target, cache)
            points[3] = HourlyForecast(
                ts=points[3].ts,
                forecast_mw=float("nan"),
                p95_lower_mw=29_000.0,
                p95_upper_mw=31_000.0,
                p99_lower_mw=28_000.0,
                p99_upper_mw=32_000.0,
            )
            return points

    report = prediction_drift_report(
        _FakeForecaster(0.0),
        NonFiniteForecaster(250.0),
        pd.DataFrame(),
        [date(2026, 7, 27)],
    )

    assert report["valid"] is False
    assert report["hours"] == 23
    assert report["invalidPredictionCount"] == 1
    assert report["invalidPredictions"][0]["hour"] == 3
