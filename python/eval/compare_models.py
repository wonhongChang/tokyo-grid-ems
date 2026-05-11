#!/usr/bin/env python3
"""Build offline backtest reports for the forecasting models.

Usage:
    python python/eval/compare_models.py
    python python/eval/compare_models.py --cache web/public/.hourly_cache.parquet \
        --out web/public/metrics/model_backtest.json --test-start 2026-01-01
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python.forecast.baseline import compute_forecast

JST = ZoneInfo("Asia/Tokyo")

_DEFAULT_CACHE      = "web/public/.hourly_cache.parquet"
_DEFAULT_OUT        = "web/public/metrics/model_backtest.json"
_DEFAULT_TEST_START = "2026-01-01"
_MIN_TRAIN_DAYS     = 90


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    mask = ~(np.isnan(actual) | np.isnan(predicted))
    a, p = actual[mask], predicted[mask]
    if len(a) == 0:
        return {"rmse": None, "mae": None, "mape": None, "n": 0}
    rmse = float(np.sqrt(np.mean((a - p) ** 2)))
    mae  = float(np.mean(np.abs(a - p)))
    nz   = a != 0
    mape = float(np.mean(np.abs((a[nz] - p[nz]) / a[nz])) * 100) if nz.any() else None
    return {
        "rmse": round(rmse, 2),
        "mae":  round(mae,  2),
        "mape": round(mape, 2) if mape is not None else None,
        "n":    int(len(a)),
    }


def _prepare_cache(cache: pd.DataFrame) -> pd.DataFrame:
    result = cache.copy()
    if result["ts"].dt.tz is None:
        result["ts"] = result["ts"].dt.tz_localize("Asia/Tokyo")
    return result


def _evaluate_baseline(
    cache: pd.DataFrame,
    test_dates: list[date],
    n_weeks: int = 12,
    min_samples: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    actuals, preds = [], []
    for d in test_dates:
        cutoff = pd.Timestamp(d, tz=JST)
        fc_list = compute_forecast(cache[cache["ts"] < cutoff], d, n_weeks, min_samples)
        fc_by_hour = {pd.Timestamp(f.ts).hour: f.forecast_mw for f in fc_list}
        for _, row in cache[cache["ts"].dt.date == d].sort_values("ts").iterrows():
            if pd.notna(row["actual_mw"]):
                actuals.append(row["actual_mw"])
                preds.append(fc_by_hour.get(row["ts"].hour, float("nan")))
    return np.array(actuals, dtype=float), np.array(preds, dtype=float)


def _evaluate_lgbm(
    cache: pd.DataFrame,
    train_cutoff: date,
    test_dates: list[date],
    n_estimators: int = 500,
    learning_rate: float = 0.05,
) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        from python.forecast.lgbm_model import LGBMForecaster
    except ImportError:
        print("[WARN] lightgbm not installed; skipping LightGBM evaluation.", file=sys.stderr)
        return None

    train_cache = cache[cache["ts"] < pd.Timestamp(train_cutoff, tz=JST)]
    try:
        forecaster = LGBMForecaster(n_estimators=n_estimators, learning_rate=learning_rate)
        forecaster.fit(train_cache)
    except ValueError as e:
        print(f"[WARN] LightGBM training failed: {e}", file=sys.stderr)
        return None

    actuals, preds = [], []
    for d in test_dates:
        cutoff = pd.Timestamp(d, tz=JST)
        try:
            fc_list = forecaster.predict(d, cache[cache["ts"] < cutoff])
            fc_by_hour = {pd.Timestamp(f.ts).hour: f.forecast_mw for f in fc_list}
        except Exception as e:
            print(f"[WARN] LightGBM predict failed for {d}: {e}", file=sys.stderr)
            fc_by_hour = {}
        for _, row in cache[cache["ts"].dt.date == d].sort_values("ts").iterrows():
            if pd.notna(row["actual_mw"]):
                actuals.append(row["actual_mw"])
                preds.append(fc_by_hour.get(row["ts"].hour, float("nan")))

    return np.array(actuals, dtype=float), np.array(preds, dtype=float)


def build_model_backtest_report(
    cache: pd.DataFrame,
    generated_at: str | None = None,
    test_start: str = _DEFAULT_TEST_START,
    n_estimators: int = 500,
    learning_rate: float = 0.05,
) -> dict:
    """Build a frozen-origin hourly-demand backtest report.

    The model is trained only on rows before ``test_start``. Each test-day
    prediction receives only cache rows before that target date for lag and
    rolling features.
    """
    cache = _prepare_cache(cache)
    test_start_date = date.fromisoformat(test_start)
    test_start_ts = pd.Timestamp(test_start_date, tz=JST)
    train_rows = cache[cache["ts"] < test_start_ts]

    if len(train_rows) < _MIN_TRAIN_DAYS * 24:
        raise ValueError(f"Training set too small ({len(train_rows)} rows).")

    test_dates = sorted(set(
        cache[(cache["ts"] >= test_start_ts) & cache["actual_mw"].notna()]["ts"].dt.date
    ))
    if not test_dates:
        raise ValueError(f"No test dates found on or after {test_start}.")

    bl_actual, bl_pred = _evaluate_baseline(cache, test_dates)
    bl_metrics = _metrics(bl_actual, bl_pred)

    lgbm_result = _evaluate_lgbm(
        cache,
        test_start_date,
        test_dates,
        n_estimators=n_estimators,
        learning_rate=learning_rate,
    )
    lgbm_metrics = _metrics(*lgbm_result) if lgbm_result is not None else None

    rmse_improvement_pct = None
    mae_improvement_pct = None
    if lgbm_metrics is not None:
        if bl_metrics["rmse"] and lgbm_metrics["rmse"]:
            rmse_improvement_pct = round(
                (bl_metrics["rmse"] - lgbm_metrics["rmse"]) / bl_metrics["rmse"] * 100,
                1,
            )
        if bl_metrics["mae"] and lgbm_metrics["mae"]:
            mae_improvement_pct = round(
                (bl_metrics["mae"] - lgbm_metrics["mae"]) / bl_metrics["mae"] * 100,
                1,
            )

    return {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at or pd.Timestamp.now(tz=JST).isoformat(timespec="seconds"),
        "methodology": {
            "type": "frozen_origin_backtest",
            "target": "hourly_actual_mw",
            "testStart": test_start_date.isoformat(),
            "minTrainDays": _MIN_TRAIN_DAYS,
        },
        "trainPeriod": {
            "start": str(min(cache["ts"].dt.date)),
            "end":   str(max(d for d in cache["ts"].dt.date if d < test_start_date)),
            "rows":  int(len(train_rows)),
        },
        "testPeriod": {
            "start": str(test_dates[0]),
            "end":   str(test_dates[-1]),
            "days":  len(test_dates),
        },
        "baseline": bl_metrics,
        "lightgbm": lgbm_metrics,
        "improvementPct": {
            "rmse": rmse_improvement_pct,
            "mae": mae_improvement_pct,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache",         default=_DEFAULT_CACHE)
    ap.add_argument("--out",           default=_DEFAULT_OUT)
    ap.add_argument("--test-start",    default=_DEFAULT_TEST_START)
    ap.add_argument("--n-estimators",  type=int,   default=500)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    args = ap.parse_args()

    cache_path = Path(args.cache)
    if not cache_path.exists():
        print(f"[ERROR] Cache not found: {cache_path}", file=sys.stderr)
        sys.exit(1)

    cache = pd.read_parquet(cache_path)
    try:
        result = build_model_backtest_report(
            cache,
            test_start=args.test_start,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
        )
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[EVAL] Train: {result['trainPeriod']['start']} -> {result['trainPeriod']['end']} "
          f"({result['trainPeriod']['rows']} rows)")
    print(f"[EVAL] Test:  {result['testPeriod']['start']} -> {result['testPeriod']['end']} "
          f"({result['testPeriod']['days']} days)")
    bl_metrics = result["baseline"]
    print(f"[EVAL] Baseline  RMSE={bl_metrics['rmse']}  MAE={bl_metrics['mae']}  "
          f"MAPE={bl_metrics['mape']}%  n={bl_metrics['n']}")
    lgbm_metrics = result["lightgbm"]
    if lgbm_metrics is not None:
        print(f"[EVAL] LightGBM  RMSE={lgbm_metrics['rmse']}  MAE={lgbm_metrics['mae']}  "
              f"MAPE={lgbm_metrics['mape']}%  n={lgbm_metrics['n']}")
        rmse_imp = result["improvementPct"]["rmse"]
        if rmse_imp is not None:
            print(f"[EVAL] RMSE improvement: {rmse_imp:+.1f}%")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[EVAL] Saved -> {out_path}")


if __name__ == "__main__":
    main()
