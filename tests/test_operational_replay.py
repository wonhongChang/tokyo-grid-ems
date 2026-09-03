"""Tests for the served-forecast operational replay report."""
from __future__ import annotations

import json
from datetime import date

import pytest

from python.eval.operational_replay import build_operational_replay_report


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_operational_replay_separates_served_and_stage_shadow_metrics(tmp_path):
    target = date(2026, 7, 1)
    actual_series = []
    forecast_series = []
    diagnostics = []
    for hour in range(24):
        ts = f"{target.isoformat()}T{hour:02d}:00:00+09:00"
        actual = 30_000.0 + hour * 100.0
        actual_series.append({
            "ts": ts,
            "actualMw": actual,
            "actualSource": "observed",
            "tepcoForecastMw": actual + 50.0,
        })
        forecast_series.append({
            "ts": ts,
            "forecastMw": actual + 100.0,
            "p95LowerMw": actual - 400.0,
            "p95UpperMw": actual + 600.0,
        })
        diagnostics.append({
            "hour": hour,
            "forecastMwByStage": {
                "raw_lgbm": actual + 300.0,
                "analog_adjusted": actual + 200.0,
            },
            "postCalibrationForecastMw": actual + 100.0,
        })

    _write_json(
        tmp_path / "actual" / f"{target.isoformat()}.json",
        {"series": actual_series},
    )
    _write_json(
        tmp_path / "forecast" / f"{target.isoformat()}.json",
        {"series": forecast_series},
    )
    snapshot_path = (
        tmp_path
        / "reports"
        / "internal"
        / "operational-calibration"
        / "snapshots"
        / target.isoformat()
        / "snapshot.json"
    )
    _write_json(snapshot_path, {"hourlyDiagnostics": diagnostics})
    _write_json(
        snapshot_path.parent / "index.json",
        {
            "snapshots": [{
                "path": str(snapshot_path.relative_to(tmp_path)).replace("\\", "/"),
            }],
        },
    )

    report = build_operational_replay_report(
        tmp_path,
        window_days=28,
        generated_at="2026-07-02T09:00:00+09:00",
    )

    assert report["period"]["days"] == 1
    assert report["served"]["overall"]["maeMw"] == pytest.approx(100.0)
    assert report["interval"]["overall"]["p95CoveragePct"] == pytest.approx(100.0)
    assert report["reference"]["tepco"]["overall"]["maeMw"] == pytest.approx(50.0)
    assert report["reference"]["maeDeltaVsTepcoMw"] == pytest.approx(50.0)
    assert report["stages"]["raw_lgbm"]["overall"]["maeMw"] == pytest.approx(300.0)
    assert report["analogShadow"]["verdict"] == "insufficient_data"
    assert report["analogShadow"]["hours"] == 24
    assert report["interval"]["coverageDiagnostics"]["status"] == "ok"
    assert report["coverage"]["stageSnapshotDays"] == 1


def test_operational_replay_excludes_tepco_fallback_from_complete_day(tmp_path):
    target = date(2026, 7, 1)
    actual_series = [
        {
            "ts": f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            "actualMw": 30_000.0,
            "actualSource": (
                "tepco_forecast_fallback" if hour == 23 else "observed"
            ),
        }
        for hour in range(24)
    ]
    _write_json(
        tmp_path / "actual" / f"{target.isoformat()}.json",
        {"series": actual_series},
    )

    report = build_operational_replay_report(tmp_path)

    assert report["period"]["days"] == 0
    assert report["coverage"]["servedHours"] == 0


def test_operational_replay_scopes_champion_metrics_by_contract_and_artifact(
    tmp_path,
):
    current_contract = "v14-r2-source-robust-day-ahead"
    current_artifact = "artifact-v14"
    _write_json(
        tmp_path / ".lgbm_model_meta.json",
        {
            "artifactSha256": current_artifact,
            "promotedAt": "2026-07-01T13:00:00+09:00",
        },
    )
    for day_number, artifact in ((1, "artifact-v11"), (2, current_artifact), (3, "artifact-v11")):
        target = date(2026, 7, day_number)
        actual_series = []
        forecast_series = []
        for hour in range(24):
            ts = f"{target.isoformat()}T{hour:02d}:00:00+09:00"
            actual_series.append({
                "ts": ts,
                "actualMw": 30_000.0,
                "actualSource": "observed",
            })
            forecast_series.append({
                "ts": ts,
                "forecastMw": 30_100.0,
            })
        _write_json(
            tmp_path / "actual" / f"{target.isoformat()}.json",
            {"series": actual_series},
        )
        _write_json(
            tmp_path / "forecast" / f"{target.isoformat()}.json",
            {
                "model": {
                    "contract": current_contract,
                    "artifactSha256": artifact,
                },
                "series": forecast_series,
            },
        )

    report = build_operational_replay_report(
        tmp_path,
        model_contract=current_contract,
        generated_at="2026-07-04T09:00:00+09:00",
    )

    assert report["served"]["overall"]["hours"] == 72
    scope = report["championScope"]
    assert scope["status"] == "ok"
    assert scope["period"] == {
        "start": "2026-07-02",
        "end": "2026-07-02",
        "days": 1,
    }
    assert scope["served"]["overall"]["hours"] == 24
    assert scope["served"]["overall"]["maeMw"] == pytest.approx(100.0)
    assert scope["coverage"]["eligibleFinalizedDays"] == 2
    assert scope["coverage"]["matchingDays"] == 1
    assert scope["coverage"]["excludedDates"][0]["date"] == "2026-07-03"
