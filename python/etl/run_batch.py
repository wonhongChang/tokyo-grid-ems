#!/usr/bin/env python3
"""
Tokyo Grid EMS — ETL batch runner (Phase 2).

Flow
----
1. Load state (.etl_state.json) and hourly cache (.hourly_cache.parquet).
2. Discover CSV files under data/raw/.
3. For each new date:
   a. Parse CSV + quality gate.
   b. Compute baseline forecast using history BEFORE that date.
   c. Detect anomalies (reserve risk / spike+drop / drift).
   d. Write alerts/YYYY-MM-DD.json and forecast/YYYY-MM-DD.json.
   e. Append to hourly cache.
4. Save updated cache and state.
5. Generate today/tomorrow forecast JSONs.
6. Write status.json.

Usage
-----
    python python/etl/run_batch.py
    python python/etl/run_batch.py --full-backfill
    python python/etl/run_batch.py --input data/raw --out web/public --config config.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python.tepc_parser import parse_tepc_daily_csv
from python.etl.quality_gate import run_quality_gate, QualityStatus
from python.forecast.baseline import (
    compute_forecast, forecast_to_dict, peak_of_forecasts, HourlyForecast,
)
from python.anomaly.detector import detect_anomalies

JST = ZoneInfo("Asia/Tokyo")

_LGBM_MODEL_NAME = ".lgbm_model.pkl"
_LGBM_MIN_ROWS   = 90 * 24

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "forecast": {"n_weeks": 12, "min_samples_per_slot": 4},
        "anomaly": {
            "reserve_risk": {"warning_pct": 90.0, "critical_pct": 95.0},
            "drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3},
        },
    }

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state(out_dir: Path) -> dict:
    p = out_dir / ".etl_state.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"okDates": [], "failedDates": [], "summaries": {}}


def save_state(out_dir: Path, state: dict) -> None:
    p = out_dir / ".etl_state.json"
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Hourly cache (parquet)
# ---------------------------------------------------------------------------

_CACHE_COLS = ["ts", "actual_mw", "forecast_mw", "usage_pct", "supply_mw"]
_CACHE_PATH_NAME = ".hourly_cache.parquet"


def load_hourly_cache(out_dir: Path) -> pd.DataFrame:
    p = out_dir / _CACHE_PATH_NAME
    if p.exists():
        df = pd.read_parquet(p)
        if "ts" in df.columns and df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("Asia/Tokyo")
        return df
    return pd.DataFrame(columns=_CACHE_COLS)


def save_hourly_cache(out_dir: Path, cache: pd.DataFrame) -> None:
    if cache.empty:
        return
    (out_dir / _CACHE_PATH_NAME).parent.mkdir(parents=True, exist_ok=True)
    cache[_CACHE_COLS].drop_duplicates(subset=["ts"]).sort_values("ts").to_parquet(
        out_dir / _CACHE_PATH_NAME, index=False
    )


def _extract_cache_rows(hourly: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in _CACHE_COLS if c in hourly.columns]
    return hourly[cols].copy()

# ---------------------------------------------------------------------------
# CSV discovery
# ---------------------------------------------------------------------------

def discover_csv_files(input_dir: Path) -> dict[date, Path]:
    result: dict[date, Path] = {}
    for csv_path in input_dir.rglob("*_power_usage.csv"):
        date_part = csv_path.stem.split("_")[0]
        if len(date_part) == 8 and date_part.isdigit():
            try:
                d = date(int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8]))
                result[d] = csv_path
            except ValueError:
                continue
    return dict(sorted(result.items()))

# ---------------------------------------------------------------------------
# Per-day summary
# ---------------------------------------------------------------------------

def extract_day_summary(d: date, parsed) -> dict:
    hourly = parsed.hourly
    peak_idx = hourly["actual_mw"].idxmax()
    peak_row = hourly.loc[peak_idx]
    peak_ts = peak_row["ts"]
    return {
        "date": d.isoformat(),
        "peakActualMw": round(float(peak_row["actual_mw"]), 1) if pd.notna(peak_row["actual_mw"]) else None,
        "peakActualAt": peak_ts.isoformat(timespec="seconds") if pd.notna(peak_ts) else None,
        "peakUsagePct": round(float(hourly["usage_pct"].max()), 1) if "usage_pct" in hourly.columns else None,
        "peakSupplyMw": round(float(hourly["supply_mw"].max()), 1) if "supply_mw" in hourly.columns else None,
    }

# ---------------------------------------------------------------------------
# JSON builders
# ---------------------------------------------------------------------------

def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ts_now() -> str:
    return datetime.now(tz=JST).isoformat(timespec="seconds")


def build_alerts_json(d: date, events: list[dict]) -> dict:
    summary = {"critical": 0, "warning": 0, "info": 0}
    for e in events:
        sev = e.get("severity", "info")
        summary[sev] = summary.get(sev, 0) + 1
    return {
        "date": d.isoformat(),
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "summary": summary,
        "events": events,
    }


def build_actual_json(d: date, hourly: pd.DataFrame) -> dict:
    series = []
    for _, row in hourly.sort_values("ts").iterrows():
        ts = row["ts"]
        if pd.isna(ts):
            continue
        actual_mw      = row.get("actual_mw")
        forecast_mw    = row.get("forecast_mw")
        usage_pct      = row.get("usage_pct")
        supply_mw      = row.get("supply_mw")
        series.append({
            "ts": ts.isoformat(timespec="seconds"),
            "actualMw":          round(float(actual_mw),   1) if pd.notna(actual_mw)   else None,
            "tepcoForecastMw":   round(float(forecast_mw), 1) if pd.notna(forecast_mw) else None,
            "usagePct":          round(float(usage_pct),   1) if pd.notna(usage_pct)   else None,
            "supplyMw":          round(float(supply_mw),   1) if pd.notna(supply_mw)   else None,
        })
    return {
        "date": d.isoformat(),
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "series": series,
    }


def build_forecast_json(d: date, fc_list: list, config: dict, model_name: str = "baseline_dow_hour_mean") -> dict:
    if not fc_list:
        return {
            "date": d.isoformat(),
            "timezone": "Asia/Tokyo",
            "availability": "not_yet_available",
            "series": [],
            "message": "Insufficient historical data for this date.",
        }
    cfg_fc = config.get("forecast", {})
    return {
        "date": d.isoformat(),
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "model": {
            "name": model_name,
            "version": "mvp-1",
            "nWeeks": cfg_fc.get("n_weeks", 12),
        },
        "peak": peak_of_forecasts(fc_list),
        "series": [forecast_to_dict(f) for f in fc_list],
    }


def _build_today_alerts(out_dir: Path, today: date, config: dict) -> None:
    actual_path  = out_dir / "actual"   / f"{today.isoformat()}.json"
    forecast_path = out_dir / "forecast" / f"{today.isoformat()}.json"
    alerts_path  = out_dir / "alerts"   / f"{today.isoformat()}.json"

    if not actual_path.exists() or not forecast_path.exists():
        return
    try:
        actual_data = json.loads(actual_path.read_text(encoding="utf-8"))
        rows = []
        for pt in actual_data.get("series", []):
            if pt.get("actualMw") is None:
                continue
            rows.append({
                "ts":        pd.Timestamp(pt["ts"]).tz_convert("Asia/Tokyo"),
                "actual_mw": pt["actualMw"],
                "usage_pct": pt.get("usagePct"),
                "supply_mw": pt.get("supplyMw"),
            })
        if not rows:
            return
        hourly = pd.DataFrame(rows)

        fc_data = json.loads(forecast_path.read_text(encoding="utf-8"))
        fc_list = [
            HourlyForecast(
                ts=pt["ts"],
                forecast_mw=pt["forecastMw"],
                p95_lower_mw=pt["p95LowerMw"],
                p95_upper_mw=pt["p95UpperMw"],
                p99_lower_mw=pt["p99LowerMw"],
                p99_upper_mw=pt["p99UpperMw"],
            )
            for pt in fc_data.get("series", [])
        ]

        events = detect_anomalies(hourly, fc_list, config.get("anomaly", {}))
        write_json(alerts_path, build_alerts_json(today, events))
        print(f"[STATUS] Today alerts: {len(events)} events -> {alerts_path.name}")
    except Exception as e:
        print(f"[WARN] Failed to build today alerts: {e}", file=sys.stderr)



def compute_missing_days(csv_dates: set[date]) -> list[str]:
    if not csv_dates:
        return []
    yesterday = datetime.now(tz=JST).date() - timedelta(days=1)
    start, end = min(csv_dates), min(max(csv_dates), yesterday)
    result, d = [], start
    while d <= end:
        if d not in csv_dates:
            result.append(d.isoformat())
        d += timedelta(days=1)
    return result


def _forecast_severity(fc_list: list, cache: pd.DataFrame, config: dict) -> str:
    """Estimate severity for a future forecast using peak forecast vs recent supply."""
    if not fc_list:
        return "info"
    peak_fc_mw = max(f.forecast_mw for f in fc_list)
    recent_supply = cache["supply_mw"].dropna().tail(24 * 7).mean() if "supply_mw" in cache.columns else None
    if recent_supply and recent_supply > 0:
        est_pct = peak_fc_mw / recent_supply * 100
        rr = config.get("anomaly", {}).get("reserve_risk", {})
        if est_pct >= rr.get("critical_pct", 95.0):
            return "critical"
        if est_pct >= rr.get("warning_pct", 90.0):
            return "warning"
    return "info"


def build_status_json(
    ok_set: set[date],
    fail_set: set[date],
    summaries: dict,
    csv_dates: set[date],
    today: date,
    today_fc: list,
    tomorrow: date,
    tomorrow_fc: list,
    cache: pd.DataFrame,
    config: dict,
) -> dict:
    coverage_to = max(ok_set) if ok_set else None
    latest = summaries.get(coverage_to.isoformat()) if coverage_to else None
    missing = compute_missing_days(csv_dates)
    availability = "ok" if ok_set else ("failed" if fail_set else "not_yet_available")

    def _fc_summary(d: date, fc_list: list) -> dict | None:
        if not fc_list:
            return None
        peak = peak_of_forecasts(fc_list)
        return {
            "date": d.isoformat(),
            "peakForecastMw": peak["forecastMw"] if peak else None,
            "peakForecastAt": peak["at"] if peak else None,
            "severity": _forecast_severity(fc_list, cache, config),
        }

    return {
        "project": "tokyo-grid-ems",
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "lastUpdatedAt": ts_now(),
        "coverageTo": coverage_to.isoformat() if coverage_to else None,
        "availability": availability,
        "missingDays": missing,
        "failedDays": [d.isoformat() for d in sorted(fail_set)],
        "latest": latest,
        "today": _fc_summary(today, today_fc),
        "tomorrow": _fc_summary(tomorrow, tomorrow_fc),
    }

# ---------------------------------------------------------------------------
# LightGBM helpers
# ---------------------------------------------------------------------------

def _try_train_lgbm(cache: pd.DataFrame, out_dir: Path):
    """Train and save LGBMForecaster. Returns forecaster or None on any failure."""
    if len(cache) < _LGBM_MIN_ROWS:
        return None
    try:
        from python.forecast.lgbm_model import LGBMForecaster
        forecaster = LGBMForecaster()
        forecaster.fit(cache)
        forecaster.save(out_dir / _LGBM_MODEL_NAME)
        print(f"[LGBM] Trained and saved -> {_LGBM_MODEL_NAME}")
        return forecaster
    except ImportError:
        return None
    except Exception as e:
        print(f"[WARN] LightGBM training failed: {e}", file=sys.stderr)
        return None



def _get_forecast(
    cache: pd.DataFrame,
    target_date: date,
    n_weeks: int,
    min_samples: int,
) -> tuple[list, str]:
    """Return (fc_list, model_name)."""
    return compute_forecast(cache, target_date, n_weeks, min_samples), "baseline_dow_hour_mean"


# ---------------------------------------------------------------------------
# Status-only update (used by intraday workflow)
# ---------------------------------------------------------------------------

def _run_status_only(out_dir: Path, config: dict) -> None:
    state = load_state(out_dir)
    ok_set   = {date.fromisoformat(d) for d in state.get("okDates",   [])}
    fail_set = {date.fromisoformat(d) for d in state.get("failedDates", [])}
    summaries: dict[str, dict] = state.get("summaries", {})
    hourly_cache = load_hourly_cache(out_dir)

    cfg_fc      = config.get("forecast", {})
    n_weeks     = cfg_fc.get("n_weeks", 12)
    min_samples = cfg_fc.get("min_samples_per_slot", 4)

    today    = datetime.now(tz=JST).date()
    tomorrow = today + timedelta(days=1)

    today_fc,    today_model    = _get_forecast(hourly_cache, today,    n_weeks, min_samples)
    tomorrow_fc, tomorrow_model = _get_forecast(hourly_cache, tomorrow, n_weeks, min_samples)

    write_json(out_dir / "forecast" / f"{today.isoformat()}.json",
               build_forecast_json(today, today_fc, config, today_model))
    write_json(out_dir / "forecast" / f"{tomorrow.isoformat()}.json",
               build_forecast_json(tomorrow, tomorrow_fc, config, tomorrow_model))

    _build_today_alerts(out_dir, today, config)

    write_json(out_dir / "status.json", build_status_json(
        ok_set, fail_set, summaries, ok_set | fail_set,
        today, today_fc, tomorrow, tomorrow_fc, hourly_cache, config,
    ))
    print(f"[STATUS] Updated: model={today_model} tomorrow={'enabled' if tomorrow_fc else 'disabled'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Tokyo Grid EMS ETL batch runner")
    ap.add_argument("--input", default="data/raw")
    ap.add_argument("--out", default="web/public")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--full-backfill", action="store_true",
                    help="Ignore existing state; reprocess all dates")
    ap.add_argument("--status-only", action="store_true",
                    help="Skip CSV processing; only update status.json with today/tomorrow forecasts")
    args = ap.parse_args()

    input_dir = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(Path(args.config))

    if args.status_only:
        _run_status_only(out_dir, config)
        return

    if not input_dir.exists():
        print(f"[ERROR] Input dir not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    csv_map = discover_csv_files(input_dir)
    if not csv_map:
        print("[WARN] No CSV files found.", file=sys.stderr)
        sys.exit(0)

    print(f"[ETL] Found {len(csv_map)} CSVs  ({min(csv_map)} → {max(csv_map)})")

    # Load state
    state = {} if args.full_backfill else load_state(out_dir)
    ok_set = {date.fromisoformat(d) for d in state.get("okDates", [])}
    fail_set = {date.fromisoformat(d) for d in state.get("failedDates", [])}
    summaries: dict[str, dict] = state.get("summaries", {})

    # Load hourly cache — rebuild from scratch on full backfill or if cache missing
    cache_path = out_dir / _CACHE_PATH_NAME
    if args.full_backfill or not cache_path.exists():
        hourly_cache = pd.DataFrame(columns=_CACHE_COLS)
        ok_set.clear()
        fail_set.clear()
        summaries.clear()
    else:
        hourly_cache = load_hourly_cache(out_dir)

    cfg_fc = config.get("forecast", {})
    n_weeks = cfg_fc.get("n_weeks", 12)
    min_samples = cfg_fc.get("min_samples_per_slot", 4)

    new_ok = new_fail = 0

    for d, csv_path in csv_map.items():
        if d in ok_set or d in fail_set:
            continue

        print(f"[ETL] {d}  ←  {csv_path.name}")
        try:
            parsed = parse_tepc_daily_csv(csv_path)
            if run_quality_gate(parsed) == QualityStatus.FAILED:
                raise ValueError("quality gate: FAILED")

            hourly = parsed.hourly

            # Forecast uses only history BEFORE this date (filtered inside compute_forecast)
            fc_list = compute_forecast(hourly_cache, d, n_weeks, min_samples)

            # Anomaly detection on today's actuals vs forecast
            events = detect_anomalies(hourly, fc_list, config.get("anomaly", {}))

            write_json(out_dir / "alerts" / f"{d.isoformat()}.json",
                       build_alerts_json(d, events))
            write_json(out_dir / "forecast" / f"{d.isoformat()}.json",
                       build_forecast_json(d, fc_list, config))
            write_json(out_dir / "actual" / f"{d.isoformat()}.json",
                       build_actual_json(d, hourly))

            # Append to cache (compute_forecast filters ts < target_date internally,
            # so order doesn't matter, but we append after for clarity)
            new_rows = _extract_cache_rows(hourly)
            if hourly_cache.empty:
                hourly_cache = new_rows.copy()
            else:
                hourly_cache = pd.concat([hourly_cache, new_rows], ignore_index=True)

            summaries[d.isoformat()] = extract_day_summary(d, parsed)
            ok_set.add(d)
            new_ok += 1

        except Exception as e:
            print(f"[WARN]  {d}: {e}", file=sys.stderr)
            fail_set.add(d)
            new_fail += 1

    # Persist state and cache
    save_state(out_dir, {
        "okDates": [d.isoformat() for d in sorted(ok_set)],
        "failedDates": [d.isoformat() for d in sorted(fail_set)],
        "summaries": summaries,
    })
    save_hourly_cache(out_dir, hourly_cache)

    # Train and save LightGBM on the full updated cache (predictions stay on baseline until Phase 5-B)
    _try_train_lgbm(hourly_cache, out_dir)

    # Today / tomorrow forecasts
    today    = datetime.now(tz=JST).date()
    tomorrow = today + timedelta(days=1)

    today_fc,    today_model    = _get_forecast(hourly_cache, today,    n_weeks, min_samples)
    tomorrow_fc, tomorrow_model = _get_forecast(hourly_cache, tomorrow, n_weeks, min_samples)

    write_json(out_dir / "forecast" / f"{today.isoformat()}.json",
               build_forecast_json(today, today_fc, config, today_model))
    write_json(out_dir / "forecast" / f"{tomorrow.isoformat()}.json",
               build_forecast_json(tomorrow, tomorrow_fc, config, tomorrow_model))

    # status.json
    write_json(out_dir / "status.json", build_status_json(
        ok_set, fail_set, summaries, set(csv_map.keys()),
        today, today_fc, tomorrow, tomorrow_fc, hourly_cache, config,
    ))

    coverage_to = max(ok_set) if ok_set else None
    print(
        f"[ETL] Done -- new: {new_ok} ok / {new_fail} failed  |  "
        f"total: {len(ok_set)} ok / {len(fail_set)} failed  |  coverage -> {coverage_to}"
    )


if __name__ == "__main__":
    main()
