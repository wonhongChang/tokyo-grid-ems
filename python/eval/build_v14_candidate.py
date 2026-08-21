"""Build the source-robust v14-r2 hourly model candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python.eval.model_validation import artifact_sha256
from python.forecast.lgbm_model import LGBMForecaster


HOURLY_ESTIMATOR_ATTRIBUTES = (
    "model_q025",
    "model_q50",
    "model_q975",
    "model_q50_lag24_residual",
    "model_q50_lag_unavailable",
    "model_q50_lag_unavailable_non_business",
)


def hourly_estimator_fingerprints(
    forecaster: LGBMForecaster,
) -> dict[str, str]:
    """Return stable hashes for the hourly LightGBM booster payloads."""
    fingerprints: dict[str, str] = {}
    for attribute in HOURLY_ESTIMATOR_ATTRIBUTES:
        estimator = getattr(forecaster, attribute, None)
        booster = getattr(estimator, "booster_", None)
        if booster is None:
            raise ValueError(f"Champion hourly estimator is missing: {attribute}")
        payload = booster.model_to_string().encode("utf-8")
        fingerprints[attribute] = hashlib.sha256(payload).hexdigest()
    for view_name, view in sorted(
        (getattr(forecaster, "q50_feature_views", None) or {}).items()
    ):
        for model_name in ("direct", "lag24_residual", "non_business"):
            estimator = view.get(model_name)
            booster = getattr(estimator, "booster_", None)
            if booster is None:
                raise ValueError(
                    f"Candidate q50 view estimator is missing: {view_name}.{model_name}"
                )
            payload = booster.model_to_string().encode("utf-8")
            fingerprints[f"q50_feature_views.{view_name}.{model_name}"] = (
                hashlib.sha256(payload).hexdigest()
            )
    return fingerprints


def candidate_config(champion_config: dict, project_config: dict) -> dict:
    """Return the complete project contract used by the rebuilt candidate."""
    del champion_config
    result = json.loads(json.dumps(project_config))
    forecast = result.get("forecast", {})
    required = {
        "lag24_residual_ensemble",
        "q50_regime_model",
        "q50_feature_view_ensemble",
        "same_regime_day_level_calibration",
        "daily_level_model",
        "partial_lag_q50_fallback",
    }
    missing = sorted(required.difference(forecast))
    if missing:
        raise ValueError(
            "Project config is missing forecast blocks: " + ", ".join(missing)
        )
    if forecast["daily_level_model"].get("enabled", False):
        raise ValueError("v14-r2 requires forecast.daily_level_model.enabled=false.")
    if not forecast["q50_feature_view_ensemble"].get("enabled", False):
        raise ValueError("v14-r2 q50 feature-view ensemble must be enabled.")
    return result


def build_candidate(
    champion: LGBMForecaster,
    training_cache: pd.DataFrame,
    project_config: dict,
) -> LGBMForecaster:
    """Return a fully retrained v14-r2 candidate under the project contract."""
    candidate = LGBMForecaster(
        n_estimators=int(getattr(champion, "n_estimators", 500)),
        learning_rate=float(getattr(champion, "learning_rate", 0.05)),
        config=candidate_config(champion.config, project_config),
    )
    candidate.fit(training_cache)
    if candidate.interval_version != LGBMForecaster.INTERVAL_VERSION:
        raise RuntimeError("v14-r2 candidate did not activate the current contract.")
    if not candidate.is_compatible():
        raise RuntimeError("v14-r2 candidate is incompatible after training.")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--champion", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cutoff",
        help="Exclusive JST training cutoff, for example 2026-08-20.",
    )
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()

    cache = pd.read_parquet(args.cache)
    cache["ts"] = pd.to_datetime(cache["ts"], utc=True).dt.tz_convert(
        "Asia/Tokyo"
    )
    cache = (
        cache.sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    if args.cutoff:
        cutoff = pd.Timestamp(args.cutoff, tz="Asia/Tokyo")
        cache = cache.loc[cache["ts"] < cutoff].copy()

    project_config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    champion = LGBMForecaster.load(args.champion)
    candidate = build_candidate(champion, cache, project_config)
    candidate.save(args.output)

    metadata = {
        "schemaVersion": "1.0.0",
        "strategy": (
            "retrain_source_robust_q50_with_lag_unavailable_day_ahead"
        ),
        "sourceChampionSha256": artifact_sha256(args.champion),
        "artifactSha256": artifact_sha256(args.output),
        "sourceIntervalVersion": champion.interval_version,
        "candidateIntervalVersion": candidate.interval_version,
        "estimatorSha256": hourly_estimator_fingerprints(candidate),
        "dailyLevelTrainingDays": candidate.daily_level_training_days,
        "trainingCutoffExclusive": args.cutoff,
    }
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()
