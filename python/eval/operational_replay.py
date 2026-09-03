"""Evaluate the forecasts and calibration stages that were actually served."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from python.eval.model_validation import TIME_BANDS, _metric_bundle, _metric_rows

JST = ZoneInfo("Asia/Tokyo")
_FALLBACK_SOURCE = "tepco_forecast_fallback"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _actual_context_by_hour(out_dir: Path, target: date) -> dict[int, dict]:
    payload = _read_json(out_dir / "actual" / f"{target.isoformat()}.json")
    if not payload:
        return {}
    result: dict[int, dict] = {}
    for point in payload.get("series", []):
        if point.get("actualSource") == _FALLBACK_SOURCE:
            continue
        value = point.get("actualMw")
        if value is None:
            continue
        tepco_forecast = point.get("tepcoForecastMw")
        result[pd.Timestamp(point["ts"]).hour] = {
            "actual": float(value),
            "tepcoForecast": (
                float(tepco_forecast) if tepco_forecast is not None else None
            ),
        }
    return result


def _actual_by_hour(out_dir: Path, target: date) -> dict[int, float]:
    return {
        hour: row["actual"]
        for hour, row in _actual_context_by_hour(out_dir, target).items()
    }


def _forecast_payload(out_dir: Path, target: date) -> dict:
    return _read_json(
        out_dir / "forecast" / f"{target.isoformat()}.json"
    ) or {}


def _forecast_by_hour(out_dir: Path, target: date) -> dict[int, dict]:
    payload = _forecast_payload(out_dir, target)
    if not payload:
        return {}
    return {
        pd.Timestamp(point["ts"]).hour: point
        for point in payload.get("series", [])
        if point.get("forecastMw") is not None
    }


def _latest_calibration_snapshot(out_dir: Path, target: date) -> dict | None:
    snapshot_dir = (
        out_dir
        / "reports"
        / "internal"
        / "operational-calibration"
        / "snapshots"
        / target.isoformat()
    )
    index = _read_json(snapshot_dir / "index.json")
    if index:
        entries = index.get("snapshots", [])
        for entry in reversed(entries):
            relative = entry.get("path")
            if not relative:
                continue
            payload = _read_json(out_dir / relative)
            if payload:
                return payload
    candidates = sorted(
        path for path in snapshot_dir.glob("*.json") if path.name != "index.json"
    )
    return _read_json(candidates[-1]) if candidates else None


def _is_non_business_day(target: date) -> bool:
    try:
        import jpholiday

        return target.weekday() >= 5 or bool(jpholiday.is_holiday(target))
    except ImportError:
        return target.weekday() >= 5


def _stage_rows(snapshot: dict | None) -> dict[str, dict[int, float]]:
    if not snapshot:
        return {}
    stages: dict[str, dict[int, float]] = {}
    for row in snapshot.get("hourlyDiagnostics", []):
        hour = row.get("hour")
        if hour is None:
            continue
        for stage, value in (row.get("forecastMwByStage") or {}).items():
            if value is not None:
                stages.setdefault(stage, {})[int(hour)] = float(value)
        post_value = row.get("postCalibrationForecastMw")
        if post_value is not None:
            stages.setdefault("final_recalculated", {})[int(hour)] = float(post_value)
    return stages


def _interval_summary(rows: list[dict]) -> dict:
    if not rows:
        return {
            "hours": 0,
            "p95CoveragePct": None,
            "averageP95HalfWidthMw": None,
        }
    covered = [
        row["lower"] <= row["actual"] <= row["upper"]
        for row in rows
    ]
    half_widths = [
        (row["upper"] - row["lower"]) / 2.0
        for row in rows
    ]
    return {
        "hours": len(rows),
        "p95CoveragePct": round(float(np.mean(covered) * 100.0), 1),
        "averageP95HalfWidthMw": round(float(np.mean(half_widths)), 1),
    }


def _interval_bundle(rows: list[dict]) -> dict:
    result = {
        "overall": _interval_summary(rows),
        "regimes": {},
        "timeBands": {},
    }
    result["regimes"]["business"] = _interval_summary([
        row for row in rows if not row["isNonBusinessDay"]
    ])
    result["regimes"]["nonBusiness"] = _interval_summary([
        row for row in rows if row["isNonBusinessDay"]
    ])
    for name, start_hour, end_hour in TIME_BANDS:
        result["timeBands"][name] = _interval_summary([
            row for row in rows if start_hour <= row["hour"] <= end_hour
        ])
    return result


def _conformal_shadow(rows: list[dict]) -> dict:
    result: dict[str, dict] = {"regimes": {}, "timeBands": {}}

    def recommendation(selected: list[dict]) -> dict:
        residuals = np.asarray(
            [abs(row["predicted"] - row["actual"]) for row in selected],
            dtype=float,
        )
        return {
            "hours": len(selected),
            "recommendedP95HalfWidthMw": round(
                float(np.quantile(residuals, 0.95)),
                1,
            )
            if len(selected) >= 24
            else None,
            "status": "shadow_only",
        }

    result["regimes"]["business"] = recommendation([
        row for row in rows if not row["isNonBusinessDay"]
    ])
    result["regimes"]["nonBusiness"] = recommendation([
        row for row in rows if row["isNonBusinessDay"]
    ])
    for name, start_hour, end_hour in TIME_BANDS:
        result["timeBands"][name] = recommendation([
            row for row in rows if start_hour <= row["hour"] <= end_hour
        ])
    return result


def _interval_coverage_flags(
    interval: dict,
    *,
    target_pct: float = 95.0,
    tolerance_pct: float = 1.0,
) -> dict:
    under: list[dict] = []
    over: list[dict] = []
    for section in ("regimes", "timeBands"):
        for name, metrics in interval[section].items():
            coverage = metrics.get("p95CoveragePct")
            if coverage is None or int(metrics.get("hours", 0)) < 24:
                continue
            row = {
                "segment": f"{section}.{name}",
                "coveragePct": coverage,
                "gapPct": round(float(coverage - target_pct), 1),
            }
            if coverage < target_pct - tolerance_pct:
                under.append(row)
            elif coverage > target_pct + tolerance_pct:
                over.append(row)
    return {
        "targetPct": target_pct,
        "tolerancePct": tolerance_pct,
        "underCoverage": under,
        "overCoverage": over,
        "status": "review" if under else "ok",
    }


def build_operational_replay_report(
    out_dir: Path,
    *,
    window_days: int = 28,
    generated_at: str | None = None,
    model_contract: str | None = None,
    artifact_sha256: str | None = None,
    promoted_at: str | None = None,
) -> dict:
    metadata = _read_json(out_dir / ".lgbm_model_meta.json") or {}
    artifact_sha256 = artifact_sha256 or metadata.get("artifactSha256")
    promoted_at = promoted_at or metadata.get("promotedAt")
    scope_requested = bool(model_contract and artifact_sha256)
    scope_start: date | None = None
    if promoted_at:
        try:
            # A promotion made during a day can leave earlier frozen hours from
            # the previous artifact. Start contract health on the next full day.
            scope_start = pd.Timestamp(promoted_at).date() + timedelta(days=1)
        except (TypeError, ValueError):
            scope_start = None

    actual_files = sorted((out_dir / "actual").glob("*.json"))
    complete_dates: list[date] = []
    for path in actual_files:
        try:
            target = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if len(_actual_by_hour(out_dir, target)) >= 24:
            complete_dates.append(target)
    evaluation_dates = complete_dates[-max(1, int(window_days)):]

    served_rows: list[dict] = []
    champion_served_rows: list[dict] = []
    tepco_rows: list[dict] = []
    interval_rows: list[dict] = []
    stage_metric_rows: dict[str, list[dict]] = {}
    missing_snapshots: list[str] = []
    daily: list[dict] = []
    champion_dates: list[date] = []
    eligible_champion_dates: list[date] = []
    excluded_champion_dates: list[dict] = []

    for target in evaluation_dates:
        actual_context = _actual_context_by_hour(out_dir, target)
        actual = {
            hour: row["actual"]
            for hour, row in actual_context.items()
        }
        forecast_payload = _forecast_payload(out_dir, target)
        forecast = {
            pd.Timestamp(point["ts"]).hour: point
            for point in forecast_payload.get("series", [])
            if point.get("forecastMw") is not None
        }
        forecast_model = forecast_payload.get("model") or {}
        after_promotion = scope_start is None or target >= scope_start
        if scope_requested and after_promotion:
            eligible_champion_dates.append(target)
        in_champion_scope = bool(
            scope_requested
            and after_promotion
            and forecast_model.get("contract") == model_contract
            and forecast_model.get("artifactSha256") == artifact_sha256
        )
        if in_champion_scope:
            champion_dates.append(target)
        elif scope_requested and after_promotion:
            excluded_champion_dates.append({
                "date": target.isoformat(),
                "modelContract": forecast_model.get("contract"),
                "artifactSha256": forecast_model.get("artifactSha256"),
            })
        is_non_business = _is_non_business_day(target)
        day_served: list[dict] = []
        for hour, actual_mw in actual.items():
            point = forecast.get(hour)
            if not point:
                continue
            row = {
                "date": target,
                "hour": hour,
                "actual": actual_mw,
                "predicted": float(point["forecastMw"]),
                "isNonBusinessDay": is_non_business,
            }
            served_rows.append(row)
            day_served.append(row)
            if in_champion_scope:
                champion_served_rows.append(row)
            tepco_forecast = actual_context[hour]["tepcoForecast"]
            if tepco_forecast is not None:
                tepco_rows.append({
                    **row,
                    "predicted": tepco_forecast,
                })
            if (
                point.get("p95LowerMw") is not None
                and point.get("p95UpperMw") is not None
            ):
                interval_rows.append({
                    **row,
                    "lower": float(point["p95LowerMw"]),
                    "upper": float(point["p95UpperMw"]),
                })

        snapshot = _latest_calibration_snapshot(out_dir, target)
        stages = _stage_rows(snapshot)
        if not stages:
            missing_snapshots.append(target.isoformat())
        for stage, forecasts in stages.items():
            for hour, predicted in forecasts.items():
                if hour not in actual:
                    continue
                stage_metric_rows.setdefault(stage, []).append({
                    "date": target,
                    "hour": hour,
                    "actual": actual[hour],
                    "predicted": predicted,
                    "isNonBusinessDay": is_non_business,
                })
        daily.append({
            "date": target.isoformat(),
            "served": _metric_rows(day_served),
            "stageSnapshotAvailable": bool(stages),
            "modelContract": forecast_model.get("contract"),
            "artifactSha256": forecast_model.get("artifactSha256"),
            "inChampionScope": in_champion_scope,
        })

    stage_metrics = {
        stage: _metric_bundle(rows)
        for stage, rows in stage_metric_rows.items()
    }
    raw_mae = (
        stage_metrics.get("raw_lgbm", {})
        .get("overall", {})
        .get("maeMw")
    )
    analog_mae = (
        stage_metrics.get("analog_adjusted", {})
        .get("overall", {})
        .get("maeMw")
    )
    analog_delta = (
        round(float(analog_mae - raw_mae), 1)
        if raw_mae is not None and analog_mae is not None
        else None
    )
    analog_hours = min(
        int(
            stage_metrics.get("raw_lgbm", {})
            .get("overall", {})
            .get("hours", 0)
        ),
        int(
            stage_metrics.get("analog_adjusted", {})
            .get("overall", {})
            .get("hours", 0)
        ),
    )
    interval_bundle = _interval_bundle(interval_rows)
    champion_period = {
        "start": min(champion_dates).isoformat() if champion_dates else None,
        "end": max(champion_dates).isoformat() if champion_dates else None,
        "days": len(set(champion_dates)),
    }
    champion_scope = {
        "status": (
            "ok" if scope_requested and champion_served_rows
            else "insufficient_data" if scope_requested
            else "not_configured"
        ),
        "modelContract": model_contract,
        "artifactSha256": artifact_sha256,
        "promotedAt": promoted_at,
        "fullDayEvaluationStart": scope_start.isoformat() if scope_start else None,
        "period": champion_period,
        "served": _metric_bundle(champion_served_rows),
        "coverage": {
            "eligibleFinalizedDays": len(set(eligible_champion_dates)),
            "matchingDays": len(set(champion_dates)),
            "hours": len(champion_served_rows),
            "excludedDates": excluded_champion_dates,
        },
    }

    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at
        or pd.Timestamp.now(tz=JST).isoformat(timespec="seconds"),
        "methodology": {
            "type": "served_forecast_operational_replay",
            "windowDays": int(window_days),
            "stageSnapshots": "latest_available_per_date",
        },
        "period": {
            "start": evaluation_dates[0].isoformat() if evaluation_dates else None,
            "end": evaluation_dates[-1].isoformat() if evaluation_dates else None,
            "days": len(evaluation_dates),
        },
        "served": _metric_bundle(served_rows),
        "championScope": champion_scope,
        "reference": {
            "tepco": _metric_bundle(tepco_rows),
            "maeDeltaVsTepcoMw": (
                round(
                    float(
                        _metric_rows(served_rows)["maeMw"]
                        - _metric_rows(tepco_rows)["maeMw"]
                    ),
                    1,
                )
                if served_rows and tepco_rows
                else None
            ),
        },
        "interval": {
            **interval_bundle,
            "coverageDiagnostics": _interval_coverage_flags(interval_bundle),
        },
        "stages": stage_metrics,
        "analogShadow": {
            "hours": analog_hours,
            "rawMaeMw": raw_mae,
            "analogAdjustedMaeMw": analog_mae,
            "maeDeltaMw": analog_delta,
            "verdict": (
                "insufficient_data" if analog_hours < 168
                else "improved" if analog_delta is not None and analog_delta < 0
                else "degraded" if analog_delta is not None and analog_delta > 0
                else "insufficient_data"
            ),
        },
        "intervalCalibrationShadow": _conformal_shadow(served_rows),
        "coverage": {
            "servedHours": len(served_rows),
            "stageSnapshotDays": len(evaluation_dates) - len(missing_snapshots),
            "missingStageSnapshotDates": missing_snapshots,
        },
        "daily": daily,
    }
