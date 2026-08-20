"""Explicitly promote a replay-qualified recovery model artifact."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from python.eval.model_validation import (
    artifact_sha256,
    config_fingerprint,
    prediction_drift_report,
)
from python.eval.build_v14_candidate import hourly_estimator_fingerprints
from python.forecast.lgbm_model import LGBMForecaster


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _overall(report: dict, key: str) -> dict:
    metrics = report.get(key) or {}
    overall = metrics.get("overall") or {}
    if not overall:
        raise ValueError(f"Validation report is missing {key}.overall.")
    return overall


def _validate_replay_evidence(reports: dict[int, dict]) -> None:
    if sorted(reports) != [28, 56, 84]:
        raise ValueError("Recovery promotion requires 28, 56, and 84-day reports.")
    primary = reports[28]
    if (primary.get("recoveryGate") or {}).get("passed") is not True:
        raise ValueError("The 28-day degraded-Champion recovery gate did not pass.")
    for window_days, report in reports.items():
        period_days = int((report.get("validationPeriod") or {}).get("days") or 0)
        if period_days != window_days:
            raise ValueError(
                f"Expected a {window_days}-day report, got {period_days} days."
            )
        candidate = _overall(report, "candidate")
        champion = _overall(report, "championContract")
        for metric in ("maeMw", "wapePct"):
            if float(candidate[metric]) > float(champion[metric]):
                raise ValueError(
                    f"{window_days}d candidate regressed on {metric}."
                )


def _validate_v13_evidence(
    reports: dict[int, dict],
    experiments: dict[int, dict],
) -> None:
    """Require v14 to improve the superseded v13 contract as well as v11."""
    if sorted(experiments) != [28, 56, 84]:
        raise ValueError("Recovery promotion requires 28, 56, and 84-day v13 evidence.")
    for window_days in (28, 56, 84):
        v14 = _overall(reports[window_days], "candidate")
        experiment = experiments[window_days]
        v13 = (
            experiment.get("featureSets", {})
            .get("all63", {})
            .get("metrics", {})
            .get("v13_contract", {})
            .get("overall", {})
        )
        if not v13:
            raise ValueError(f"The {window_days}d experiment is missing v13 metrics.")
        for metric in ("maeMw", "wapePct"):
            if float(v14[metric]) > float(v13[metric]):
                raise ValueError(
                    f"{window_days}d v14 regressed versus v13 on {metric}."
                )


def _finite_smoke_test(
    model: LGBMForecaster,
    cache: pd.DataFrame,
    target_dates: list[date],
) -> dict:
    failures: list[dict] = []
    for target in target_dates:
        points = model.predict(target, cache.copy())
        if len(points) != 24:
            failures.append({"date": target.isoformat(), "reason": "row_count"})
            continue
        for hour, point in enumerate(points):
            values = (
                point.forecast_mw,
                point.p95_lower_mw,
                point.p95_upper_mw,
                point.p99_lower_mw,
                point.p99_upper_mw,
            )
            if not np.isfinite(values).all():
                failures.append({
                    "date": target.isoformat(),
                    "hour": hour,
                    "reason": "non_finite",
                })
    return {
        "passed": not failures,
        "dates": [target.isoformat() for target in target_dates],
        "failures": failures,
    }


def _comparison_payload(
    reports: dict[int, dict],
    experiments: dict[int, dict],
    *,
    generated_at: str,
    artifact_hash: str,
    interval_version: str,
) -> dict:
    windows: dict[str, dict] = {}
    for days, report in reports.items():
        experiment = experiments[days]
        v13 = (
            experiment.get("featureSets", {})
            .get("all63", {})
            .get("metrics", {})
            .get("v13_contract", {})
        )
        if not v13:
            raise ValueError(f"The {days}d experiment is missing v13 metrics.")
        v11 = report["championContract"]
        v14 = report["candidate"]
        windows[f"{days}d"] = {
            "validationPeriod": report.get("validationPeriod"),
            "v11": v11,
            "v13": v13,
            "v14": v14,
            "v14ImprovementPct": {
                "vsV11Mae": round(
                    (v11["overall"]["maeMw"] - v14["overall"]["maeMw"])
                    / v11["overall"]["maeMw"]
                    * 100.0,
                    2,
                ),
                "vsV13Mae": round(
                    (v13["overall"]["maeMw"] - v14["overall"]["maeMw"])
                    / v13["overall"]["maeMw"]
                    * 100.0,
                    2,
                ),
            },
        }
    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "methodology": {
            "type": "same_cutoff_contract_replay",
            "weatherContext": "final_observed_weather",
            "targetDayDemandLeakage": "removed",
            "note": (
                "The primary v14 contract is compared with v11 and v13 at "
                "matching training cutoffs. Partial-lag behavior is smoke-tested "
                "separately because finalized replay has complete lag24 coverage."
            ),
        },
        "candidateArtifact": {
            "sha256": artifact_hash,
            "intervalVersion": interval_version,
        },
        "windows": windows,
        "decision": "recovery_promoted",
    }


def promote_recovery_candidate(
    *,
    candidate_path: Path,
    out_dir: Path,
    config: dict,
    reports: dict[int, dict],
    experiments: dict[int, dict],
    cache: pd.DataFrame,
    training_cutoff: str,
    target_date: date,
    approve_recovery: bool,
    allow_large_drift: bool,
) -> dict:
    """Promote an exact artifact after explicit degraded-Champion approval."""
    if not approve_recovery:
        raise PermissionError("Explicit --approve-recovery is required.")
    _validate_replay_evidence(reports)
    _validate_v13_evidence(reports, experiments)

    model_path = out_dir / ".lgbm_model.pkl"
    metadata_path = out_dir / ".lgbm_model_meta.json"
    rollback_path = out_dir / ".lgbm_model.rollback.pkl"
    rollback_metadata_path = out_dir / ".lgbm_model.rollback_meta.json"
    if not model_path.exists():
        raise FileNotFoundError("Current Champion artifact is missing.")
    champion = LGBMForecaster.load(model_path)
    candidate = LGBMForecaster.load(candidate_path)
    if not candidate.is_compatible():
        raise ValueError("Candidate artifact is incompatible.")
    if candidate.interval_version != LGBMForecaster.INTERVAL_VERSION:
        raise ValueError("Candidate does not implement the current model contract.")
    champion_hourly_hashes = hourly_estimator_fingerprints(champion)
    candidate_hourly_hashes = hourly_estimator_fingerprints(candidate)
    if candidate_hourly_hashes != champion_hourly_hashes:
        raise ValueError("Recovery candidate changed a Champion hourly estimator.")

    normalized_cache = cache.copy()
    normalized_cache["ts"] = pd.to_datetime(
        normalized_cache["ts"],
        utc=True,
    ).dt.tz_convert("Asia/Tokyo")
    target_dates = [target_date, target_date + timedelta(days=1)]
    smoke = _finite_smoke_test(candidate, normalized_cache, target_dates)
    if not smoke["passed"]:
        raise ValueError("Candidate failed the current/tomorrow smoke test.")
    drift = prediction_drift_report(
        champion,
        candidate,
        normalized_cache,
        target_dates,
    )
    promotion_config = config.get("model_promotion", {})
    drift_failures: list[str] = []
    if not drift.get("valid", False):
        drift_failures.append("prediction_drift_invalid")
    if float(drift.get("meanAbsDeltaMw") or 0.0) > float(
        promotion_config.get("max_mean_prediction_drift_mw", 900)
    ):
        drift_failures.append("mean_prediction_drift_exceeded")
    if float(drift.get("maxAbsDeltaMw") or 0.0) > float(
        promotion_config.get("max_hour_prediction_drift_mw", 2500)
    ):
        drift_failures.append("hour_prediction_drift_exceeded")
    if "prediction_drift_invalid" in drift_failures:
        raise ValueError("Candidate prediction drift is invalid.")
    if drift_failures and not allow_large_drift:
        raise PermissionError(
            "Prediction drift exceeds limits; explicit --allow-large-drift is required."
        )

    candidate_hash = artifact_sha256(candidate_path)
    champion_hash = artifact_sha256(model_path)
    generated_at = pd.Timestamp.now(tz="Asia/Tokyo").isoformat(timespec="seconds")
    comparison = _comparison_payload(
        reports,
        experiments,
        generated_at=generated_at,
        artifact_hash=candidate_hash,
        interval_version=candidate.interval_version,
    )

    staged_model = out_dir / ".lgbm_model.pkl.recovery-approved"
    staged_metadata = out_dir / ".lgbm_model_meta.json.recovery-approved"
    shutil.copy2(candidate_path, staged_model)
    metadata = {
        "schemaVersion": "2.0.0",
        "createdAt": generated_at,
        "promotedAt": generated_at,
        "promotionMode": "operator_replay_recovery",
        "trainingCutoff": training_cutoff,
        "intervalVersion": candidate.interval_version,
        "configFingerprint": config_fingerprint(config),
        "artifactConfigFingerprint": config_fingerprint(candidate.config),
        "artifactSha256": candidate_hash,
        "hourlyEstimatorSha256": candidate_hourly_hashes,
        "validationPeriod": reports[28].get("validationPeriod"),
        "validationWindows": [28, 56, 84],
    }
    _write_json(staged_metadata, metadata)

    shutil.copy2(model_path, rollback_path)
    if metadata_path.exists():
        shutil.copy2(metadata_path, rollback_metadata_path)
    os.replace(staged_model, model_path)
    os.replace(staged_metadata, metadata_path)
    _write_json(out_dir / "metrics" / "model_contract_comparison.json", comparison)

    previous_report = _read_json(out_dir / "metrics" / "model_promotion.json")
    report = {
        "schemaVersion": "2.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "status": "recovery_promoted",
        "reason": "operator_approved_replay_recovery",
        "champion": {
            "artifact": ".lgbm_model.pkl",
            "sha256": artifact_sha256(model_path),
            "intervalVersion": candidate.interval_version,
            "trainingCutoff": training_cutoff,
            "hourlyEstimatorSha256": candidate_hourly_hashes,
        },
        "rollback": {
            "artifact": ".lgbm_model.rollback.pkl",
            "sha256": artifact_sha256(rollback_path),
            "intervalVersion": getattr(champion, "interval_version", None),
            "sourceChampionSha256": champion_hash,
        },
        "validation": {
            "28dRecoveryGate": reports[28].get("recoveryGate"),
            "comparisonReport": "metrics/model_contract_comparison.json",
        },
        "smokeTest": smoke,
        "predictionDrift": drift,
        "driftFailures": drift_failures,
        "driftOverrideApproved": bool(drift_failures and allow_large_drift),
        "postPromotionMonitoring": {
            "requiredHours": 72,
            "rollbackOnMaterialRegression": True,
        },
        "lastEvaluation": previous_report,
    }
    _write_json(out_dir / "metrics" / "model_promotion.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("web/public"))
    parser.add_argument("--cache", type=Path, default=Path("web/public/.hourly_cache.parquet"))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--training-cutoff", required=True)
    parser.add_argument("--target-date", type=date.fromisoformat, required=True)
    for days in (28, 56, 84):
        parser.add_argument(f"--validation-{days}", type=Path, required=True)
        parser.add_argument(f"--experiment-{days}", type=Path, required=True)
    parser.add_argument("--approve-recovery", action="store_true")
    parser.add_argument("--allow-large-drift", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    reports = {
        days: _read_json(getattr(args, f"validation_{days}"))
        for days in (28, 56, 84)
    }
    experiments = {
        days: _read_json(getattr(args, f"experiment_{days}"))
        for days in (28, 56, 84)
    }
    cache = pd.read_parquet(args.cache)
    report = promote_recovery_candidate(
        candidate_path=args.candidate,
        out_dir=args.out_dir,
        config=config,
        reports=reports,
        experiments=experiments,
        cache=cache,
        training_cutoff=args.training_cutoff,
        target_date=args.target_date,
        approve_recovery=args.approve_recovery,
        allow_large_drift=args.allow_large_drift,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
