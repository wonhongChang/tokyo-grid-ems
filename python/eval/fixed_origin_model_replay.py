"""Replay an exact model artifact against Git-preserved forecast origins."""
from __future__ import annotations

import argparse
import copy
import io
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python.eval.model_validation import (
    _metric_bundle,
    artifact_sha256,
    config_fingerprint,
)
from python.forecast.feature_builder import _is_nonworking
from python.forecast.lgbm_model import LGBMForecaster


JST = ZoneInfo("Asia/Tokyo")


def _git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    payload = subprocess.check_output(["git", *args], cwd=repo)
    return payload if binary else payload.decode("utf-8").strip()


def _origin_commit(
    repo: Path,
    target: date,
    origin_lead_days: int = 0,
) -> tuple[str, str]:
    path = f"forecast_snapshots/{target.isoformat()}"
    output = _git(
        repo,
        "log",
        "origin/data",
        "--diff-filter=A",
        "--reverse",
        "--format=%H%x09%cI",
        "--",
        path,
    )
    origin_date = target - timedelta(days=origin_lead_days)
    midnight = pd.Timestamp(origin_date, tz=JST)
    next_midnight = midnight + pd.Timedelta(days=1)
    candidates: list[tuple[str, pd.Timestamp]] = []
    for line in str(output).splitlines():
        if "\t" not in line:
            continue
        commit, timestamp = line.split("\t", 1)
        captured = pd.Timestamp(timestamp).tz_convert(JST)
        if midnight <= captured < next_midnight:
            candidates.append((commit, captured))
    if not candidates:
        raise RuntimeError(
            f"No D-{origin_lead_days} origin cache found for {target}."
        )
    commit, captured = min(candidates, key=lambda item: item[1])
    return commit, captured.isoformat()


def _cache_at(repo: Path, commit: str) -> pd.DataFrame:
    payload = _git(
        repo,
        "show",
        f"{commit}:.hourly_cache.parquet",
        binary=True,
    )
    cache = pd.read_parquet(io.BytesIO(payload))
    cache["ts"] = pd.to_datetime(cache["ts"], utc=True).dt.tz_convert(JST)
    return (
        cache.sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )


def _normalized_cache(path: Path) -> pd.DataFrame:
    cache = pd.read_parquet(path)
    cache["ts"] = pd.to_datetime(cache["ts"], utc=True).dt.tz_convert(JST)
    return (
        cache.sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )


def _actuals(cache: pd.DataFrame, target: date) -> dict[int, float]:
    mask = (cache["ts"].dt.date == target) & cache["actual_mw"].notna()
    if "actual_source" in cache.columns:
        mask &= (
            cache["actual_source"].fillna("observed")
            != "tepco_forecast_fallback"
        )
    return {
        int(row.ts.hour): float(row.actual_mw)
        for row in cache.loc[mask].sort_values("ts").itertuples()
    }


def _origin_inference_cache(
    cache: pd.DataFrame,
    target: date,
    captured_at: str | pd.Timestamp,
) -> pd.DataFrame:
    result = cache.copy()
    captured = pd.Timestamp(captured_at)
    captured = (
        captured.tz_localize(JST)
        if captured.tzinfo is None
        else captured.tz_convert(JST)
    )
    knowledge_cutoff = captured.floor("h")
    unavailable_mask = result["ts"] >= knowledge_cutoff
    result.loc[unavailable_mask, "actual_mw"] = np.nan
    if "actual_source" in result.columns:
        result.loc[unavailable_mask, "actual_source"] = None
    target_mask = result["ts"].dt.date == target
    result.loc[target_mask, "actual_mw"] = np.nan
    if "actual_source" in result.columns:
        result.loc[target_mask, "actual_source"] = None
    return result


def _baseline_config(config: dict) -> dict:
    result = copy.deepcopy(config)
    forecast = result.setdefault("forecast", {})
    forecast.setdefault("q50_feature_view_ensemble", {})["enabled"] = False
    forecast.setdefault("q50_regime_model", {})["enabled"] = False
    forecast.setdefault("daily_level_model", {})["enabled"] = False
    forecast.setdefault("lag24_residual_ensemble", {}).setdefault(
        "transition_cooling_attenuation",
        {},
    )["enabled"] = False
    forecast.setdefault("partial_lag_q50_fallback", {})[
        "lag_unavailable_models_enabled"
    ] = False
    return result


def _train_baseline(
    cache: pd.DataFrame,
    config: dict,
    cutoff: date,
    n_estimators: int,
    learning_rate: float,
) -> LGBMForecaster:
    training = cache.loc[cache["ts"] < pd.Timestamp(cutoff, tz=JST)].copy()
    model = LGBMForecaster(
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        config=_baseline_config(config),
    )
    model.fit(training)
    return model


def _metrics(rows: list[dict]) -> dict:
    return _metric_bundle(rows)


def _daily_metrics(rows: list[dict], start: date, end: date) -> dict:
    return {
        target.isoformat(): _metric_bundle([
            row for row in rows if row["date"] == target
        ])["overall"]
        for target in pd.date_range(start, end, freq="D").date
    }


def _interval_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {
            "hours": 0,
            "p95CoveragePct": None,
            "p99CoveragePct": None,
            "meanP95WidthMw": None,
            "meanP99WidthMw": None,
        }
    actual = np.asarray([row["actual"] for row in rows], dtype=float)
    p95_lower = np.asarray([row["p95Lower"] for row in rows], dtype=float)
    p95_upper = np.asarray([row["p95Upper"] for row in rows], dtype=float)
    p99_lower = np.asarray([row["p99Lower"] for row in rows], dtype=float)
    p99_upper = np.asarray([row["p99Upper"] for row in rows], dtype=float)
    values = np.concatenate([actual, p95_lower, p95_upper, p99_lower, p99_upper])
    if not np.isfinite(values).all():
        raise ValueError("Interval metrics require finite values.")
    return {
        "hours": len(rows),
        "p95CoveragePct": round(float(np.mean(
            (actual >= p95_lower) & (actual <= p95_upper)
        ) * 100.0), 2),
        "p99CoveragePct": round(float(np.mean(
            (actual >= p99_lower) & (actual <= p99_upper)
        ) * 100.0), 2),
        "meanP95WidthMw": round(float(np.mean(p95_upper - p95_lower)), 1),
        "meanP99WidthMw": round(float(np.mean(p99_upper - p99_lower)), 1),
    }


def _paired_daily_mae_bootstrap(
    baseline_rows: list[dict],
    candidate_rows: list[dict],
    *,
    iterations: int = 20_000,
    seed: int = 20260821,
) -> dict:
    """Return a deterministic date-block bootstrap for paired daily MAE."""
    baseline = pd.DataFrame(baseline_rows)
    candidate = pd.DataFrame(candidate_rows)
    baseline["absError"] = (baseline["predicted"] - baseline["actual"]).abs()
    candidate["absError"] = (candidate["predicted"] - candidate["actual"]).abs()
    baseline_daily = baseline.groupby("date")["absError"].mean()
    candidate_daily = candidate.groupby("date")["absError"].mean()
    dates = baseline_daily.index.intersection(candidate_daily.index).sort_values()
    if len(dates) < 7:
        return {
            "valid": False,
            "days": int(len(dates)),
            "reason": "insufficient_paired_dates",
        }
    base = baseline_daily.loc[dates].to_numpy(dtype=float)
    challenger = candidate_daily.loc[dates].to_numpy(dtype=float)
    if not np.isfinite(np.concatenate([base, challenger])).all():
        return {
            "valid": False,
            "days": int(len(dates)),
            "reason": "non_finite_daily_mae",
        }
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(dates), size=(iterations, len(dates)))
    ratios = challenger[indices].mean(axis=1) / base[indices].mean(axis=1)
    lower, upper = np.quantile(ratios, [0.025, 0.975])
    return {
        "valid": True,
        "days": int(len(dates)),
        "candidateBetterDays": int(np.sum(challenger < base)),
        "maeRatio": round(float(challenger.mean() / base.mean()), 4),
        "maeRatioCi95Lower": round(float(lower), 4),
        "maeRatioCi95Upper": round(float(upper), 4),
        "iterations": int(iterations),
        "seed": int(seed),
    }


def _gate(
    baseline: dict,
    candidate: dict,
    baseline_intervals: dict,
    candidate_intervals: dict,
    *,
    phase: str,
    min_holdout_improvement_pct: float,
    balanced_min_mae_improvement_pct: float,
    balanced_min_rmse_improvement_pct: float,
    balanced_min_max_error_improvement_pct: float,
    balanced_max_segment_regression_pct: float,
    conservative_min_mae_improvement_pct: float,
    conservative_min_rmse_improvement_pct: float,
    conservative_min_max_error_improvement_pct: float,
    conservative_min_shape_improvement_pct: float,
    conservative_max_segment_regression_pct: float,
    paired_daily_mae: dict,
) -> dict:
    failures: list[str] = []
    base_overall = baseline["overall"]
    candidate_overall = candidate["overall"]
    improvement = (
        (float(base_overall["maeMw"]) - float(candidate_overall["maeMw"]))
        / float(base_overall["maeMw"])
        * 100.0
    )
    rmse_improvement = (
        (float(base_overall["rmseMw"]) - float(candidate_overall["rmseMw"]))
        / float(base_overall["rmseMw"])
        * 100.0
    )
    max_error_improvement = (
        (
            float(base_overall["maxErrorMw"])
            - float(candidate_overall["maxErrorMw"])
        )
        / float(base_overall["maxErrorMw"])
        * 100.0
    )
    shape_improvement = (
        (
            float(base_overall["shapeDeltaMaeMw"])
            - float(candidate_overall["shapeDeltaMaeMw"])
        )
        / float(base_overall["shapeDeltaMaeMw"])
        * 100.0
    )
    if float(candidate_overall["maeMw"]) >= float(base_overall["maeMw"]):
        failures.append("overall_mae_not_improved")
    if float(candidate_overall["rmseMw"]) >= float(base_overall["rmseMw"]):
        failures.append("overall_rmse_not_improved")
    holdout_segment_regressions: list[str] = []
    conservative_segment_regressions: list[str] = []
    for regime in ("business", "nonBusiness"):
        base_value = float(baseline["regimes"][regime]["maeMw"])
        candidate_value = float(candidate["regimes"][regime]["maeMw"])
        allowed = 1.05 if phase == "development" else 1.0
        if candidate_value > base_value * allowed:
            failures.append(f"{regime}_mae_regressed")
        if phase == "holdout" and candidate_value > base_value * (
            1.0 + balanced_max_segment_regression_pct / 100.0
        ):
            holdout_segment_regressions.append(f"regimes.{regime}")
        if phase == "holdout" and candidate_value > base_value * (
            1.0 + conservative_max_segment_regression_pct / 100.0
        ):
            conservative_segment_regressions.append(f"regimes.{regime}")
    for band, base_metrics in baseline["timeBands"].items():
        candidate_value = float(candidate["timeBands"][band]["maeMw"])
        if candidate_value > float(base_metrics["maeMw"]) * 1.05:
            failures.append(f"{band}_mae_regressed")
        if phase == "holdout" and candidate_value > float(base_metrics["maeMw"]) * (
            1.0 + balanced_max_segment_regression_pct / 100.0
        ):
            holdout_segment_regressions.append(f"timeBands.{band}")
        if phase == "holdout" and candidate_value > float(base_metrics["maeMw"]) * (
            1.0 + conservative_max_segment_regression_pct / 100.0
        ):
            conservative_segment_regressions.append(f"timeBands.{band}")

    strict_recovery = (
        improvement >= min_holdout_improvement_pct
        and rmse_improvement >= 0.0
        and max_error_improvement >= 0.0
        and shape_improvement >= 0.0
        and not holdout_segment_regressions
    )
    balanced_recovery = (
        improvement >= balanced_min_mae_improvement_pct
        and rmse_improvement >= balanced_min_rmse_improvement_pct
        and max_error_improvement >= balanced_min_max_error_improvement_pct
        and not holdout_segment_regressions
    )
    conservative_recovery = (
        improvement >= conservative_min_mae_improvement_pct
        and rmse_improvement >= conservative_min_rmse_improvement_pct
        and max_error_improvement >= conservative_min_max_error_improvement_pct
        and shape_improvement >= conservative_min_shape_improvement_pct
        and not conservative_segment_regressions
    )
    gate_mode = "development"
    if phase == "holdout":
        if strict_recovery:
            gate_mode = "strict_mae_recovery"
        elif balanced_recovery:
            gate_mode = "balanced_risk_recovery"
        elif conservative_recovery:
            gate_mode = "conservative_broad_recovery"
        else:
            gate_mode = "failed_recovery"
            failures.append("holdout_recovery_improvement_below_threshold")

    baseline_p95 = baseline_intervals.get("p95CoveragePct")
    candidate_p95 = candidate_intervals.get("p95CoveragePct")
    baseline_p99 = baseline_intervals.get("p99CoveragePct")
    candidate_p99 = candidate_intervals.get("p99CoveragePct")
    if (
        baseline_p95 is None
        or candidate_p95 is None
        or float(candidate_p95) < float(baseline_p95) - 2.0
    ):
        failures.append("p95_coverage_regressed")
    if (
        baseline_p99 is None
        or candidate_p99 is None
        or float(candidate_p99) < float(baseline_p99) - 1.0
    ):
        failures.append("p99_coverage_regressed")
    if phase == "holdout" and (
        not paired_daily_mae.get("valid", False)
        or float(paired_daily_mae.get("maeRatioCi95Upper", float("inf"))) >= 1.0
    ):
        failures.append("paired_daily_mae_ci_does_not_confirm_improvement")
    return {
        "passed": not failures,
        "phase": phase,
        "mode": gate_mode,
        "maeImprovementPct": round(improvement, 2),
        "rmseImprovementPct": round(rmse_improvement, 2),
        "maxErrorImprovementPct": round(max_error_improvement, 2),
        "shapeImprovementPct": round(shape_improvement, 2),
        "balancedMaxSegmentRegressionPct": balanced_max_segment_regression_pct,
        "holdoutSegmentRegressions": holdout_segment_regressions,
        "conservativeMaxSegmentRegressionPct": (
            conservative_max_segment_regression_pct
        ),
        "conservativeSegmentRegressions": conservative_segment_regressions,
        "pairedDailyMae": paired_daily_mae,
        "failures": failures,
    }


def replay(
    *,
    repo: Path,
    cache: pd.DataFrame,
    config: dict,
    candidate: LGBMForecaster,
    candidate_path: Path,
    baseline_path: Path | None,
    cutoff: date,
    start: date,
    end: date,
    phase: str,
    origin_lead_days: int = 0,
) -> dict:
    if baseline_path is None:
        baseline = _train_baseline(
            cache,
            config,
            cutoff,
            candidate.n_estimators,
            candidate.learning_rate,
        )
        baseline_artifact = {
            "mode": "cutoff_retrained_v11_contract",
            "sha256": None,
            "intervalVersion": baseline.interval_version,
        }
    else:
        baseline = LGBMForecaster.load(baseline_path)
        if not baseline.is_compatible():
            raise ValueError("Baseline artifact is incompatible.")
        baseline_artifact = {
            "mode": "exact_deployed_champion",
            "path": baseline_path.name,
            "sha256": artifact_sha256(baseline_path),
            "intervalVersion": baseline.interval_version,
        }
    baseline_rows: list[dict] = []
    candidate_raw_rows: list[dict] = []
    candidate_rows: list[dict] = []
    baseline_interval_rows: list[dict] = []
    candidate_raw_interval_rows: list[dict] = []
    candidate_interval_rows: list[dict] = []
    residual_history: dict[bool, list[float]] = {False: [], True: []}
    residual_entries: list[dict] = []
    origins: list[dict] = []
    calibration_config = config["forecast"]["same_regime_day_level_calibration"]
    min_history = int(calibration_config.get("min_history_days", 3))
    history_window = int(calibration_config.get("history_window_days", 3))
    shrinkage = float(calibration_config.get("shrinkage", 0.25))
    cap = float(calibration_config.get("max_abs_adjustment_mw", 1000.0))

    current = start
    while current <= end:
        commit, captured_at = _origin_commit(
            repo,
            current,
            origin_lead_days=origin_lead_days,
        )
        origin_cache = _origin_inference_cache(
            _cache_at(repo, commit),
            current,
            captured_at,
        )
        actual = _actuals(cache, current)
        if set(actual) != set(range(24)):
            raise RuntimeError(f"Incomplete finalized actuals for {current}.")
        baseline_forecasts = baseline.predict(current, origin_cache)
        candidate_forecasts = candidate.predict(current, origin_cache)
        baseline_values = np.asarray([
            point.forecast_mw for point in baseline_forecasts
        ])
        raw_values = np.asarray([
            point.forecast_mw for point in candidate_forecasts
        ])
        regime = bool(_is_nonworking(current))
        history = residual_history[regime]
        history_values = history[-history_window:]
        adjustment = 0.0
        if len(history_values) >= min_history:
            adjustment = float(np.clip(
                shrinkage * np.median(history_values),
                -cap,
                cap,
            ))
        candidate_values = raw_values + adjustment
        for hour in range(24):
            common = {
                "date": current,
                "hour": hour,
                "actual": actual[hour],
                "isNonBusinessDay": regime,
            }
            baseline_rows.append({**common, "predicted": baseline_values[hour]})
            candidate_raw_rows.append({**common, "predicted": raw_values[hour]})
            candidate_rows.append({**common, "predicted": candidate_values[hour]})
            baseline_point = baseline_forecasts[hour]
            candidate_point = candidate_forecasts[hour]
            baseline_interval_rows.append({
                **common,
                "p95Lower": baseline_point.p95_lower_mw,
                "p95Upper": baseline_point.p95_upper_mw,
                "p99Lower": baseline_point.p99_lower_mw,
                "p99Upper": baseline_point.p99_upper_mw,
            })
            candidate_raw_interval_rows.append({
                **common,
                "p95Lower": candidate_point.p95_lower_mw,
                "p95Upper": candidate_point.p95_upper_mw,
                "p99Lower": candidate_point.p99_lower_mw,
                "p99Upper": candidate_point.p99_upper_mw,
            })
            candidate_interval_rows.append({
                **common,
                "p95Lower": candidate_point.p95_lower_mw + adjustment,
                "p95Upper": candidate_point.p95_upper_mw + adjustment,
                "p99Lower": candidate_point.p99_lower_mw + adjustment,
                "p99Upper": candidate_point.p99_upper_mw + adjustment,
            })
        raw_residual = float(np.mean([
            actual[hour] - raw_values[hour]
            for hour in range(24)
        ]))
        history.append(raw_residual)
        residual_entries.append({
            "date": current.isoformat(),
            "isNonBusinessDay": regime,
            "meanResidualMw": round(raw_residual, 1),
            "appliedAdjustmentMw": round(adjustment, 1),
            "originCommit": commit,
            "originGeneratedAt": captured_at,
        })
        origins.append({
            "date": current.isoformat(),
            "commit": commit,
            "capturedAt": captured_at,
        })
        current += timedelta(days=1)

    baseline_metrics = _metrics(baseline_rows)
    candidate_raw_metrics = _metrics(candidate_raw_rows)
    candidate_metrics = _metrics(candidate_rows)
    baseline_intervals = _interval_metrics(baseline_interval_rows)
    candidate_raw_intervals = _interval_metrics(candidate_raw_interval_rows)
    candidate_intervals = _interval_metrics(candidate_interval_rows)
    paired_daily_mae = _paired_daily_mae_bootstrap(
        baseline_rows,
        candidate_rows,
    )
    promotion_config = config.get("model_promotion", {})
    gate = _gate(
        baseline_metrics,
        candidate_metrics,
        baseline_intervals,
        candidate_intervals,
        phase=phase,
        min_holdout_improvement_pct=float(
            promotion_config.get(
                "recovery_min_improvement_pct",
                8.0,
            )
        ),
        balanced_min_mae_improvement_pct=float(
            promotion_config.get(
                "recovery_balanced_min_mae_improvement_pct",
                7.0,
            )
        ),
        balanced_min_rmse_improvement_pct=float(
            promotion_config.get(
                "recovery_balanced_min_rmse_improvement_pct",
                8.0,
            )
        ),
        balanced_min_max_error_improvement_pct=float(
            promotion_config.get(
                "recovery_balanced_min_max_error_improvement_pct",
                10.0,
            )
        ),
        balanced_max_segment_regression_pct=float(
            promotion_config.get(
                "recovery_balanced_max_segment_regression_pct",
                1.0,
            )
        ),
        conservative_min_mae_improvement_pct=float(
            promotion_config.get(
                "recovery_conservative_min_mae_improvement_pct",
                5.0,
            )
        ),
        conservative_min_rmse_improvement_pct=float(
            promotion_config.get(
                "recovery_conservative_min_rmse_improvement_pct",
                5.0,
            )
        ),
        conservative_min_max_error_improvement_pct=float(
            promotion_config.get(
                "recovery_conservative_min_max_error_improvement_pct",
                5.0,
            )
        ),
        conservative_min_shape_improvement_pct=float(
            promotion_config.get(
                "recovery_conservative_min_shape_improvement_pct",
                2.0,
            )
        ),
        conservative_max_segment_regression_pct=float(
            promotion_config.get(
                "recovery_conservative_max_segment_regression_pct",
                0.0,
            )
        ),
        paired_daily_mae=paired_daily_mae,
    )
    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": pd.Timestamp.now(tz=JST).isoformat(timespec="seconds"),
        "phase": phase,
        "trainingCutoffExclusive": cutoff.isoformat(),
        "validationPeriod": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days + 1,
        },
        "methodology": {
            "forecastOrigin": (
                "first_same_day_snapshot_cache_from_data_branch"
                if origin_lead_days == 0
                else "first_previous_day_snapshot_cache_from_data_branch"
            ),
            "originLeadDays": origin_lead_days,
            "targetDayActualLeakage": "removed",
            "actuals": "finalized_observed_only",
            "onlineCalibration": (
                "previous_three_same-business-type raw residual median, "
                f"{shrinkage * 100:g} percent shrinkage, +/-{cap:g} MW cap"
            ),
            "downstreamGuards": "excluded_for_model_contract_attribution",
        },
        "candidateArtifact": {
            "path": candidate_path.name,
            "sha256": artifact_sha256(candidate_path),
            "intervalVersion": candidate.interval_version,
            "configFingerprint": config_fingerprint(candidate.config),
        },
        "baselineArtifact": baseline_artifact,
        "baseline": baseline_metrics,
        "candidateRaw": candidate_raw_metrics,
        "candidate": candidate_metrics,
        "intervals": {
            "baseline": baseline_intervals,
            "candidateRaw": candidate_raw_intervals,
            "candidate": candidate_intervals,
        },
        "daily": {
            "baseline": _daily_metrics(baseline_rows, start, end),
            "candidate": _daily_metrics(candidate_rows, start, end),
        },
        "pairedDailyMae": paired_daily_mae,
        "dailyRawResiduals": residual_entries,
        "origins": origins,
        "gate": gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-artifact", type=Path)
    parser.add_argument("--cutoff", type=date.fromisoformat, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--phase", choices=("development", "holdout"), required=True)
    parser.add_argument(
        "--origin-lead-days",
        type=int,
        choices=(0, 1),
        default=0,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    candidate = LGBMForecaster.load(args.candidate)
    report = replay(
        repo=args.repo,
        cache=_normalized_cache(args.cache),
        config=config,
        candidate=candidate,
        candidate_path=args.candidate,
        baseline_path=args.baseline_artifact,
        cutoff=args.cutoff,
        start=args.start,
        end=args.end,
        phase=args.phase,
        origin_lead_days=args.origin_lead_days,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"gate": report["gate"], "metrics": report["candidate"]}, indent=2))


if __name__ == "__main__":
    main()
