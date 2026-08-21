"""Promote the exact artifact that passed fixed-origin recovery replay."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python.eval.build_v14_candidate import hourly_estimator_fingerprints
from python.eval.model_validation import (
    artifact_sha256,
    config_fingerprint,
    prediction_drift_report,
)
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


def _validate_evidence(
    candidate_path: Path,
    candidate: LGBMForecaster,
    champion_sha256: str,
    same_day_development: dict,
    same_day_holdout: dict,
    day_ahead_development: dict,
    day_ahead_holdout: dict,
) -> None:
    reports = (
        ("same-day development", same_day_development, "development", 0),
        ("same-day holdout", same_day_holdout, "holdout", 0),
        ("day-ahead development", day_ahead_development, "development", 1),
        ("day-ahead holdout", day_ahead_holdout, "holdout", 1),
    )
    candidate_hash = artifact_sha256(candidate_path)
    for label, report, phase, origin_lead_days in reports:
        if report.get("phase") != phase:
            raise ValueError(f"{label} evidence has the wrong phase.")
        if (report.get("gate") or {}).get("passed") is not True:
            raise ValueError(f"{label} fixed-origin gate did not pass.")
        methodology = report.get("methodology") or {}
        if methodology.get("originLeadDays") != origin_lead_days:
            raise ValueError(f"{label} evidence has the wrong forecast origin.")
        artifact = report.get("candidateArtifact") or {}
        if artifact.get("intervalVersion") != candidate.interval_version:
            raise ValueError(f"{label} evidence has a different model contract.")

    development_hashes = {
        (same_day_development.get("candidateArtifact") or {}).get("sha256"),
        (day_ahead_development.get("candidateArtifact") or {}).get("sha256"),
    }
    if len(development_hashes) != 1 or None in development_hashes:
        raise ValueError("Development evidence artifacts do not match.")
    for label, report in (
        ("same-day holdout", same_day_holdout),
        ("day-ahead holdout", day_ahead_holdout),
    ):
        artifact = report.get("candidateArtifact") or {}
        if artifact.get("sha256") != candidate_hash:
            raise ValueError(
                f"{label} evidence does not match the exact candidate artifact."
            )
        baseline_artifact = report.get("baselineArtifact") or {}
        if baseline_artifact.get("sha256") != champion_sha256:
            raise ValueError(
                f"{label} evidence does not match the deployed Champion."
            )


def _smoke_test(
    candidate: LGBMForecaster,
    cache: pd.DataFrame,
    target_dates: list[date],
) -> dict:
    failures: list[dict] = []
    for target in target_dates:
        try:
            forecasts = candidate.predict(target, cache.copy())
        except Exception as exc:
            failures.append({"date": target.isoformat(), "reason": str(exc)})
            continue
        if len(forecasts) != 24:
            failures.append({"date": target.isoformat(), "reason": "row_count"})
            continue
        if any(
            not np.isfinite([
                point.forecast_mw,
                point.p95_lower_mw,
                point.p95_upper_mw,
                point.p99_lower_mw,
                point.p99_upper_mw,
            ]).all()
            for point in forecasts
        ):
            failures.append({"date": target.isoformat(), "reason": "non_finite"})
    return {
        "passed": not failures,
        "dates": [target.isoformat() for target in target_dates],
        "failures": failures,
    }


def promote(
    *,
    candidate_path: Path,
    out_dir: Path,
    cache: pd.DataFrame,
    config: dict,
    same_day_development: dict,
    same_day_holdout: dict,
    day_ahead_development: dict,
    day_ahead_holdout: dict,
    target_date: date,
    approve: bool,
    allow_large_drift: bool,
) -> dict:
    if not approve:
        raise PermissionError("Explicit --approve is required.")
    model_path = out_dir / ".lgbm_model.pkl"
    metadata_path = out_dir / ".lgbm_model_meta.json"
    if not model_path.exists():
        raise FileNotFoundError("Current Champion artifact is missing.")

    champion = LGBMForecaster.load(model_path)
    candidate = LGBMForecaster.load(candidate_path)
    champion_hash = artifact_sha256(model_path)
    if not candidate.is_compatible():
        raise ValueError("Candidate artifact is incompatible.")
    if candidate.interval_version != LGBMForecaster.INTERVAL_VERSION:
        raise ValueError("Candidate does not implement the current contract.")
    if config_fingerprint(candidate.config) != config_fingerprint(config):
        raise ValueError("Candidate artifact config differs from project config.")
    _validate_evidence(
        candidate_path,
        candidate,
        champion_hash,
        same_day_development,
        same_day_holdout,
        day_ahead_development,
        day_ahead_holdout,
    )

    normalized_cache = cache.copy()
    normalized_cache["ts"] = pd.to_datetime(
        normalized_cache["ts"],
        utc=True,
    ).dt.tz_convert("Asia/Tokyo")
    target_dates = [target_date, target_date + timedelta(days=1)]
    smoke = _smoke_test(candidate, normalized_cache, target_dates)
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
            "Prediction drift exceeds limits; --allow-large-drift is required."
        )
    drift_override_basis = None
    if drift_failures:
        same_day_gate = same_day_holdout.get("gate") or {}
        day_ahead_gate = day_ahead_holdout.get("gate") or {}
        minimum_same_day = float(
            promotion_config.get(
                "large_drift_override_min_same_day_improvement_pct",
                8.0,
            )
        )
        minimum_day_ahead = float(
            promotion_config.get(
                "large_drift_override_min_day_ahead_improvement_pct",
                20.0,
            )
        )
        strong_exact_recovery = (
            same_day_gate.get("mode") == "strict_mae_recovery"
            and day_ahead_gate.get("mode") == "strict_mae_recovery"
            and float(same_day_gate.get("maeImprovementPct", 0.0))
            >= minimum_same_day
            and float(day_ahead_gate.get("maeImprovementPct", 0.0))
            >= minimum_day_ahead
        )
        if not strong_exact_recovery:
            raise PermissionError(
                "Large drift override requires strong exact-Champion D0 and D-1 "
                "holdout recovery."
            )
        drift_override_basis = {
            "sameDayMaeImprovementPct": same_day_gate["maeImprovementPct"],
            "dayAheadMaeImprovementPct": day_ahead_gate["maeImprovementPct"],
            "minimumSameDayMaeImprovementPct": minimum_same_day,
            "minimumDayAheadMaeImprovementPct": minimum_day_ahead,
        }

    generated_at = pd.Timestamp.now(
        tz="Asia/Tokyo"
    ).isoformat(timespec="seconds")
    candidate_hash = artifact_sha256(candidate_path)
    rollback_path = out_dir / ".lgbm_model.rollback.pkl"
    rollback_metadata_path = out_dir / ".lgbm_model.rollback_meta.json"
    shutil.copy2(model_path, rollback_path)
    if metadata_path.exists():
        shutil.copy2(metadata_path, rollback_metadata_path)

    staged_model = out_dir / ".lgbm_model.pkl.fixed-origin-approved"
    staged_metadata = out_dir / ".lgbm_model_meta.json.fixed-origin-approved"
    shutil.copy2(candidate_path, staged_model)
    metadata = {
        "schemaVersion": "3.0.0",
        "createdAt": generated_at,
        "promotedAt": generated_at,
        "promotionMode": "fixed_origin_recovery",
        "trainingCutoff": same_day_holdout["trainingCutoffExclusive"],
        "intervalVersion": candidate.interval_version,
        "configFingerprint": config_fingerprint(config),
        "artifactConfigFingerprint": config_fingerprint(candidate.config),
        "artifactSha256": candidate_hash,
        "estimatorSha256": hourly_estimator_fingerprints(candidate),
        "validationPeriod": same_day_holdout["validationPeriod"],
    }
    _write_json(staged_metadata, metadata)
    os.replace(staged_model, model_path)
    os.replace(staged_metadata, metadata_path)

    calibration_config = config["forecast"]["same_regime_day_level_calibration"]
    state_path = out_dir / str(calibration_config["state_path"])
    residuals = list(same_day_holdout.get("dailyRawResiduals") or [])
    state = {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "updatedAt": generated_at,
        "modelContract": config["forecast"]["model_contract"],
        "artifactSha256": candidate_hash,
        "validFromDate": same_day_holdout["validationPeriod"]["start"],
        "entries": [
            {
                "date": entry["date"],
                "isNonBusinessDay": entry["isNonBusinessDay"],
                "meanResidualMw": entry["meanResidualMw"],
                "originGeneratedAt": entry["originGeneratedAt"],
                "source": "fixed_origin_holdout_seed",
            }
            for entry in residuals
        ],
    }
    _write_json(state_path, state)

    comparison = {
        "schemaVersion": "3.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "methodology": "git_preserved_fixed_origin",
        "candidateArtifact": {
            "sha256": candidate_hash,
            "intervalVersion": candidate.interval_version,
        },
        "sameDay": {
            "development": {
                "period": same_day_development["validationPeriod"],
                "baseline": same_day_development["baseline"],
                "candidate": same_day_development["candidate"],
                "gate": same_day_development["gate"],
            },
            "holdout": {
                "period": same_day_holdout["validationPeriod"],
                "baseline": same_day_holdout["baseline"],
                "candidate": same_day_holdout["candidate"],
                "gate": same_day_holdout["gate"],
            },
        },
        "dayAhead": {
            "development": {
                "period": day_ahead_development["validationPeriod"],
                "baseline": day_ahead_development["baseline"],
                "candidate": day_ahead_development["candidate"],
                "gate": day_ahead_development["gate"],
            },
            "holdout": {
                "period": day_ahead_holdout["validationPeriod"],
                "baseline": day_ahead_holdout["baseline"],
                "candidate": day_ahead_holdout["candidate"],
                "gate": day_ahead_holdout["gate"],
            },
        },
        "decision": "promoted",
    }
    _write_json(out_dir / "metrics" / "model_contract_comparison.json", comparison)

    previous_path = out_dir / "metrics" / "model_promotion.json"
    previous = _read_json(previous_path) if previous_path.exists() else None
    report = {
        "schemaVersion": "3.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "status": "recovery_promoted",
        "reason": "fixed_origin_development_and_holdout_gates_passed",
        "champion": {
            "artifact": ".lgbm_model.pkl",
            "sha256": candidate_hash,
            "intervalVersion": candidate.interval_version,
            "trainingCutoff": same_day_holdout["trainingCutoffExclusive"],
        },
        "rollback": {
            "artifact": ".lgbm_model.rollback.pkl",
            "sha256": artifact_sha256(rollback_path),
            "intervalVersion": getattr(champion, "interval_version", None),
            "sourceChampionSha256": champion_hash,
        },
        "validation": {
            "sameDayDevelopmentGate": same_day_development["gate"],
            "sameDayHoldoutGate": same_day_holdout["gate"],
            "dayAheadDevelopmentGate": day_ahead_development["gate"],
            "dayAheadHoldoutGate": day_ahead_holdout["gate"],
            "comparisonReport": "metrics/model_contract_comparison.json",
        },
        "smokeTest": smoke,
        "predictionDrift": drift,
        "driftFailures": drift_failures,
        "driftOverrideApproved": bool(drift_failures and allow_large_drift),
        "driftOverrideBasis": drift_override_basis,
        "postPromotionMonitoring": {
            "rollbackArtifactReady": True,
            "reviewAfterFinalizedDays": 3,
        },
        "lastEvaluation": previous,
    }
    _write_json(previous_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--same-day-development", type=Path, required=True)
    parser.add_argument("--same-day-holdout", type=Path, required=True)
    parser.add_argument("--day-ahead-development", type=Path, required=True)
    parser.add_argument("--day-ahead-holdout", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("web/public"))
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("web/public/.hourly_cache.parquet"),
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--target-date", type=date.fromisoformat, required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--allow-large-drift", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    report = promote(
        candidate_path=args.candidate,
        out_dir=args.out_dir,
        cache=pd.read_parquet(args.cache),
        config=config,
        same_day_development=_read_json(args.same_day_development),
        same_day_holdout=_read_json(args.same_day_holdout),
        day_ahead_development=_read_json(args.day_ahead_development),
        day_ahead_holdout=_read_json(args.day_ahead_holdout),
        target_date=args.target_date,
        approve=args.approve,
        allow_large_drift=args.allow_large_drift,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
