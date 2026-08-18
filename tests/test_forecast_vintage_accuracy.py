from __future__ import annotations

import json
from datetime import date

import pytest

from python.eval.forecast_vintage_accuracy import (
    _qualification,
    append_forecast_vintage_snapshot,
    backfill_forecast_vintages_from_snapshots,
    build_forecast_vintage_accuracy_report,
)


def _qualification_bucket(days: int, *, hours: int | None = None) -> dict:
    paired_hours = hours if hours is not None else days * 24
    metric = {
        "hours": paired_hours,
        "maeMw": 100.0,
        "wapePct": 0.3,
        "rmseMw": 125.0,
        "maxErrorMw": 400.0,
    }
    return {
        "dates": days,
        "model": metric,
        "tepco": metric,
        "maeRatio": 1.0,
        "wapeRatio": 1.0,
        "rmseRatio": 1.0,
        "maxErrorRatio": 1.0,
        "pairedDifference": {"maeRatioUpper": 1.05},
        "timeBands": {
            "overnight": {
                "model": {"hours": days * 6},
                "tepco": {"hours": days * 6},
                "maeRatio": 1.0,
            },
            "morning": {
                "model": {"hours": days * 5},
                "tepco": {"hours": days * 5},
                "maeRatio": 1.0,
            },
            "daytime": {
                "model": {"hours": days * 5},
                "tepco": {"hours": days * 5},
                "maeRatio": 1.0,
            },
            "late_afternoon": {
                "model": {"hours": days * 3},
                "tepco": {"hours": days * 3},
                "maeRatio": 1.0,
            },
            "evening": {
                "model": {"hours": days * 5},
                "tepco": {"hours": days * 5},
                "maeRatio": 1.0,
            },
        },
    }


def _qualification_settings() -> dict:
    return {
        "minimum_qualification_days": 84,
        "non_inferiority_ratio": 1.10,
        "max_segment_ratio": 1.25,
        "minimum_bucket_coverage_ratio": 0.80,
        "max_rmse_ratio": 1.15,
        "max_max_error_ratio": 1.25,
    }


def _write_actual(tmp_path, target: date, actual_mw: float = 30_000.0) -> None:
    path = tmp_path / "actual" / f"{target.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "date": target.isoformat(),
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "series": [
            {
                "ts": f"{target.isoformat()}T{hour:02d}:00:00+09:00",
                "actualMw": actual_mw + hour,
                "actualSource": "observed",
            }
            for hour in range(24)
        ],
    }), encoding="utf-8")


def _append(
    tmp_path,
    target: date,
    captured_at: str,
    *,
    model_mw: float,
    tepco_mw: float,
    hour: int = 12,
) -> None:
    ts = f"{target.isoformat()}T{hour:02d}:00:00+09:00"
    append_forecast_vintage_snapshot(
        tmp_path,
        target,
        generated_at=captured_at,
        run_type="intraday",
        model={"name": "lgbm_quantile_q50"},
        model_series=[{"ts": ts, "forecastMw": model_mw}],
        tepco_series=[{"ts": ts, "tepcoForecastMw": tepco_mw}],
        config={"forecast_vintages": {"retention_days": 120}},
    )


def test_append_vintage_keeps_only_future_targets_and_never_rewrites_capture(
    tmp_path,
):
    target = date(2026, 8, 18)
    _append(
        tmp_path,
        target,
        "2026-08-18T11:30:00+09:00",
        model_mw=30_100.0,
        tepco_mw=30_200.0,
    )
    _append(
        tmp_path,
        target,
        "2026-08-18T11:30:00+09:00",
        model_mw=99_999.0,
        tepco_mw=99_999.0,
    )
    _append(
        tmp_path,
        target,
        "2026-08-18T12:30:00+09:00",
        model_mw=31_000.0,
        tepco_mw=31_000.0,
    )

    payload = json.loads(
        (
            tmp_path
            / "reports/internal/forecast-vintages/2026-08-18.json"
        ).read_text(encoding="utf-8")
    )

    assert payload["snapshotCount"] == 1
    assert payload["snapshots"][0]["series"][0]["modelForecastMw"] == 30_100.0
    assert payload["snapshots"][0]["series"][0]["leadMinutes"] == 30.0


def test_append_vintage_normalizes_naive_tepco_timestamp_to_jst(tmp_path):
    target = date(2026, 8, 18)
    append_forecast_vintage_snapshot(
        tmp_path,
        target,
        generated_at="2026-08-18T11:30:00+09:00",
        run_type="intraday",
        model="model",
        model_series=[{
            "ts": "2026-08-18T12:00:00+09:00",
            "forecastMw": 30_100.0,
        }],
        tepco_series=[{
            "ts": "2026-08-18T12:00:00",
            "tepcoForecastMw": 30_200.0,
        }],
    )

    payload = json.loads(
        (
            tmp_path
            / "reports/internal/forecast-vintages/2026-08-18.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["snapshotCount"] == 1
    assert payload["snapshots"][0]["series"][0]["tepcoForecastMw"] == 30_200.0


def test_matched_vintage_report_selects_one_same_capture_pair_per_lead_bucket(
    tmp_path,
):
    target = date(2026, 8, 18)
    _write_actual(tmp_path, target)
    captures = [
        ("2026-08-18T11:30:00+09:00", 30_012.0, 30_112.0),
        ("2026-08-18T10:30:00+09:00", 31_000.0, 31_000.0),
        ("2026-08-18T09:30:00+09:00", 30_212.0, 30_412.0),
        ("2026-08-18T05:30:00+09:00", 30_312.0, 30_612.0),
        ("2026-08-17T18:00:00+09:00", 30_412.0, 30_812.0),
    ]
    for captured_at, model_mw, tepco_mw in captures:
        _append(
            tmp_path,
            target,
            captured_at,
            model_mw=model_mw,
            tepco_mw=tepco_mw,
        )

    report = build_forecast_vintage_accuracy_report(
        tmp_path,
        generated_at="2026-08-19T09:00:00+09:00",
    )

    assert report["availability"] == "ok"
    assert report["coverage"] == {
        "matchedRows": 4,
        "dates": 1,
        "retentionDays": 120,
    }
    buckets = report["windows"]["28d"]["leadBuckets"]
    assert buckets["0_2h"]["model"]["maeMw"] == pytest.approx(0.0)
    assert buckets["0_2h"]["tepco"]["maeMw"] == pytest.approx(100.0)
    assert buckets["2_4h"]["model"]["maeMw"] == pytest.approx(200.0)
    assert buckets["4_8h"]["model"]["maeMw"] == pytest.approx(300.0)
    assert buckets["8_24h"]["model"]["maeMw"] == pytest.approx(400.0)
    assert report["qualification"]["status"] == "collecting"
    assert report["qualification"]["passed"] is False


def test_qualification_requires_dense_paired_hour_coverage():
    windows = {
        "28d": {
            "period": {"days": 28},
            "leadBuckets": {
                name: _qualification_bucket(28)
                for name in ("0_2h", "2_4h", "4_8h", "8_24h")
            },
        },
        "84d": {
            "period": {"days": 84},
            "leadBuckets": {
                name: _qualification_bucket(84)
                for name in ("0_2h", "2_4h", "4_8h", "8_24h")
            },
        },
    }
    assert _qualification(windows, _qualification_settings())["passed"] is True

    windows["28d"]["leadBuckets"]["0_2h"] = _qualification_bucket(
        28,
        hours=100,
    )
    result = _qualification(windows, _qualification_settings())

    assert result["status"] == "collecting"
    assert "28d.0_2h.insufficient_hours" in result["failures"]


def test_qualification_rejects_risk_or_uncertain_paired_result():
    windows = {
        "28d": {
            "period": {"days": 28},
            "leadBuckets": {
                name: _qualification_bucket(28)
                for name in ("0_2h", "2_4h", "4_8h", "8_24h")
            },
        },
        "84d": {
            "period": {"days": 84},
            "leadBuckets": {
                name: _qualification_bucket(84)
                for name in ("0_2h", "2_4h", "4_8h", "8_24h")
            },
        },
    }
    bucket = windows["28d"]["leadBuckets"]["2_4h"]
    bucket["rmseRatio"] = 1.20
    bucket["pairedDifference"]["maeRatioUpper"] = 1.12

    result = _qualification(windows, _qualification_settings())

    assert result["status"] == "not_qualified"
    assert "28d.2_4h.rmse_ratio" in result["failures"]
    assert "28d.2_4h.paired_mae_ratio_ci" in result["failures"]


def test_backfill_pairs_only_same_date_snapshots_within_two_minutes(tmp_path):
    target = date(2026, 8, 18)
    forecast_path = (
        tmp_path
        / "forecast_snapshots"
        / target.isoformat()
        / "forecast.json"
    )
    forecast_path.parent.mkdir(parents=True)
    forecast_path.write_text(json.dumps({
        "targetDate": target.isoformat(),
        "generatedAt": "2026-08-18T08:31:35+09:00",
        "runType": "intraday",
        "model": {"name": "lgbm_quantile_q50"},
        "series": [{
            "ts": "2026-08-18T09:00:00+09:00",
            "forecastMw": 31_000.0,
        }],
    }), encoding="utf-8")
    calibration_path = (
        tmp_path
        / "reports/internal/operational-calibration/snapshots"
        / target.isoformat()
        / "calibration.json"
    )
    calibration_path.parent.mkdir(parents=True)
    calibration_path.write_text(json.dumps({
        "date": target.isoformat(),
        "generatedAt": "2026-08-18T08:31:24+09:00",
        "hourlyDiagnostics": [{
            "ts": "2026-08-18T09:00:00+09:00",
            "tepcoForecastMw": 30_800.0,
        }],
    }), encoding="utf-8")

    first = backfill_forecast_vintages_from_snapshots(tmp_path)
    second = backfill_forecast_vintages_from_snapshots(tmp_path)
    payload = json.loads(
        (
            tmp_path
            / "reports/internal/forecast-vintages/2026-08-18.json"
        ).read_text(encoding="utf-8")
    )

    assert first == {"matched": 1, "imported": 1, "skipped": 0}
    assert second == {"matched": 0, "imported": 0, "skipped": 1}
    assert payload["snapshotCount"] == 1
    assert payload["snapshots"][0]["captureOrigin"] == (
        "legacy_same_run_snapshot_pair"
    )
    assert payload["snapshots"][0]["series"][0]["tepcoForecastMw"] == 30_800.0
