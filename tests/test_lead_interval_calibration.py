from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from python.etl.run_batch import build_forecast_json
from python.forecast.baseline import HourlyForecast
from python.forecast.rolling_interval_calibration import (
    build_lead_conformal_profile, forecast_lead_band, serving_policy_fingerprint,
)


def _config():
    return {
        "interval_calibration": {"min_p95_half_width_mw": 500,
            "max_p95_half_width_mw": 3750, "p95_half_width_scale": 1},
        "served_interval_calibration": {"enabled": True,
            "mode": "lead_aware_conformal_target_width", "minimum_samples_per_lead_band": 3,
            "minimum_history_days": 3, "max_p95_half_width_mw": 3750, "safety_scale": 1.05},
    }


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _history(root, config):
    days = [date(2026, 9, day) for day in range(1, 5)]
    _write(root / ".etl_state.json", {"okDates": [str(day) for day in days]})
    _write(root / ".lgbm_model_meta.json", {"artifactSha256": "model-a"})
    for day in days:
        _write(root / "actual" / f"{day}.json", {"series": [
            {"ts": f"{day}T{h:02d}:00:00+09:00", "actualMw": 30000, "actualSource": "observed"}
            for h in range(24)
        ]})
        for lead, error in ((1, 1000), (3, 3000)):
            ts = datetime.fromisoformat(f"{day}T09:00:00+09:00")
            _write(root / "forecast_snapshots" / str(day) / f"lead-{lead}.json", {
                "generatedAt": (ts - timedelta(hours=lead)).isoformat(),
                "model": {"artifactSha256": "model-a"},
                "servingPolicyFingerprint": serving_policy_fingerprint(config),
                "series": [{"ts": ts.isoformat(), "forecastMw": 30000 + error}],
            })


def _profile(root, cfg, issued="2026-09-08T08:00:00+09:00"):
    return build_lead_conformal_profile(root, date(2026, 9, 8), cfg, issued, "model-a")


def test_widths_use_issued_lead_not_final_served_errors(tmp_path):
    cfg = _config()
    _history(tmp_path, cfg)
    for day in range(1, 5):
        _write(tmp_path / f"forecast/2026-09-{day:02d}.json", {"series": [
            {"ts": f"2026-09-{day:02d}T09:00:00+09:00", "forecastMw": 30000}
        ]})
    assert _profile(tmp_path, cfg)["servedTarget"]["targetWidthsMwByHour"]["9"] == 1050
    assert _profile(tmp_path, cfg, "2026-09-08T06:00:00+09:00")["servedTarget"]["targetWidthsMwByHour"]["9"] == 3150


@pytest.mark.parametrize("field,bad_value", [
    ("model", {"artifactSha256": "other-model"}),
    ("servingPolicyFingerprint", "other-policy"),
    ("generatedAt", "2026-09-09T00:00:00+09:00"),
    ("generatedAt", "2026-09-01T08:00:00"),
])
def test_unknown_artifact_policy_or_issue_time_is_not_calibration_evidence(tmp_path, field, bad_value):
    cfg = _config()
    _history(tmp_path, cfg)
    for path in (tmp_path / "forecast_snapshots").rglob("*.json"):
        value = json.loads(path.read_text())
        value[field] = bad_value
        _write(path, value)
    assert _profile(tmp_path, cfg)["servedTarget"]["targetWidthsMwByHour"] == {}


def test_repeated_runs_do_not_supply_more_independent_samples(tmp_path):
    cfg = _config()
    _history(tmp_path, cfg)
    for day in range(1, 5):
        path = tmp_path / f"forecast_snapshots/2026-09-{day:02d}/lead-1.json"
        value = json.loads(path.read_text())
        for duplicate in range(5):
            _write(path.with_name(f"duplicate-{duplicate}.json"), value)
    detail = _profile(tmp_path, cfg)["servedTarget"]["detailsByHour"]["9"]
    assert detail["groups"]["all_regime"]["samples"] == 4


def test_previous_day_cannot_leak_morning_csv_into_midnight_replay(tmp_path):
    cfg = _config()
    _history(tmp_path, cfg)
    profile = build_lead_conformal_profile(tmp_path, date(2026, 9, 5), cfg,
        "2026-09-05T08:00:00+09:00", "model-a")
    assert profile["historyCutoffExclusive"] == "2026-09-04"
    assert profile["servedTarget"]["detailsByHour"]["9"]["groups"]["all_regime"]["days"] == 3


def test_quantile_clipped_by_cap_is_not_labelled_calibrated(tmp_path):
    cfg = _config()
    cfg["served_interval_calibration"]["max_p95_half_width_mw"] = 2500
    _history(tmp_path, cfg)
    profile = _profile(tmp_path, cfg, "2026-09-08T06:00:00+09:00")
    detail = profile["servedTarget"]["detailsByHour"]["9"]
    assert detail["application"] == "native_fallback_cap_exceeded"
    assert "9" not in profile["servedTarget"]["targetWidthsMwByHour"]


def test_policy_fingerprint_changes_for_controls_not_band_widths():
    cfg = _config()
    before = serving_policy_fingerprint(cfg)
    cfg["served_interval_calibration"]["safety_scale"] = 2
    assert serving_policy_fingerprint(cfg) == before
    cfg["intraday_correction"] = {"shrinkage": .2}
    assert serving_policy_fingerprint(cfg) != before


def test_observed_bound_floor_invalidates_unbounded_floor_policy_history():
    cfg = _config()
    old_payload = {key: cfg.get(key, {}) for key in (
        "forecast", "weather_features", "weather_forecast_bias_correction",
        "adjustment", "intraday_correction", "serving_calibration",
    )}
    old_payload["servingSemanticsVersion"] = 1
    old_policy = hashlib.sha256(json.dumps(
        old_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()
    assert serving_policy_fingerprint(cfg) != old_policy


def test_serving_preserves_observed_band_and_calibrates_future_band(tmp_path):
    cfg = _config()
    _history(tmp_path, cfg)
    _write(tmp_path / "actual/2026-09-08.json", {"series": [
        {"ts": "2026-09-08T07:00:00+09:00", "actualMw": 30100}
    ]})
    forecasts = [HourlyForecast(f"2026-09-08T{h:02d}:00:00+09:00", 30000,
                               29200, 31000, 28800, 32100) for h in (7, 9)]
    payload = build_forecast_json(date(2026, 9, 8), forecasts, cfg, "lgbm_quantile",
        out_dir=tmp_path, generated_at="2026-09-08T08:00:00+09:00", preserve_observed_bands=True)
    past, future = payload["series"]
    assert past["p95LowerMw"] == 29200
    assert past["p99UpperMw"] == 32100
    assert future["p95UpperMw"] == 31050
    assert all(row["forecastMw"] == 30000 for row in payload["series"])
    assert payload["intervalCalibration"]["preservedObservedHours"] == [7]


@pytest.mark.parametrize("lead,expected", [(0,None),(2,"0_2h"),(2.01,"2_4h"),(-1,None),(48,"24_48h"),(49,None)])
def test_lead_boundaries(lead, expected):
    assert forecast_lead_band(lead) == expected


@pytest.mark.parametrize("bad_source", ["tepco_forecast_fallback", "wrong_date"])
def test_incomplete_or_wrong_day_actuals_are_excluded(tmp_path, bad_source):
    cfg = _config()
    _history(tmp_path, cfg)
    for path in (tmp_path / "actual").glob("*.json"):
        payload = json.loads(path.read_text())
        if bad_source == "wrong_date":
            payload["series"][0]["ts"] = "2026-08-01T00:00:00+09:00"
        else:
            payload["series"][0]["actualSource"] = bad_source
        _write(path, payload)
    assert _profile(tmp_path, cfg)["availability"] == "insufficient_history"


def test_missing_issue_time_or_artifact_keeps_native_intervals(tmp_path):
    cfg = _config()
    _history(tmp_path, cfg)
    result = build_lead_conformal_profile(tmp_path, date(2026, 9, 8), cfg, "invalid", "model-a")
    assert result["availability"] == "missing_issue_or_artifact"
    result = build_lead_conformal_profile(tmp_path, date(2026, 9, 8), cfg,
                                        "2026-09-08T08:00:00+09:00", None)
    assert result["servedTarget"]["targetWidthsMwByHour"] == {}


def test_actual_timestamps_are_indexed_by_jst_hour(tmp_path):
    cfg = _config()
    _history(tmp_path, cfg)
    for path in (tmp_path / "actual").glob("*.json"):
        payload = json.loads(path.read_text())
        for row in payload["series"]:
            timestamp = datetime.fromisoformat(row["ts"])
            row["actualMw"] = 30000 if timestamp.hour == 9 else 10000
            row["ts"] = timestamp.astimezone(timezone.utc).isoformat()
        _write(path, payload)
    assert _profile(tmp_path, cfg)["servedTarget"]["targetWidthsMwByHour"]["9"] == 1050
