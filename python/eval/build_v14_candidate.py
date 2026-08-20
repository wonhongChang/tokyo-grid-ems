"""Build v14 auxiliary calibrators without replacing champion hourly models."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from python.eval.model_validation import artifact_sha256
from python.forecast.lgbm_model import LGBMForecaster


HOURLY_ESTIMATOR_ATTRIBUTES = (
    "model_q025",
    "model_q50",
    "model_q975",
    "model_q50_lag24_residual",
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
    return fingerprints


def candidate_config(champion_config: dict, project_config: dict) -> dict:
    """Copy only v14 calibrator settings onto the champion model contract."""
    result = copy.deepcopy(champion_config)
    result.setdefault("forecast", {})
    source = project_config.get("forecast", {})
    for key in (
        "q50_regime_model",
        "daily_level_model",
        "partial_lag_q50_fallback",
    ):
        if key not in source:
            raise ValueError(f"Project config is missing forecast.{key}.")
        result["forecast"][key] = copy.deepcopy(source[key])
    return result


def build_candidate(
    champion: LGBMForecaster,
    training_cache: pd.DataFrame,
    project_config: dict,
) -> LGBMForecaster:
    """Return a v14 candidate that preserves the champion hourly estimators."""
    source_fingerprints = hourly_estimator_fingerprints(champion)
    candidate = copy.deepcopy(champion)
    candidate.config = candidate_config(champion.config, project_config)
    candidate.fit_v14_calibrators(training_cache)
    if hourly_estimator_fingerprints(candidate) != source_fingerprints:
        raise RuntimeError("v14 calibration changed a champion hourly estimator.")
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
            "preserve_champion_hourly_add_non_business_and_daily_calibrators"
        ),
        "sourceChampionSha256": artifact_sha256(args.champion),
        "artifactSha256": artifact_sha256(args.output),
        "sourceIntervalVersion": champion.interval_version,
        "candidateIntervalVersion": candidate.interval_version,
        "hourlyEstimatorSha256": hourly_estimator_fingerprints(candidate),
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
