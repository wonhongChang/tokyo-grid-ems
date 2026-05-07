#!/usr/bin/env python3
"""Walk-forward model comparison: baseline vs LightGBM.

Usage:
    python python/eval/compare_models.py
    python python/eval/compare_models.py --cache web/public/.hourly_cache.parquet \
        --out web/public/model_eval.json --test-start 2026-01-01
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
_DEFAULT_OUT        = "web/public/model_eval.json"
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
        print("[WARN] lightgbm not installed — skipping LightGBM evaluation.", file=sys.stderr)
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
    if cache["ts"].dt.tz is None:
        cache["ts"] = cache["ts"].dt.tz_localize("Asia/Tokyo")

    test_start    = date.fromisoformat(args.test_start)
    test_start_ts = pd.Timestamp(test_start, tz=JST)
    train_rows    = cache[cache["ts"] < test_start_ts]

    if len(train_rows) < _MIN_TRAIN_DAYS * 24:
        print(f"[ERROR] Training set too small ({len(train_rows)} rows).", file=sys.stderr)
        sys.exit(1)

    test_dates = sorted(set(
        cache[(cache["ts"] >= test_start_ts) & cache["actual_mw"].notna()]["ts"].dt.date
    ))
    if not test_dates:
        print(f"[ERROR] No test dates found on or after {test_start}.", file=sys.stderr)
        sys.exit(1)

    print(f"[EVAL] Train: before {test_start} ({len(train_rows)} rows)")
    print(f"[EVAL] Test:  {test_dates[0]} – {test_dates[-1]} ({len(test_dates)} days)")

    print("[EVAL] Evaluating baseline...")
    bl_actual, bl_pred = _evaluate_baseline(cache, test_dates)
    bl_metrics = _metrics(bl_actual, bl_pred)
    print(f"[EVAL] Baseline  RMSE={bl_metrics['rmse']}  MAE={bl_metrics['mae']}  "
          f"MAPE={bl_metrics['mape']}%  n={bl_metrics['n']}")

    print("[EVAL] Evaluating LightGBM...")
    lgbm_result = _evaluate_lgbm(
        cache, test_start, test_dates,
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
    )
    lgbm_metrics = None
    if lgbm_result is not None:
        lgbm_metrics = _metrics(*lgbm_result)
        print(f"[EVAL] LightGBM  RMSE={lgbm_metrics['rmse']}  MAE={lgbm_metrics['mae']}  "
              f"MAPE={lgbm_metrics['mape']}%  n={lgbm_metrics['n']}")
        if bl_metrics["rmse"] and lgbm_metrics["rmse"]:
            imp = (bl_metrics["rmse"] - lgbm_metrics["rmse"]) / bl_metrics["rmse"] * 100
            print(f"[EVAL] RMSE improvement: {imp:+.1f}%")

    result = {
        "evaluatedAt": pd.Timestamp.now(tz=JST).isoformat(timespec="seconds"),
        "trainPeriod": {
            "start": str(min(cache["ts"].dt.date)),
            "end":   str(max(d for d in cache["ts"].dt.date if d < test_start)),
        },
        "testPeriod": {
            "start": str(test_dates[0]),
            "end":   str(test_dates[-1]),
            "days":  len(test_dates),
        },
        "baseline": bl_metrics,
        "lightgbm": lgbm_metrics,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[EVAL] Saved -> {out_path}")


if __name__ == "__main__":
    main()
