from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from python.eval.fixed_origin_model_replay import (
    _baseline_config,
    _gate,
    _interval_metrics,
    _origin_inference_cache,
    _paired_daily_mae_bootstrap,
)


def _metrics(mae: float, rmse: float, max_error: float) -> dict:
    row = {
        "hours": 24,
        "maeMw": mae,
        "meanBiasMw": 0.0,
        "wapePct": 3.0,
        "rmseMw": rmse,
        "maxErrorMw": max_error,
        "shapeDeltaMaeMw": 500.0,
    }
    return {
        "overall": deepcopy(row),
        "regimes": {
            "business": deepcopy(row),
            "nonBusiness": deepcopy(row),
        },
        "timeBands": {
            "overnight": deepcopy(row),
            "morning": deepcopy(row),
            "daytime": deepcopy(row),
            "late_afternoon": deepcopy(row),
            "evening": deepcopy(row),
        },
    }


def _intervals(p95: float = 80.0, p99: float = 96.0) -> dict:
    return {
        "hours": 24,
        "p95CoveragePct": p95,
        "p99CoveragePct": p99,
        "meanP95WidthMw": 3000.0,
        "meanP99WidthMw": 6000.0,
    }


def _holdout_gate(baseline: dict, candidate: dict, candidate_intervals=None):
    return _gate(
        baseline,
        candidate,
        _intervals(),
        candidate_intervals or _intervals(),
        phase="holdout",
        min_holdout_improvement_pct=8.0,
        balanced_min_mae_improvement_pct=7.0,
        balanced_min_rmse_improvement_pct=8.0,
        balanced_min_max_error_improvement_pct=10.0,
        balanced_max_segment_regression_pct=1.0,
        conservative_min_mae_improvement_pct=5.0,
        conservative_min_rmse_improvement_pct=5.0,
        conservative_min_max_error_improvement_pct=5.0,
        conservative_min_shape_improvement_pct=2.0,
        conservative_max_segment_regression_pct=0.0,
        paired_daily_mae={
            "valid": True,
            "maeRatioCi95Upper": 0.99,
        },
    )


def test_baseline_config_disables_candidate_only_models():
    config = {
        "forecast": {
            "q50_feature_view_ensemble": {"enabled": True},
            "q50_regime_model": {"enabled": True},
            "daily_level_model": {"enabled": True},
            "partial_lag_q50_fallback": {
                "enabled": True,
                "lag_unavailable_models_enabled": True,
            },
        }
    }

    baseline = _baseline_config(config)

    forecast = baseline["forecast"]
    assert forecast["q50_feature_view_ensemble"]["enabled"] is False
    assert forecast["q50_regime_model"]["enabled"] is False
    assert forecast["daily_level_model"]["enabled"] is False
    assert (
        forecast["partial_lag_q50_fallback"][
            "lag_unavailable_models_enabled"
        ]
        is False
    )
    assert (
        config["forecast"]["partial_lag_q50_fallback"][
            "lag_unavailable_models_enabled"
        ]
        is True
    )


def test_origin_cache_removes_actuals_after_capture_knowledge_cutoff():
    timestamps = pd.date_range(
        "2026-06-30T00:00:00+09:00",
        periods=27,
        freq="h",
    )
    cache = pd.DataFrame({
        "ts": timestamps,
        "actual_mw": np.arange(len(timestamps), dtype=float),
        "actual_source": "observed",
    })

    result = _origin_inference_cache(
        cache,
        target=pd.Timestamp("2026-07-01").date(),
        captured_at="2026-06-30T01:13:17+09:00",
    )

    assert result.loc[0, "actual_mw"] == 0.0
    assert result.loc[1:, "actual_mw"].isna().all()
    assert result.loc[1:, "actual_source"].isna().all()


def test_balanced_recovery_accepts_small_noncritical_segment_noise():
    baseline = _metrics(100.0, 200.0, 1000.0)
    candidate = _metrics(92.5, 180.0, 880.0)
    candidate["timeBands"]["evening"]["maeMw"] = 100.7

    gate = _holdout_gate(baseline, candidate)

    assert gate["passed"] is True
    assert gate["mode"] == "balanced_risk_recovery"
    assert gate["holdoutSegmentRegressions"] == []


def test_balanced_recovery_rejects_material_segment_regression():
    baseline = _metrics(100.0, 200.0, 1000.0)
    candidate = _metrics(92.5, 180.0, 880.0)
    candidate["timeBands"]["evening"]["maeMw"] = 101.1

    gate = _holdout_gate(baseline, candidate)

    assert gate["passed"] is False
    assert gate["mode"] == "failed_recovery"
    assert gate["holdoutSegmentRegressions"] == ["timeBands.evening"]


def test_conservative_recovery_accepts_broad_non_regression():
    baseline = _metrics(100.0, 200.0, 1000.0)
    candidate = _metrics(94.5, 188.0, 940.0)
    candidate["overall"]["shapeDeltaMaeMw"] = 480.0
    for section in ("regimes", "timeBands"):
        for metrics in candidate[section].values():
            metrics["maeMw"] = 99.0

    gate = _holdout_gate(baseline, candidate)

    assert gate["passed"] is True
    assert gate["mode"] == "conservative_broad_recovery"
    assert gate["conservativeSegmentRegressions"] == []


def test_conservative_recovery_rejects_any_segment_regression():
    baseline = _metrics(100.0, 200.0, 1000.0)
    candidate = _metrics(94.5, 188.0, 940.0)
    candidate["overall"]["shapeDeltaMaeMw"] = 480.0
    candidate["timeBands"]["evening"]["maeMw"] = 100.1

    gate = _holdout_gate(baseline, candidate)

    assert gate["passed"] is False
    assert gate["mode"] == "failed_recovery"
    assert gate["conservativeSegmentRegressions"] == ["timeBands.evening"]


def test_recovery_rejects_material_interval_coverage_regression():
    baseline = _metrics(100.0, 200.0, 1000.0)
    candidate = _metrics(90.0, 175.0, 850.0)

    gate = _holdout_gate(
        baseline,
        candidate,
        candidate_intervals=_intervals(p95=77.9, p99=94.9),
    )

    assert gate["passed"] is False
    assert "p95_coverage_regressed" in gate["failures"]
    assert "p99_coverage_regressed" in gate["failures"]


def test_recovery_rejects_unconfirmed_paired_daily_improvement():
    baseline = _metrics(100.0, 200.0, 1000.0)
    candidate = _metrics(90.0, 175.0, 850.0)

    gate = _gate(
        baseline,
        candidate,
        _intervals(),
        _intervals(),
        phase="holdout",
        min_holdout_improvement_pct=8.0,
        balanced_min_mae_improvement_pct=7.0,
        balanced_min_rmse_improvement_pct=8.0,
        balanced_min_max_error_improvement_pct=10.0,
        balanced_max_segment_regression_pct=1.0,
        conservative_min_mae_improvement_pct=5.0,
        conservative_min_rmse_improvement_pct=5.0,
        conservative_min_max_error_improvement_pct=5.0,
        conservative_min_shape_improvement_pct=2.0,
        conservative_max_segment_regression_pct=0.0,
        paired_daily_mae={
            "valid": True,
            "maeRatioCi95Upper": 1.01,
        },
    )

    assert gate["passed"] is False
    assert "paired_daily_mae_ci_does_not_confirm_improvement" in gate["failures"]


def test_interval_metrics_reports_coverage_and_width():
    rows = [
        {
            "actual": 100.0,
            "p95Lower": 90.0,
            "p95Upper": 110.0,
            "p99Lower": 80.0,
            "p99Upper": 120.0,
        },
        {
            "actual": 130.0,
            "p95Lower": 90.0,
            "p95Upper": 110.0,
            "p99Lower": 80.0,
            "p99Upper": 120.0,
        },
    ]

    metrics = _interval_metrics(rows)

    assert metrics == {
        "hours": 2,
        "p95CoveragePct": 50.0,
        "p99CoveragePct": 50.0,
        "meanP95WidthMw": 20.0,
        "meanP99WidthMw": 40.0,
    }


def test_paired_daily_mae_bootstrap_is_deterministic_and_paired():
    baseline_rows = []
    candidate_rows = []
    for day in range(10):
        for hour in range(24):
            actual = 100.0
            baseline_rows.append({
                "date": day,
                "hour": hour,
                "actual": actual,
                "predicted": 110.0,
            })
            candidate_rows.append({
                "date": day,
                "hour": hour,
                "actual": actual,
                "predicted": 108.0,
            })

    result = _paired_daily_mae_bootstrap(
        baseline_rows,
        candidate_rows,
        iterations=1000,
        seed=7,
    )

    assert result["valid"] is True
    assert result["candidateBetterDays"] == 10
    assert result["maeRatio"] == 0.8
    assert result["maeRatioCi95Upper"] == 0.8
