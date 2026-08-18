"""Matched-vintage accuracy for model and TEPCO forecasts captured together."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

JST = ZoneInfo("Asia/Tokyo")
_FALLBACK_SOURCE = "tepco_forecast_fallback"
_LEDGER_DIR = Path("reports/internal/forecast-vintages")

DEFAULT_LEAD_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0_2h", 0.0, 120.0),
    ("2_4h", 120.0, 240.0),
    ("4_8h", 240.0, 480.0),
    ("8_24h", 480.0, 1440.0),
)

TIME_BANDS: tuple[tuple[str, int, int], ...] = (
    ("overnight", 0, 5),
    ("morning", 6, 10),
    ("daytime", 11, 15),
    ("late_afternoon", 16, 18),
    ("evening", 19, 23),
)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _config(config: dict | None) -> dict:
    raw = (config or {}).get("forecast_vintages", {})
    return {
        "enabled": bool(raw.get("enabled", True)),
        "retention_days": max(int(raw.get("retention_days", 120)), 1),
        "max_snapshots_per_day": max(
            int(raw.get("max_snapshots_per_day", 48)),
            1,
        ),
        "minimum_qualification_days": max(
            int(raw.get("minimum_qualification_days", 84)),
            1,
        ),
        "non_inferiority_ratio": max(
            float(raw.get("non_inferiority_ratio", 1.10)),
            0.0,
        ),
        "max_segment_ratio": max(
            float(raw.get("max_segment_ratio", 1.25)),
            0.0,
        ),
        "minimum_bucket_coverage_ratio": min(
            max(float(raw.get("minimum_bucket_coverage_ratio", 0.80)), 0.0),
            1.0,
        ),
        "max_rmse_ratio": max(
            float(raw.get("max_rmse_ratio", 1.15)),
            0.0,
        ),
        "max_max_error_ratio": max(
            float(raw.get("max_max_error_ratio", 1.25)),
            0.0,
        ),
    }


def _model_name(model: dict | str | None) -> str | None:
    if isinstance(model, dict):
        value = model.get("name")
        return str(value) if value else None
    return str(model) if model else None


def _future_comparison_rows(
    generated_at: str,
    model_series: list[dict],
    tepco_series: list[dict],
) -> list[dict]:
    captured_at = pd.Timestamp(generated_at)
    if captured_at.tzinfo is None:
        captured_at = captured_at.tz_localize(JST)
    else:
        captured_at = captured_at.tz_convert(JST)

    tepco_by_ts: dict[pd.Timestamp, float] = {}
    for point in tepco_series:
        if not point.get("ts") or point.get("tepcoForecastMw") is None:
            continue
        source_ts = pd.Timestamp(point["ts"])
        if source_ts.tzinfo is None:
            source_ts = source_ts.tz_localize(JST)
        else:
            source_ts = source_ts.tz_convert(JST)
        tepco_by_ts[source_ts] = float(point["tepcoForecastMw"])
    rows: list[dict] = []
    for point in model_series:
        if point.get("ts") is None or point.get("forecastMw") is None:
            continue
        target_ts = pd.Timestamp(point["ts"])
        if target_ts.tzinfo is None:
            target_ts = target_ts.tz_localize(JST)
        else:
            target_ts = target_ts.tz_convert(JST)
        tepco_value = tepco_by_ts.get(target_ts)
        lead_minutes = (target_ts - captured_at).total_seconds() / 60.0
        if tepco_value is None or lead_minutes <= 0:
            continue
        rows.append({
            "ts": target_ts.isoformat(timespec="seconds"),
            "hour": int(target_ts.hour),
            "leadMinutes": round(float(lead_minutes), 1),
            "modelForecastMw": round(float(point["forecastMw"]), 1),
            "tepcoForecastMw": round(float(tepco_value), 1),
        })
    return rows


def _rewrite_index(out_dir: Path, generated_at: str, retention_days: int) -> None:
    ledger_dir = out_dir / _LEDGER_DIR
    entries: list[dict] = []
    for path in sorted(ledger_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        payload = _read_json(path)
        if not payload:
            continue
        snapshots = payload.get("snapshots", [])
        entries.append({
            "targetDate": payload.get("targetDate"),
            "path": path.relative_to(out_dir).as_posix(),
            "snapshotCount": len(snapshots),
            "firstCapturedAt": (
                snapshots[0].get("capturedAt") if snapshots else None
            ),
            "lastCapturedAt": (
                snapshots[-1].get("capturedAt") if snapshots else None
            ),
        })
    _write_json(ledger_dir / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "retentionDays": retention_days,
        "dates": entries,
    })


def _prune_ledgers(
    out_dir: Path,
    current_date: date,
    retention_days: int,
) -> None:
    ledger_dir = out_dir / _LEDGER_DIR
    cutoff = current_date - timedelta(days=retention_days - 1)
    for path in ledger_dir.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            target = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if target < cutoff:
            path.unlink()


def append_forecast_vintage_snapshot(
    out_dir: Path,
    target_date: date,
    *,
    generated_at: str,
    run_type: str,
    model: dict | str | None,
    model_series: list[dict],
    tepco_series: list[dict],
    config: dict | None = None,
    capture_origin: str = "live_pipeline",
) -> Path | None:
    """Append one immutable, future-only model/TEPCO comparison snapshot."""
    settings = _config(config)
    if not settings["enabled"]:
        return None
    rows = _future_comparison_rows(generated_at, model_series, tepco_series)
    if not rows:
        return None

    captured_date = pd.Timestamp(generated_at).date()
    _prune_ledgers(out_dir, captured_date, settings["retention_days"])
    path = out_dir / _LEDGER_DIR / f"{target_date.isoformat()}.json"
    payload = _read_json(path) or {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "targetDate": target_date.isoformat(),
        "sourceContract": {
            "tepco": "published_forecast_captured_at_run_time",
            "model": "served_forecast_captured_at_same_run_time",
            "sourceMayRevisePastValues": True,
            "pastRevisionsApplied": False,
        },
        "snapshots": [],
    }
    snapshots = payload.setdefault("snapshots", [])
    if any(row.get("capturedAt") == generated_at for row in snapshots):
        return path
    if len(snapshots) >= settings["max_snapshots_per_day"]:
        return path

    snapshots.append({
        "capturedAt": generated_at,
        "captureOrigin": capture_origin,
        "runType": run_type,
        "modelName": _model_name(model),
        "series": rows,
    })
    snapshots.sort(key=lambda row: str(row.get("capturedAt") or ""))
    payload["snapshotCount"] = len(snapshots)
    _write_json(path, payload)
    _rewrite_index(out_dir, generated_at, settings["retention_days"])
    return path


def _snapshot_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.glob("*/*.json")
        if path.name != "index.json"
    )


def _timestamp(value: object) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        result = pd.Timestamp(str(value))
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        return result.tz_localize(JST)
    return result.tz_convert(JST)


def _existing_capture_keys(out_dir: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    ledger_dir = out_dir / _LEDGER_DIR
    for path in ledger_dir.glob("*.json"):
        if path.name == "index.json":
            continue
        payload = _read_json(path) or {}
        target_date = str(payload.get("targetDate") or path.stem)
        for snapshot in payload.get("snapshots", []):
            captured_at = snapshot.get("capturedAt")
            if captured_at:
                keys.add((target_date, str(captured_at)))
    return keys


def backfill_forecast_vintages_from_snapshots(
    out_dir: Path,
    *,
    config: dict | None = None,
    max_pair_delta_seconds: float = 120.0,
) -> dict:
    """Import only legacy model/TEPCO snapshots attributable to one run.

    Forecast snapshots preserve the served model series. Operational
    calibration snapshots preserve the TEPCO values read by that run. The two
    writers execute seconds apart, so a pair is accepted only when the target
    date matches and their generation timestamps are within the configured
    tolerance. Later TEPCO revisions are never substituted.
    """
    settings = _config(config)
    if not settings["enabled"]:
        return {"matched": 0, "imported": 0, "skipped": 0}

    calibration_root = (
        out_dir
        / "reports"
        / "internal"
        / "operational-calibration"
        / "snapshots"
    )
    calibration_by_date: dict[str, list[tuple[pd.Timestamp, dict]]] = {}
    for path in _snapshot_files(calibration_root):
        payload = _read_json(path) or {}
        target_date = payload.get("date")
        generated_at = _timestamp(payload.get("generatedAt"))
        hourly = payload.get("hourlyDiagnostics")
        if not target_date or generated_at is None or not isinstance(hourly, list):
            continue
        calibration_by_date.setdefault(str(target_date), []).append(
            (generated_at, payload)
        )

    existing = _existing_capture_keys(out_dir)
    candidates: list[tuple[pd.Timestamp, dict, dict]] = []
    matched = 0
    skipped = 0
    for path in _snapshot_files(out_dir / "forecast_snapshots"):
        forecast = _read_json(path) or {}
        target_date = str(forecast.get("targetDate") or "")
        generated_at = _timestamp(forecast.get("generatedAt"))
        if not target_date or generated_at is None:
            continue
        capture_key = (target_date, str(forecast.get("generatedAt")))
        if capture_key in existing:
            skipped += 1
            continue
        calibration_candidates = calibration_by_date.get(target_date, [])
        if not calibration_candidates:
            continue
        delta_seconds, calibration = min(
            (
                abs((candidate_ts - generated_at).total_seconds()),
                candidate_payload,
            )
            for candidate_ts, candidate_payload in calibration_candidates
        )
        if delta_seconds > float(max_pair_delta_seconds):
            continue
        matched += 1
        candidates.append((generated_at, forecast, calibration))

    imported = 0
    for _, forecast, calibration in sorted(candidates, key=lambda item: item[0]):
        target_date = date.fromisoformat(str(forecast["targetDate"]))
        capture_key = (target_date.isoformat(), str(forecast["generatedAt"]))
        tepco_series = [
            {
                "ts": row.get("ts"),
                "tepcoForecastMw": row.get("tepcoForecastMw"),
            }
            for row in calibration.get("hourlyDiagnostics", [])
            if row.get("ts") and row.get("tepcoForecastMw") is not None
        ]
        path = append_forecast_vintage_snapshot(
            out_dir,
            target_date,
            generated_at=str(forecast["generatedAt"]),
            run_type=str(forecast.get("runType") or "legacy_snapshot"),
            model=forecast.get("model"),
            model_series=forecast.get("series", []),
            tepco_series=tepco_series,
            config=config,
            capture_origin="legacy_same_run_snapshot_pair",
        )
        if path is not None:
            imported += 1
            existing.add(capture_key)
    return {"matched": matched, "imported": imported, "skipped": skipped}


def _actual_by_ts(out_dir: Path, target_date: date) -> dict[str, float]:
    payload = _read_json(out_dir / "actual" / f"{target_date.isoformat()}.json")
    if not payload:
        return {}
    return {
        str(point["ts"]): float(point["actualMw"])
        for point in payload.get("series", [])
        if point.get("ts")
        and point.get("actualMw") is not None
        and point.get("actualSource") != _FALLBACK_SOURCE
    }


def _lead_bucket(lead_minutes: float) -> str | None:
    for name, lower, upper in DEFAULT_LEAD_BUCKETS:
        if lower < lead_minutes <= upper:
            return name
    return None


def _selected_rows(out_dir: Path) -> list[dict]:
    selected: dict[tuple[str, str], dict] = {}
    ledger_dir = out_dir / _LEDGER_DIR
    for path in sorted(ledger_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            target_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        actual_by_ts = _actual_by_ts(out_dir, target_date)
        if not actual_by_ts:
            continue
        payload = _read_json(path) or {}
        for snapshot in payload.get("snapshots", []):
            for point in snapshot.get("series", []):
                target_ts = str(point.get("ts") or "")
                actual = actual_by_ts.get(target_ts)
                if actual is None:
                    continue
                lead_minutes = float(point.get("leadMinutes", 0.0))
                bucket = _lead_bucket(lead_minutes)
                if bucket is None:
                    continue
                row = {
                    "date": target_date,
                    "hour": int(point.get("hour", target_ts[11:13])),
                    "ts": target_ts,
                    "bucket": bucket,
                    "capturedAt": snapshot.get("capturedAt"),
                    "leadMinutes": lead_minutes,
                    "actual": actual,
                    "model": float(point["modelForecastMw"]),
                    "tepco": float(point["tepcoForecastMw"]),
                }
                key = (bucket, target_ts)
                existing = selected.get(key)
                if existing is None or lead_minutes < existing["leadMinutes"]:
                    selected[key] = row
    return sorted(
        selected.values(),
        key=lambda row: (row["date"], row["hour"], row["bucket"]),
    )


def _metrics(rows: list[dict], field: str) -> dict:
    if not rows:
        return {
            "hours": 0,
            "maeMw": None,
            "wapePct": None,
            "rmseMw": None,
            "maxErrorMw": None,
        }
    actual = np.asarray([row["actual"] for row in rows], dtype=float)
    predicted = np.asarray([row[field] for row in rows], dtype=float)
    errors = predicted - actual
    abs_errors = np.abs(errors)
    denominator = float(np.abs(actual).sum())
    return {
        "hours": len(rows),
        "maeMw": round(float(abs_errors.mean()), 1),
        "wapePct": (
            round(float(abs_errors.sum() / denominator * 100.0), 3)
            if denominator > 0
            else None
        ),
        "rmseMw": round(float(math.sqrt(np.square(errors).mean())), 1),
        "maxErrorMw": round(float(abs_errors.max()), 1),
    }


def _paired_daily_ci(rows: list[dict]) -> dict:
    daily: dict[date, dict[str, list[float]]] = {}
    for row in rows:
        bucket = daily.setdefault(
            row["date"],
            {"model": [], "tepco": []},
        )
        bucket["model"].append(abs(row["model"] - row["actual"]))
        bucket["tepco"].append(abs(row["tepco"] - row["actual"]))
    daily_model = np.asarray(
        [float(np.mean(values["model"])) for values in daily.values()],
        dtype=float,
    )
    daily_tepco = np.asarray(
        [float(np.mean(values["tepco"])) for values in daily.values()],
        dtype=float,
    )
    daily_differences = daily_model - daily_tepco
    result = {
        "dates": int(len(daily_differences)),
        "meanModelMinusTepcoAbsErrorMw": (
            round(float(daily_differences.mean()), 1)
            if len(daily_differences)
            else None
        ),
        "confidenceLevel": 0.95,
        "lowerMw": None,
        "upperMw": None,
        "maeRatioLower": None,
        "maeRatioUpper": None,
        "method": "date_block_bootstrap",
    }
    if len(daily_differences) < 7:
        return result
    rng = np.random.default_rng(42)
    sample_indices = rng.integers(
        0,
        len(daily_differences),
        size=(2000, len(daily_differences)),
    )
    difference_samples = daily_differences[sample_indices].mean(axis=1)
    model_samples = daily_model[sample_indices].mean(axis=1)
    tepco_samples = daily_tepco[sample_indices].mean(axis=1)
    valid_ratio = tepco_samples > 0
    ratio_samples = model_samples[valid_ratio] / tepco_samples[valid_ratio]
    result["lowerMw"] = round(
        float(np.quantile(difference_samples, 0.025)),
        1,
    )
    result["upperMw"] = round(
        float(np.quantile(difference_samples, 0.975)),
        1,
    )
    if len(ratio_samples):
        result["maeRatioLower"] = round(
            float(np.quantile(ratio_samples, 0.025)),
            3,
        )
        result["maeRatioUpper"] = round(
            float(np.quantile(ratio_samples, 0.975)),
            3,
        )
    return result


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator / denominator), 3)


def _bucket_report(rows: list[dict]) -> dict:
    model = _metrics(rows, "model")
    tepco = _metrics(rows, "tepco")
    time_bands: dict[str, dict] = {}
    for name, start, end in TIME_BANDS:
        selected = [row for row in rows if start <= row["hour"] <= end]
        model_band = _metrics(selected, "model")
        tepco_band = _metrics(selected, "tepco")
        time_bands[name] = {
            "model": model_band,
            "tepco": tepco_band,
            "maeRatio": _ratio(model_band["maeMw"], tepco_band["maeMw"]),
        }
    return {
        "dates": len({row["date"] for row in rows}),
        "model": model,
        "tepco": tepco,
        "maeRatio": _ratio(model["maeMw"], tepco["maeMw"]),
        "wapeRatio": _ratio(model["wapePct"], tepco["wapePct"]),
        "rmseRatio": _ratio(model["rmseMw"], tepco["rmseMw"]),
        "maxErrorRatio": _ratio(
            model["maxErrorMw"],
            tepco["maxErrorMw"],
        ),
        "pairedDifference": _paired_daily_ci(rows),
        "timeBands": time_bands,
    }


def _window_report(rows: list[dict], window_days: int) -> dict:
    dates = sorted({row["date"] for row in rows})
    selected_dates = set(dates[-window_days:])
    selected_rows = [row for row in rows if row["date"] in selected_dates]
    return {
        "period": {
            "start": min(selected_dates).isoformat() if selected_dates else None,
            "end": max(selected_dates).isoformat() if selected_dates else None,
            "days": len(selected_dates),
            "requestedDays": window_days,
        },
        "leadBuckets": {
            name: _bucket_report([
                row for row in selected_rows if row["bucket"] == name
            ])
            for name, _, _ in DEFAULT_LEAD_BUCKETS
        },
    }


def _qualification(windows: dict, settings: dict) -> dict:
    failures: list[str] = []
    long_window_days = settings["minimum_qualification_days"]
    required_windows = ("28d", f"{long_window_days}d")
    band_hours = {
        name: end - start + 1
        for name, start, end in TIME_BANDS
    }
    for window_name in required_windows:
        window = windows[window_name]
        requested_days = int(window_name[:-1])
        if window["period"]["days"] < requested_days:
            failures.append(f"{window_name}.insufficient_days")
            continue
        for bucket_name, report in window["leadBuckets"].items():
            if report["dates"] < requested_days:
                failures.append(f"{window_name}.{bucket_name}.insufficient_days")
                continue
            required_bucket_hours = math.ceil(
                requested_days
                * 24
                * settings["minimum_bucket_coverage_ratio"]
            )
            if int(report["model"]["hours"]) < required_bucket_hours:
                failures.append(
                    f"{window_name}.{bucket_name}.insufficient_hours"
                )
                continue
            if (
                report["maeRatio"] is None
                or report["maeRatio"] > settings["non_inferiority_ratio"]
            ):
                failures.append(f"{window_name}.{bucket_name}.mae_ratio")
            if (
                report["wapeRatio"] is None
                or report["wapeRatio"] > settings["non_inferiority_ratio"]
            ):
                failures.append(f"{window_name}.{bucket_name}.wape_ratio")
            if (
                report["rmseRatio"] is None
                or report["rmseRatio"] > settings["max_rmse_ratio"]
            ):
                failures.append(f"{window_name}.{bucket_name}.rmse_ratio")
            if (
                report["maxErrorRatio"] is None
                or report["maxErrorRatio"] > settings["max_max_error_ratio"]
            ):
                failures.append(f"{window_name}.{bucket_name}.max_error_ratio")
            ratio_upper = (report.get("pairedDifference") or {}).get(
                "maeRatioUpper"
            )
            if (
                ratio_upper is None
                or ratio_upper > settings["non_inferiority_ratio"]
            ):
                failures.append(
                    f"{window_name}.{bucket_name}.paired_mae_ratio_ci"
                )
            for band_name, band in report["timeBands"].items():
                ratio = band.get("maeRatio")
                paired_hours = min(
                    int((band.get("model") or {}).get("hours", 0)),
                    int((band.get("tepco") or {}).get("hours", 0)),
                )
                minimum_hours = math.ceil(
                    requested_days
                    * band_hours[band_name]
                    * settings["minimum_bucket_coverage_ratio"]
                )
                if paired_hours < minimum_hours:
                    failures.append(
                        f"{window_name}.{bucket_name}.{band_name}.insufficient_hours"
                    )
                elif ratio is None or ratio > settings["max_segment_ratio"]:
                    failures.append(
                        f"{window_name}.{bucket_name}.{band_name}.mae_ratio"
                    )
    collecting = any(
        failure.endswith(("insufficient_days", "insufficient_hours"))
        for failure in failures
    )
    return {
        "status": (
            "collecting" if collecting
            else "qualified" if not failures
            else "not_qualified"
        ),
        "passed": not failures,
        "failures": failures,
        "thresholds": {
            "requiredWindowsDays": [28, long_window_days],
            "nonInferiorityRatio": settings["non_inferiority_ratio"],
            "maxSegmentMaeRatio": settings["max_segment_ratio"],
            "minimumBucketCoverageRatio": settings[
                "minimum_bucket_coverage_ratio"
            ],
            "maxRmseRatio": settings["max_rmse_ratio"],
            "maxMaxErrorRatio": settings["max_max_error_ratio"],
            "pairedMaeRatioCiUpper": settings["non_inferiority_ratio"],
        },
    }


def build_forecast_vintage_accuracy_report(
    out_dir: Path,
    *,
    generated_at: str,
    config: dict | None = None,
) -> dict:
    """Build same-capture, lead-time matched model-vs-TEPCO metrics."""
    settings = _config(config)
    rows = _selected_rows(out_dir) if settings["enabled"] else []
    long_window_days = settings["minimum_qualification_days"]
    windows = {
        "28d": _window_report(rows, 28),
        f"{long_window_days}d": _window_report(rows, long_window_days),
    }
    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "availability": "ok" if rows else "collecting",
        "methodology": {
            "type": "matched_capture_lead_time_evaluation",
            "sourceTimestamp": "capturedAt",
            "issuedAtAvailable": False,
            "futureTargetsOnly": True,
            "selectionWithinBucket": "minimum_positive_lead_within_bucket",
            "sourcePastRevisionsApplied": False,
            "leadBucketsMinutes": [
                {
                    "name": name,
                    "lowerExclusive": lower,
                    "upperInclusive": upper,
                }
                for name, lower, upper in DEFAULT_LEAD_BUCKETS
            ],
        },
        "coverage": {
            "matchedRows": len(rows),
            "dates": len({row["date"] for row in rows}),
            "retentionDays": settings["retention_days"],
        },
        "windows": windows,
        "qualification": _qualification(windows, settings),
    }
