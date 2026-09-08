from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from python.forecast.baseline import HourlyForecast
from python.forecast.same_regime_calibration import SameRegimeDayLevelCalibrator


def _config() -> dict:
    return {
        "forecast": {
            "model_contract": "v14-r2-source-robust-ensemble",
            "same_regime_day_level_calibration": {
                "enabled": True,
                "min_history_days": 3,
                "history_window_days": 3,
                "shrinkage": 0.25,
                "max_abs_adjustment_mw": 1000,
                "state_path": "metrics/day-level.json",
            },
        }
    }


def _forecast() -> list[HourlyForecast]:
    return [
        HourlyForecast(
            ts=f"2026-01-08T{hour:02d}:00:00+09:00",
            forecast_mw=30_000.0,
            p95_lower_mw=29_000.0,
            p95_upper_mw=31_000.0,
            p99_lower_mw=28_000.0,
            p99_upper_mw=32_000.0,
        )
        for hour in range(24)
    ]


def _write_state(tmp_path, *, artifact_hash: str = "candidate") -> None:
    (tmp_path / ".lgbm_model_meta.json").write_text(
        json.dumps({"artifactSha256": "candidate"}),
        encoding="utf-8",
    )
    path = tmp_path / "metrics" / "day-level.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({
            "modelContract": "v14-r2-source-robust-ensemble",
            "artifactSha256": artifact_hash,
            "validFromDate": "2026-01-01",
            "entries": [
                {"date": "2026-01-05", "isNonBusinessDay": False, "meanResidualMw": 400},
                {"date": "2026-01-06", "isNonBusinessDay": False, "meanResidualMw": 800},
                {"date": "2026-01-07", "isNonBusinessDay": False, "meanResidualMw": 1200},
                {"date": "2026-01-04", "isNonBusinessDay": True, "meanResidualMw": -900},
            ],
        }),
        encoding="utf-8",
    )
    state = json.loads(path.read_text(encoding="utf-8"))
    for entry in state["entries"]:
        entry["source"] = "immutable_day_ahead_origin"
        entry["originGeneratedAt"] = f"{date.fromisoformat(entry['date']) - timedelta(days=1)}T00:20:00+09:00"
    path.write_text(json.dumps(state), encoding="utf-8")


def test_same_regime_calibration_uses_three_day_median(tmp_path):
    _write_state(tmp_path)
    calibrator = SameRegimeDayLevelCalibrator(_config(), tmp_path)

    result = calibrator.apply(
        _forecast(),
        date(2026, 1, 8),
        pd.DataFrame({"is_non_business_day": [0.0]}),
    )

    assert result.applied is True
    assert result.adjustment_mw == 200.0
    assert result.history_dates == (
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
    )
    assert result.forecasts[0].forecast_mw == 30_200.0
    assert result.forecasts[0].p95_lower_mw == 29_200.0
    assert result.forecasts[0].p99_upper_mw == 32_200.0


def test_same_regime_calibration_does_not_mix_business_types(tmp_path):
    _write_state(tmp_path)
    calibrator = SameRegimeDayLevelCalibrator(_config(), tmp_path)

    result = calibrator.apply(
        _forecast(),
        date(2026, 1, 11),
        pd.DataFrame({"is_non_business_day": [1.0]}),
    )

    assert result.applied is False
    assert result.adjustment_mw == 0.0


def test_same_regime_calibration_rejects_another_artifact_state(tmp_path):
    _write_state(tmp_path, artifact_hash="old-model")
    calibrator = SameRegimeDayLevelCalibrator(_config(), tmp_path)

    result = calibrator.apply(
        _forecast(),
        date(2026, 1, 8),
        pd.DataFrame({"is_non_business_day": [0.0]}),
    )

    assert result.applied is False
    assert result.forecasts[0].forecast_mw == 30_000.0


def test_same_regime_calibration_refreshes_from_canonical_origin_series(tmp_path):
    (tmp_path / ".etl_state.json").write_text(
        json.dumps({"okDates": ["2026-01-07"]}), encoding="utf-8",
    )
    (tmp_path / ".lgbm_model_meta.json").write_text(
        json.dumps({"artifactSha256": "candidate"}),
        encoding="utf-8",
    )
    state_path = tmp_path / "metrics" / "day-level.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({
            "modelContract": "v14-r2-source-robust-ensemble",
            "artifactSha256": "candidate",
            "validFromDate": "2026-01-07",
            "entries": [],
        }),
        encoding="utf-8",
    )
    actual_path = tmp_path / "actual" / "2026-01-07.json"
    actual_path.parent.mkdir()
    actual_path.write_text(
        json.dumps({
            "series": [
                {
                    "ts": f"2026-01-07T{hour:02d}:00:00+09:00",
                    "actualMw": 31_000.0,
                    "actualSource": "observed",
                }
                for hour in range(24)
            ],
        }),
        encoding="utf-8",
    )
    origin_path = (
        tmp_path
        / "forecast_origins"
        / "2026-01-07"
        / "candidate.json"
    )
    origin_path.parent.mkdir(parents=True)
    origin_path.write_text(
        json.dumps({
            "generatedAt": "2026-01-06T20:00:00+09:00",
            "model": {
                "contract": "v14-r2-source-robust-ensemble",
                "artifactSha256": "candidate",
            },
            "forecastBuild": {
                "series": [
                    {
                        "hour": hour,
                        "forecastMwByStage": {"raw_lgbm": 30_000.0},
                    }
                    for hour in range(24)
                ],
            },
        }),
        encoding="utf-8",
    )

    calibrator = SameRegimeDayLevelCalibrator(_config(), tmp_path)
    state = calibrator.refresh(date(2026, 1, 8))

    assert state is not None
    assert state["latestResidualDate"] == "2026-01-07"
    assert state["entries"] == [{
        "date": "2026-01-07",
        "isNonBusinessDay": False,
        "meanResidualMw": 1000.0,
        "originGeneratedAt": "2026-01-06T20:00:00+09:00",
        "source": "immutable_day_ahead_origin",
    }]


def test_same_regime_calibration_fails_closed_for_stale_state(tmp_path):
    _write_state(tmp_path)
    calibrator = SameRegimeDayLevelCalibrator(_config(), tmp_path)

    result = calibrator.apply(
        _forecast(),
        date(2026, 1, 20),
        pd.DataFrame({"is_non_business_day": [0.0]}),
    )

    assert result.applied is False
    assert result.adjustment_mw == 0.0
    assert result.state_status == "stale_state"
    assert result.latest_residual_date == "2026-01-07"
    assert result.state_lag_days == 13


def test_same_regime_calibration_uses_serving_freshness_policy(tmp_path):
    _write_state(tmp_path)
    config = _config()
    config["serving_calibration"] = {
        "same_regime_day_level": {"max_state_lag_days": 1},
    }
    calibrator = SameRegimeDayLevelCalibrator(config, tmp_path)

    result = calibrator.apply(
        _forecast(),
        date(2026, 1, 9),
        pd.DataFrame({"is_non_business_day": [0.0]}),
    )

    assert result.applied is False
    assert result.state_status == "stale_state"
    assert result.state_lag_days == 2


def _replace_entries(tmp_path, values):
    path = tmp_path / "metrics/day-level.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["entries"] = [{
        "date": day, "isNonBusinessDay": non_business, "meanResidualMw": residual,
        "originGeneratedAt": f"{date.fromisoformat(day) - timedelta(days=1)}T00:20:00+09:00",
        "source": "immutable_day_ahead_origin",
    } for day, non_business, residual in values]
    path.write_text(json.dumps(state), encoding="utf-8")


def test_fresh_weekend_does_not_validate_old_business_cohort(tmp_path):
    _write_state(tmp_path)
    _replace_entries(tmp_path, [
        ("2026-08-19", False, 400), ("2026-08-20", False, 800),
        ("2026-08-28", False, 1200), ("2026-09-06", True, -1000),
    ])
    result = SameRegimeDayLevelCalibrator(_config(), tmp_path).apply(
        _forecast(), date(2026, 9, 7), pd.DataFrame({"is_non_business_day": [0]}),
    )
    assert not result.applied
    assert result.state_status == "stale_same_regime_history"
    assert result.expected_history_dates == ("2026-09-02", "2026-09-03", "2026-09-04")


def test_recent_weekend_cohort_survives_normal_weekday_gap(tmp_path):
    _write_state(tmp_path)
    _replace_entries(tmp_path, [
        ("2026-08-23", True, 400), ("2026-08-29", True, 800),
        ("2026-08-30", True, 1200), ("2026-09-04", False, -1000),
    ])
    result = SameRegimeDayLevelCalibrator(_config(), tmp_path).apply(
        _forecast(), date(2026, 9, 5), pd.DataFrame({"is_non_business_day": [1]}),
    )
    assert result.applied
    assert result.adjustment_mw == 200
    assert result.history_dates == result.expected_history_dates


def test_d0_seed_is_not_mixed_with_d1_history(tmp_path):
    _write_state(tmp_path)
    path = tmp_path / "metrics/day-level.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["entries"][0]["source"] = "fixed_origin_holdout_seed"
    path.write_text(json.dumps(state), encoding="utf-8")
    result = SameRegimeDayLevelCalibrator(_config(), tmp_path).apply(
        _forecast(), date(2026, 1, 8), pd.DataFrame({"is_non_business_day": [0]}),
    )
    assert not result.applied
    assert result.rejected_origin_entries == 1
    assert len(result.history_dates) == 2


@pytest.mark.parametrize("timestamp,valid", [
    ("2026-01-06T15:30:00+00:00", False),
    ("2026-01-06T14:30:00+00:00", True),
    ("2026-01-06T20:00:00", False),
    ("2026-01-05T20:00:00+09:00", False),
])
def test_origin_date_uses_jst_and_exact_d1(timestamp, valid):
    assert SameRegimeDayLevelCalibrator._is_day_ahead_origin(timestamp, date(2026, 1, 7)) is valid


def test_complete_actuals_without_etl_finalization_are_not_training_truth(tmp_path):
    _write_state(tmp_path)
    path = tmp_path / "actual/2026-01-07.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"series": [
        {"ts": point.ts, "actualMw": 31000} for point in _forecast()
    ]}), encoding="utf-8")
    assert SameRegimeDayLevelCalibrator(_config(), tmp_path)._final_actuals(date(2026, 1, 7)) is None


def test_d1_residual_prior_does_not_adjust_same_day_forecast(tmp_path):
    _write_state(tmp_path)
    _replace_entries(tmp_path, [
        ("2026-01-02", False, 400), ("2026-01-05", False, 800),
        ("2026-01-06", False, 1200), ("2026-01-07", False, -9000),
    ])
    cfg = _config()
    cfg["serving_calibration"] = {"same_regime_day_level": {"application": "day_ahead_only"}}
    calibrator = SameRegimeDayLevelCalibrator(cfg, tmp_path)
    forecasts = _forecast()
    features = pd.DataFrame({"is_non_business_day": [0]})
    d0 = calibrator.apply(forecasts, date(2026, 1, 8), features,
                          issued_at="2026-01-08T08:30:00+09:00")
    assert d0.state_status == "origin_horizon_mismatch"
    assert d0.forecasts == forecasts
    d1 = calibrator.apply(forecasts, date(2026, 1, 8), features,
                          issued_at="2026-01-07T21:00:00+09:00")
    assert d1.applied
    assert d1.history_dates == ("2026-01-02", "2026-01-05", "2026-01-06")
    assert d1.adjustment_mw == 200
