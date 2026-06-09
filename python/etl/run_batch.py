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
import shutil
import sys
from dataclasses import dataclass
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
from python.forecast.interval_calibration import calibrate_p95_half_widths
from python.anomaly.detector import (
    DEFAULT_RESERVE_CRITICAL_PCT,
    DEFAULT_RESERVE_WARNING_PCT,
    detect_anomalies,
)

JST = ZoneInfo("Asia/Tokyo")

_LGBM_MODEL_NAME = ".lgbm_model.pkl"
_LGBM_MIN_ROWS   = 90 * 24
_TEPCO_FORECAST_FALLBACK_SOURCE = "tepco_forecast_fallback"
_FORECAST_SNAPSHOT_PATH_NAME = "forecast_snapshots"
_OPERATIONAL_CALIBRATION_SNAPSHOT_PATH_NAME = (
    "reports/internal/operational-calibration/snapshots"
)


@dataclass(frozen=True)
class ForecastBuildResult:
    forecasts: list[HourlyForecast]
    model_name: str
    stages: dict[str, list[HourlyForecast]]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "forecast": {"n_weeks": 12, "min_samples_per_slot": 4},
        "weather_forecast_bias_correction": {
            "enabled": False,
            "lookback_hours": 4,
            "observation_lag_hours": 1,
            "horizon_hours": 4,
            "min_abs_bias_c": 0.8,
            "max_abs_bias_c": 2.5,
            "decay_per_hour": 0.75,
        },
        "intraday_correction": {
            "negative_residual_damping": {
                "enabled": True,
                "min_reference_hour": 12,
                "multiplier": 0.5,
            },
            "negative_residual_near_term_floor": {
                "enabled": True,
                "target_hours": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "min_adjustment_mw": 500,
                "actual_reference_slack_mw": 500,
                "anchor_slack_mw": 1200,
                "drop_slope_allowance_fraction": 0.25,
                "max_drop_slope_allowance_mw": 400,
                "max_restore_mw": 700,
                "min_restore_mw": 100,
            },
            "midday_residual_deweight": {
                "enabled": True,
                "hours": [12],
                "weight": 0.25,
                "min_abs_residual_mw": 600,
            },
            "shape_guard": {
                "enabled": True,
                "min_reference_hour": 12,
                "hours": [15, 16, 17, 18, 19],
                "max_drop_mw": 1000,
            },
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1200, 1500, 2000],
                "max_decrease_mw_by_lead_hour": [1000, 1800, 2400],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 700,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [2000, 3600, 5000],
                },
            },
        },
        "adjustment": {
            "midday_transition_guard": {
                "enabled": True,
                "hours": [12],
                "min_negative_delta_mw": 500,
                "min_excess_mw": 300,
                "shrinkage": 0.5,
                "triggered_shrinkage": 0.75,
                "max_downward_adjustment_mw": 900,
                "triggered_max_downward_adjustment_mw": 1200,
                "same_day_softening_min_latest_hour": 10,
                "same_day_softening_delta_mw": -300,
                "use_recent_quantile_when_softening": True,
            },
        },
        "forecast_snapshots": {
            "enabled": True,
            "retention_days": 21,
            "max_per_day": 16,
        },
        "operational_calibration_snapshots": {
            "enabled": True,
            "retention_days": 14,
            "max_per_day": 24,
        },
        "anomaly": {
            "reserve_risk": {
                "warning_pct": DEFAULT_RESERVE_WARNING_PCT,
                "critical_pct": DEFAULT_RESERVE_CRITICAL_PCT,
            },
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

_CACHE_COLS = [
    "ts", "actual_mw", "forecast_mw", "usage_pct", "supply_mw",
    "temp_c", "apparent_temp_c", "humidity_pct", "discomfort_index",
    "weather_source",
]
_CACHE_PATH_NAME = ".hourly_cache.parquet"


def _cache_default_value(col: str):
    return None if col == "weather_source" else float("nan")


def load_hourly_cache(out_dir: Path) -> pd.DataFrame:
    p = out_dir / _CACHE_PATH_NAME
    if p.exists():
        df = pd.read_parquet(p)
        if "ts" in df.columns and df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("Asia/Tokyo")
        for col in ["temp_c", "apparent_temp_c", "humidity_pct", "discomfort_index", "weather_source"]:
            if col not in df.columns:
                df[col] = _cache_default_value(col)
        return df
    return pd.DataFrame(columns=_CACHE_COLS)


def save_hourly_cache(out_dir: Path, cache: pd.DataFrame) -> None:
    if cache.empty:
        return
    (out_dir / _CACHE_PATH_NAME).parent.mkdir(parents=True, exist_ok=True)
    save_cols = [c for c in _CACHE_COLS if c in cache.columns]
    to_save = cache[save_cols].copy()
    if "actual_mw" in to_save.columns:
        to_save["_actual_rank"] = to_save["actual_mw"].notna().astype(int)
        to_save = (
            to_save.sort_values(["ts", "_actual_rank"], ascending=[True, False])
                   .drop_duplicates(subset=["ts"], keep="first")
                   .drop(columns=["_actual_rank"])
        )
    else:
        to_save = to_save.drop_duplicates(subset=["ts"], keep="first")
    to_save.sort_values("ts").to_parquet(out_dir / _CACHE_PATH_NAME, index=False)


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


def _reserve_risk_severity_from_alerts_payload(payload: dict | None) -> str | None:
    """Return status severity from reserve-risk alerts only.

    The dashboard's day badge represents TEPCO usage-rate risk:
    stable below 92%, warning from 92% to below 97%, critical at 97%+.
    Forecast interval misses and drift can still appear in the alert list, but
    they should not turn the day tab into a usage-risk warning.
    """
    if payload is None:
        return None

    severities = [
        event.get("severity", "info")
        for event in payload.get("events", [])
        if event.get("type") == "reserve_risk"
    ]
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "info"


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


def _normalize_forecast_bands(
    fc_list: list[HourlyForecast],
    config: dict | None = None,
) -> list[HourlyForecast]:
    result: list[HourlyForecast] = []
    for forecast in fc_list:
        point_forecast_mw = round(float(forecast.forecast_mw), 1)
        ordered_p95_lower = round(
            min(float(forecast.p95_lower_mw), float(forecast.p95_upper_mw), point_forecast_mw),
            1,
        )
        ordered_p95_upper = round(
            max(float(forecast.p95_lower_mw), float(forecast.p95_upper_mw), point_forecast_mw),
            1,
        )
        half_lo, half_hi = calibrate_p95_half_widths(
            point_forecast_mw - ordered_p95_lower,
            ordered_p95_upper - point_forecast_mw,
            config,
        )
        p95_lower = round(point_forecast_mw - half_lo, 1)
        p95_upper = round(point_forecast_mw + half_hi, 1)
        p99_lower = round(p95_lower - half_lo, 1)
        p99_upper = round(p95_upper + half_hi, 1)
        result.append(HourlyForecast(
            ts=forecast.ts,
            forecast_mw=point_forecast_mw,
            p95_lower_mw=p95_lower,
            p95_upper_mw=p95_upper,
            p99_lower_mw=p99_lower,
            p99_upper_mw=p99_upper,
        ))
    return result


def build_forecast_json(d: date, fc_list: list, config: dict, model_name: str = "baseline_dow_hour_mean") -> dict:
    if not fc_list:
        return {
            "date": d.isoformat(),
            "timezone": "Asia/Tokyo",
            "availability": "not_yet_available",
            "series": [],
            "message": "Insufficient historical data for this date.",
        }
    fc_list = _normalize_forecast_bands(fc_list, config)
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


def _load_existing_forecast(out_dir: Path, d: date) -> tuple[list[HourlyForecast], str | None]:
    """Load an already-published forecast for d, if it exists.

    Daily ETL runs after the operating day has finished.  If a forecast JSON was
    already published by the previous day's status/intraday runs, preserve it so
    the dashboard and operational accuracy report continue to compare against
    the forecast users actually saw.
    """
    forecast_path = out_dir / "forecast" / f"{d.isoformat()}.json"
    if not forecast_path.exists():
        return [], None
    try:
        data = json.loads(forecast_path.read_text(encoding="utf-8"))
        result = [
            HourlyForecast(
                ts=pt["ts"],
                forecast_mw=pt["forecastMw"],
                p95_lower_mw=pt["p95LowerMw"],
                p95_upper_mw=pt["p95UpperMw"],
                p99_lower_mw=pt["p99LowerMw"],
                p99_upper_mw=pt["p99UpperMw"],
            )
            for pt in data.get("series", [])
            if pt.get("forecastMw") is not None
        ]
        model_name = data.get("model", {}).get("name")
        return result, model_name
    except Exception as e:
        print(f"[WARN] Failed to read existing forecast/{d.isoformat()}.json: {e}", file=sys.stderr)
        return [], None


def _to_jst_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(JST)
    return ts.tz_convert(JST)


def _load_observed_actual_hours(out_dir: Path, d: date) -> set[int]:
    """Return hours with a real observed actual in actual/d.json.

    The marked TEPCO fallback for the final hour is intentionally excluded. It
    is useful as a temporary lag input, but it is not an observed actual.
    """
    actual_path = out_dir / "actual" / f"{d.isoformat()}.json"
    if not actual_path.exists():
        return set()

    try:
        data = json.loads(actual_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Failed to read actual/{d.isoformat()}.json: {e}", file=sys.stderr)
        return set()

    observed_hours: set[int] = set()
    for pt in data.get("series", []):
        if pt.get("actualMw") is None:
            continue
        if pt.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE:
            continue
        try:
            ts = _to_jst_timestamp(pt["ts"])
        except Exception:
            continue
        if ts.date() == d:
            observed_hours.add(ts.hour)
    return observed_hours


def _freeze_observed_forecast_hours(
    out_dir: Path,
    d: date,
    forecasts: list[HourlyForecast],
    model_name: str,
    preserve_observed_hours: bool = True,
) -> tuple[list[HourlyForecast], str]:
    """Keep already-published forecasts for hours that now have actuals.

    Intraday runs rebuild the whole day each time. Without this guard, a past
    hour can appear to change after the actual value arrived because the raw
    model is re-run without the intraday residual correction that was active
    before that hour was observed.
    """
    if not preserve_observed_hours:
        print(f"[FORECAST] Rebuilt observed forecast hours for {d.isoformat()}")
        return forecasts, model_name

    observed_hours = _load_observed_actual_hours(out_dir, d)
    if not observed_hours:
        return forecasts, model_name

    existing_forecasts, existing_model_name = _load_existing_forecast(out_dir, d)
    if not existing_forecasts:
        return forecasts, model_name

    existing_by_hour: dict[int, HourlyForecast] = {}
    for forecast in existing_forecasts:
        try:
            ts = _to_jst_timestamp(forecast.ts)
        except Exception:
            continue
        if ts.date() == d:
            existing_by_hour[ts.hour] = forecast

    frozen_count = 0
    result: list[HourlyForecast] = []
    for forecast in forecasts:
        try:
            ts = _to_jst_timestamp(forecast.ts)
        except Exception:
            result.append(forecast)
            continue
        if ts.date() == d and ts.hour in observed_hours and ts.hour in existing_by_hour:
            result.append(existing_by_hour[ts.hour])
            frozen_count += 1
        else:
            result.append(forecast)

    if frozen_count:
        print(f"[FORECAST] Preserved {frozen_count} observed forecast hours for {d.isoformat()}")
    if forecasts and frozen_count == len(forecasts) and existing_model_name:
        return result, existing_model_name
    return result, model_name


def _inject_today_actuals(out_dir: Path, today: date, cache: pd.DataFrame) -> pd.DataFrame:
    """Inject actual_mw from actual/ JSONs for dates missing from cache.

    Covers today (lag_24h for tomorrow) and any recent days not yet in the
    hourly cache (e.g. yesterday when TEPCO CSV hasn't been published yet).
    Missing published actuals temporarily use TEPCO forecasts as lag inputs until
    the monthly CSV provides final observed values.
    """
    if cache.empty or "ts" not in cache.columns:
        normalized_cache = cache.copy()
        cached_actuals = pd.Series(dtype="float64")
    else:
        normalized_cache = cache.copy()
        normalized_cache["ts"] = pd.to_datetime(normalized_cache["ts"], utc=True).dt.tz_convert("Asia/Tokyo")
        cached_actuals = (
            normalized_cache.set_index("ts")["actual_mw"]
            if "actual_mw" in normalized_cache.columns
            else pd.Series(dtype="float64")
        )

    updates: dict = {}
    actual_dir = out_dir / "actual"
    lookback = [today - timedelta(days=i) for i in range(8)]
    for d in lookback:
        actual_path = actual_dir / f"{d.isoformat()}.json"
        if not actual_path.exists():
            continue
        try:
            data = json.loads(actual_path.read_text(encoding="utf-8"))
            for pt in data.get("series", []):
                ts = pd.Timestamp(pt["ts"]).tz_convert("Asia/Tokyo")
                actual_mw = pt.get("actualMw")
                is_fallback = pt.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE
                if actual_mw is None:
                    actual_mw = pt.get("tepcoForecastMw")
                    is_fallback = True
                    if actual_mw is None:
                        continue
                existing_actual = cached_actuals.loc[ts] if ts in cached_actuals.index else float("nan")
                if isinstance(existing_actual, pd.Series):
                    existing_actual = existing_actual.dropna().iloc[0] if existing_actual.notna().any() else float("nan")
                if is_fallback and pd.notna(existing_actual):
                    continue
                updates[ts] = {
                    "actual_mw":   actual_mw,
                    "forecast_mw": pt.get("tepcoForecastMw"),
                    "usage_pct":   pt.get("usagePct"),
                    "supply_mw":   pt.get("supplyMw"),
                }
        except Exception as e:
            print(f"[WARN] Failed to read actual/{d.isoformat()}.json: {e}", file=sys.stderr)

    if not updates:
        return cache

    upd_df = pd.DataFrame(
        [{"ts": ts, **vals} for ts, vals in updates.items()]
    ).set_index("ts")

    result = normalized_cache.set_index("ts")
    update_cols = [c for c in ("actual_mw", "forecast_mw", "usage_pct", "supply_mw")
                   if c in upd_df.columns and c in result.columns]
    result.update(upd_df[update_cols])
    result = result.reset_index()

    # Add rows for timestamps not yet in cache at all
    new_ts = set(upd_df.index) - set(result["ts"])
    if new_ts:
        new_rows = []
        for ts in new_ts:
            row: dict = {"ts": ts, "temp_c": float("nan")}
            for c in ("actual_mw", "forecast_mw", "usage_pct", "supply_mw"):
                value = upd_df.loc[ts, c] if c in upd_df.columns else None
                row[c] = float(value) if value is not None and pd.notna(value) else float("nan")
            new_rows.append({c: row.get(c, _cache_default_value(c)) for c in _CACHE_COLS})
        result = pd.concat(
            [result, pd.DataFrame(new_rows)], ignore_index=True
        ).sort_values("ts").reset_index(drop=True)

    injected_dates = sorted({ts.date() for ts in updates})
    print(f"[STATUS] Injected actuals for {[d.isoformat() for d in injected_dates]} ({len(updates)} rows)")
    return result


def _make_day_context(inf_features: pd.DataFrame, config: dict) -> dict:
    """Build day-level context dict for anomaly detector enrichment."""
    adj_cfg   = config.get("adjustment", {}).get("post_holiday_timeband_guard", {})
    min_consec = int(adj_cfg.get("min_consec_holiday_len", 3))
    max_dsh    = int(adj_cfg.get("max_days_since_holiday_end", 1))
    try:
        row0 = inf_features.iloc[0]
        post_holiday_early_morning = (
            float(row0["consec_holiday_len"]) >= min_consec
            and float(row0["days_since_holiday_end"]) <= max_dsh
        )
    except Exception:
        post_holiday_early_morning = False
    return {"post_holiday_early_morning": post_holiday_early_morning}


def _build_today_alerts(
    out_dir: Path,
    today: date,
    config: dict,
    day_context: dict | None = None,
) -> dict | None:
    """Build and write alerts JSON for one date. Returns the payload, or None on failure."""
    actual_path  = out_dir / "actual"   / f"{today.isoformat()}.json"
    forecast_path = out_dir / "forecast" / f"{today.isoformat()}.json"
    alerts_path  = out_dir / "alerts"   / f"{today.isoformat()}.json"

    if not actual_path.exists() or not forecast_path.exists():
        return
    try:
        actual_data = json.loads(actual_path.read_text(encoding="utf-8"))
        rows = []
        for pt in actual_data.get("series", []):
            if pt.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE:
                continue
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

        events = detect_anomalies(hourly, fc_list, config.get("anomaly", {}), day_context)
        payload = build_alerts_json(today, events)
        write_json(alerts_path, payload)
        print(f"[STATUS] Alerts {today.isoformat()}: {len(events)} events -> {alerts_path.name}")
        return payload
    except Exception as e:
        print(f"[WARN] Failed to build today alerts: {e}", file=sys.stderr)
    return None


def _build_alerts_for_date(
    out_dir: Path,
    d: date,
    config: dict,
    cache: pd.DataFrame,
) -> dict | None:
    """Rebuild alerts for any actual/forecast date using the current anomaly config."""
    day_context = None
    try:
        from python.forecast.feature_builder import build_inference_features
        day_context = _make_day_context(build_inference_features(cache, d, config), config)
    except Exception:
        pass
    return _build_today_alerts(out_dir, d, config, day_context=day_context)


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


def _forecast_severity(
    fc_list: list,
    cache: pd.DataFrame,
    config: dict,
    allow_critical: bool = True,
) -> str:
    """Estimate severity from peak forecast vs recent supply."""
    if not fc_list:
        return "info"
    peak_forecast = max(fc_list, key=lambda f: f.forecast_mw)
    peak_fc_mw = peak_forecast.forecast_mw
    recent_supply = None
    if "supply_mw" in cache.columns:
        supply_df = cache[["ts", "supply_mw"]].dropna(subset=["supply_mw"]).copy()
        if not supply_df.empty:
            try:
                peak_ts = _to_jst_timestamp(peak_forecast.ts)
                exact_supply = supply_df.loc[supply_df["ts"] == peak_ts, "supply_mw"].dropna()
                if not exact_supply.empty:
                    recent_supply = float(exact_supply.iloc[-1])
            except Exception:
                recent_supply = None
        if recent_supply is None:
            # p75 of recent weekday supply: robust against GW-low outliers and peak-day highs
            weekday_supply = supply_df[supply_df["ts"].dt.dayofweek < 5].tail(24 * 14)
            if not weekday_supply.empty:
                recent_supply = weekday_supply["supply_mw"].quantile(0.75)
    if recent_supply and recent_supply > 0:
        est_pct = peak_fc_mw / recent_supply * 100
        rr = config.get("anomaly", {}).get("reserve_risk", {})
        if est_pct >= rr.get("critical_pct", DEFAULT_RESERVE_CRITICAL_PCT):
            return "critical" if allow_critical else "warning"
        if est_pct >= rr.get("warning_pct", DEFAULT_RESERVE_WARNING_PCT):
            return "warning"
    return "info"


def _enrich_latest_temp(latest: dict | None, cache: pd.DataFrame) -> dict | None:
    if not latest or "peakActualAt" not in latest or "temp_c" not in cache.columns:
        return latest
    try:
        peak_ts = pd.Timestamp(latest["peakActualAt"]).tz_convert("Asia/Tokyo")
        temp_row = cache.loc[cache["ts"] == peak_ts, "temp_c"]
        if not temp_row.empty and pd.notna(temp_row.iloc[0]):
            return {**latest, "peakTempC": round(float(temp_row.iloc[0]), 1)}
    except Exception:
        pass
    return latest


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
    today_severity: str | None = None,
    extended_cache: pd.DataFrame | None = None,
    display_cache: pd.DataFrame | None = None,
) -> dict:
    coverage_to = max(ok_set) if ok_set else None
    latest = summaries.get(coverage_to.isoformat()) if coverage_to else None
    missing = compute_missing_days(csv_dates)
    availability = "ok" if ok_set else ("failed" if fail_set else "not_yet_available")

    def _fc_summary(d: date, fc_list: list, override_sev: str | None = None) -> dict | None:
        if not fc_list:
            return None
        peak = peak_of_forecasts(fc_list)
        sev = (
            override_sev
            if override_sev is not None
            else _forecast_severity(
                fc_list,
                extended_cache if extended_cache is not None else cache,
                config,
                allow_critical=d <= today,
            )
        )
        result = {
            "date": d.isoformat(),
            "peakForecastMw": peak["forecastMw"] if peak else None,
            "peakForecastAt": peak["at"] if peak else None,
            "severity": sev,
        }
        if peak and extended_cache is not None and "temp_c" in extended_cache.columns:
            peak_ts = pd.Timestamp(peak["at"]).tz_convert("Asia/Tokyo")
            temp_source = display_cache if display_cache is not None else extended_cache
            if "ts" not in temp_source.columns or "temp_c" not in temp_source.columns:
                return result
            temp_row = temp_source.loc[temp_source["ts"] == peak_ts, "temp_c"]
            if not temp_row.empty and pd.notna(temp_row.iloc[0]):
                result["peakTempC"] = round(float(temp_row.iloc[0]), 1)
        return result

    yesterday = today - timedelta(days=1)
    return {
        "project": "tokyo-grid-ems",
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "lastUpdatedAt": ts_now(),
        "coverageTo": coverage_to.isoformat() if coverage_to else None,
        "availability": availability,
        "missingDays": missing,
        "failedDays": [d.isoformat() for d in sorted(fail_set)],
        "latest": _enrich_latest_temp(latest, cache),
        "yesterday": yesterday.isoformat(),
        "today": _fc_summary(today, today_fc, today_severity),
        "tomorrow": _fc_summary(tomorrow, tomorrow_fc),
    }

# ---------------------------------------------------------------------------
# LightGBM helpers
# ---------------------------------------------------------------------------

def _try_load_lgbm(out_dir: Path):
    """Load saved LGBMForecaster from disk. Returns forecaster or None."""
    model_path = out_dir / _LGBM_MODEL_NAME
    if not model_path.exists():
        return None
    try:
        from python.forecast.lgbm_model import LGBMForecaster
        forecaster = LGBMForecaster.load(model_path)
        if hasattr(forecaster, "is_compatible") and not forecaster.is_compatible():
            print("[WARN] LightGBM model feature version is stale; retraining required", file=sys.stderr)
            return None
        return forecaster
    except Exception as e:
        print(f"[WARN] LightGBM load failed: {e}", file=sys.stderr)
        return None


def _try_train_lgbm(cache: pd.DataFrame, out_dir: Path, config: dict | None = None):
    """Train and save LGBMForecaster. Returns forecaster or None on any failure."""
    if len(cache) < _LGBM_MIN_ROWS:
        return None
    try:
        from python.forecast.lgbm_model import LGBMForecaster
        forecaster = LGBMForecaster(config=config)
        forecaster.fit(cache)
        forecaster.save(out_dir / _LGBM_MODEL_NAME)
        print(f"[LGBM] Trained and saved -> {_LGBM_MODEL_NAME}")
        return forecaster
    except ImportError:
        return None
    except Exception as e:
        print(f"[WARN] LightGBM training failed: {e}", file=sys.stderr)
        return None


def _try_train_lgbm_as_of(
    cache: pd.DataFrame,
    cutoff_date: date,
    config: dict | None = None,
):
    """Train a temporary LightGBM model using only rows before cutoff_date."""
    cutoff_ts = pd.Timestamp(cutoff_date, tz=JST)
    train_cache = cache[cache["ts"] < cutoff_ts].copy()
    if len(train_cache) < _LGBM_MIN_ROWS:
        return None
    try:
        from python.forecast.lgbm_model import LGBMForecaster
        forecaster = LGBMForecaster(config=config)
        forecaster.fit(train_cache)
        return forecaster
    except ImportError:
        return None
    except Exception as e:
        print(f"[WARN] Historical LightGBM training failed for {cutoff_date}: {e}", file=sys.stderr)
        return None



def _extend_cache_with_forecast_weather(cache: pd.DataFrame, days: int = 3) -> pd.DataFrame:
    """Upsert virtual forecast-weather rows for upcoming days.

    build_inference_features looks up temp_c for the target_date from cache,
    so these virtual rows make forecast temperatures available to the model. Existing
    virtual rows are refreshed because intraday weather forecasts can change materially.
    Rows with actual_mw are treated as historical observations and are not overwritten.
    """
    try:
        from python.etl.fetch_weather import fetch_forecast_temps
        weather = fetch_forecast_temps(days=days)
    except Exception as e:
        print(f"[WARN] Forecast weather fetch failed: {e}", file=sys.stderr)
        return cache

    result = cache.copy()
    for col in _CACHE_COLS:
        if col not in result.columns:
            result[col] = _cache_default_value(col)

    weather_cols = [
        col
        for col in ["ts", "temp_c", "apparent_temp_c", "humidity_pct", "discomfort_index", "weather_source"]
        if col in weather.columns
    ]
    weather_temp = weather[weather_cols].copy()
    forecast_col_map = {
        col: f"_forecast_{col}"
        for col in weather_cols
        if col != "ts"
    }
    result = result.merge(
        weather_temp.rename(columns=forecast_col_map),
        on="ts",
        how="left",
    )
    for col, forecast_col in forecast_col_map.items():
        can_refresh = (
            result["actual_mw"].isna()
            & result[forecast_col].notna()
        )
        result.loc[can_refresh, col] = result.loc[can_refresh, forecast_col]
    result = result.drop(columns=list(forecast_col_map.values()))

    existing_ts = set(result["ts"])
    new_rows = weather_temp[~weather_temp["ts"].isin(existing_ts)].copy()
    for col in _CACHE_COLS:
        if col not in new_rows.columns:
            new_rows[col] = _cache_default_value(col)

    result = pd.concat([result[_CACHE_COLS], new_rows[_CACHE_COLS]], ignore_index=True)
    return result.sort_values("ts").reset_index(drop=True)


def _bounded_float(value, default: float, min_value: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if min_value is not None:
        result = max(min_value, result)
    return result


def _apply_weather_forecast_bias_correction(
    cache: pd.DataFrame,
    config: dict,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Nudge near-term same-day forecast weather toward recent observed weather.

    This corrects the weather input, not the electric demand target. If the
    forecast has been too cold or too warm during the last few observed hours,
    apply a capped, fading +/- adjustment to the next same-day forecast hours.
    """
    cfg = config.get("weather_forecast_bias_correction", {})
    if not cfg.get("enabled", True) or cache.empty or "ts" not in cache.columns:
        return cache

    lookback_hours = _bounded_float(cfg.get("lookback_hours"), 4.0, min_value=1.0)
    observation_lag_hours = _bounded_float(cfg.get("observation_lag_hours"), 1.0, min_value=0.0)
    horizon_hours = int(_bounded_float(cfg.get("horizon_hours"), 3.0, min_value=1.0))
    min_abs_bias_c = _bounded_float(cfg.get("min_abs_bias_c"), 1.5, min_value=0.0)
    max_abs_bias_c = _bounded_float(cfg.get("max_abs_bias_c"), 1.5, min_value=0.1)
    decay_per_hour = min(1.0, _bounded_float(cfg.get("decay_per_hour"), 0.6, min_value=0.0))

    now_ts = _to_jst_timestamp(now or datetime.now(tz=JST))
    observed_cutoff = now_ts - pd.Timedelta(hours=observation_lag_hours)
    observed_start = max(
        pd.Timestamp(now_ts.date(), tz=JST),
        observed_cutoff - pd.Timedelta(hours=lookback_hours),
    )

    result = cache.copy()
    for col in _CACHE_COLS:
        if col not in result.columns:
            result[col] = _cache_default_value(col)
    result["ts"] = pd.to_datetime(result["ts"], utc=True).dt.tz_convert("Asia/Tokyo")

    try:
        from python.etl.fetch_weather import fetch_past_temps
        observed_weather = fetch_past_temps(now_ts.date(), now_ts.date())
    except Exception as e:
        print(f"[WARN] Weather bias correction fetch failed: {e}", file=sys.stderr)
        return cache

    if observed_weather.empty:
        return cache
    observed_weather = observed_weather.copy()
    observed_weather["ts"] = pd.to_datetime(observed_weather["ts"], utc=True).dt.tz_convert("Asia/Tokyo")
    observed_weather = observed_weather[
        (observed_weather["ts"] >= observed_start)
        & (observed_weather["ts"] <= observed_cutoff)
    ]
    if observed_weather.empty:
        return cache

    forecast_weather = result[["ts", "temp_c", "apparent_temp_c"]].copy()
    comparison = observed_weather.merge(
        forecast_weather.rename(columns={
            "temp_c": "_forecast_temp_c",
            "apparent_temp_c": "_forecast_apparent_temp_c",
        }),
        on="ts",
        how="inner",
    )
    comparison = comparison.dropna(subset=["temp_c", "_forecast_temp_c"])
    if comparison.empty:
        return cache

    temp_bias = float((comparison["temp_c"] - comparison["_forecast_temp_c"]).median())
    temp_bias = max(-max_abs_bias_c, min(max_abs_bias_c, temp_bias))
    if abs(temp_bias) < min_abs_bias_c:
        temp_bias = 0.0

    apparent_bias = temp_bias
    has_apparent_bias = False
    if "apparent_temp_c" in comparison.columns and "_forecast_apparent_temp_c" in comparison.columns:
        apparent_comparison = comparison.dropna(subset=["apparent_temp_c", "_forecast_apparent_temp_c"])
        if not apparent_comparison.empty:
            has_apparent_bias = True
            apparent_bias = float(
                (apparent_comparison["apparent_temp_c"] - apparent_comparison["_forecast_apparent_temp_c"]).median()
            )
            apparent_bias = max(-max_abs_bias_c, min(max_abs_bias_c, apparent_bias))
            if abs(apparent_bias) < min_abs_bias_c:
                apparent_bias = 0.0

    if not has_apparent_bias:
        apparent_bias = temp_bias
    if temp_bias == 0.0 and apparent_bias == 0.0:
        return cache

    future_mask = (
        (result["ts"].dt.date == now_ts.date())
        & (result["ts"] > observed_cutoff)
        & result["actual_mw"].isna()
    )
    future_index = list(result.loc[future_mask].sort_values("ts").index[:horizon_hours])
    if not future_index:
        return cache

    for step, idx in enumerate(future_index):
        decay = decay_per_hour ** step
        if temp_bias != 0.0 and pd.notna(result.at[idx, "temp_c"]):
            result.at[idx, "temp_c"] = result.at[idx, "temp_c"] + temp_bias * decay
        if apparent_bias != 0.0 and pd.notna(result.at[idx, "apparent_temp_c"]):
            result.at[idx, "apparent_temp_c"] = result.at[idx, "apparent_temp_c"] + apparent_bias * decay

    latest_observed_hour = comparison["ts"].max().hour
    first_adjusted_hour = int(result.loc[future_index[0], "ts"].hour)
    last_adjusted_hour = int(result.loc[future_index[-1], "ts"].hour)
    print(
        "[WEATHER] Forecast bias correction "
        f"{now_ts.date()}: temp_bias={temp_bias:+.1f}C apparent_bias={apparent_bias:+.1f}C "
        f"(samples={len(comparison)}, latest_obs={latest_observed_hour:02d}:00, "
        f"hours={first_adjusted_hour:02d}-{last_adjusted_hour:02d})"
    )
    return result.sort_values("ts").reset_index(drop=True)


def _make_adjuster(config: dict):
    """Instantiate AnalogousDayAdjuster from config. Returns None on import failure."""
    try:
        from python.forecast.adjustment import AnalogousDayAdjuster
        return AnalogousDayAdjuster(config)
    except Exception as e:
        print(f"[WARN] AnalogousDayAdjuster init failed: {e}", file=sys.stderr)
        return None


def _make_guard(config: dict):
    """Instantiate PostHolidayTimeBandGuard from config. Returns None on import failure."""
    try:
        from python.forecast.adjustment import PostHolidayTimeBandGuard
        cfg = config.get("adjustment", {}).get("post_holiday_timeband_guard", {})
        if not cfg.get("enabled", True):
            return None
        return PostHolidayTimeBandGuard(config)
    except Exception as e:
        print(f"[WARN] PostHolidayTimeBandGuard init failed: {e}", file=sys.stderr)
        return None


def _make_midday_guard(config: dict):
    """Instantiate MiddayTransitionGuard from config. Returns None on import failure."""
    try:
        from python.forecast.adjustment import MiddayTransitionGuard
        cfg = config.get("adjustment", {}).get("midday_transition_guard", {})
        if not cfg.get("enabled", True):
            return None
        return MiddayTransitionGuard(config)
    except Exception as e:
        print(f"[WARN] MiddayTransitionGuard init failed: {e}", file=sys.stderr)
        return None


def _build_forecast_pipeline(
    forecaster,
    cache: pd.DataFrame,
    target_date: date,
    n_weeks: int,
    min_samples: int,
    config: dict | None = None,
    adjuster=None,
    guard=None,
    midday_guard=None,
) -> ForecastBuildResult:
    """Return forecast output plus intermediate stages.

    Pipeline: LightGBM → AnalogousDayAdjuster → PostHolidayTimeBandGuard → output.
    Falls back to baseline when LightGBM is unavailable or fails.
    """
    if forecaster is not None:
        try:
            from python.forecast.feature_builder import build_inference_features
            inference_features = build_inference_features(
                cache,
                target_date,
                config,
                include_context=True,
            )
            raw_lgbm_forecasts = forecaster.predict(target_date, cache)
            analog_adjusted_forecasts = (
                adjuster.adjust(
                    forecaster,
                    raw_lgbm_forecasts,
                    cache,
                    target_date,
                    inference_features,
                )
                if adjuster
                else raw_lgbm_forecasts
            )
            guarded_forecasts = (
                guard.apply(raw_lgbm_forecasts, analog_adjusted_forecasts, inference_features)
                if guard
                else analog_adjusted_forecasts
            )
            midday_guarded_forecasts = (
                midday_guard.apply(guarded_forecasts, inference_features)
                if midday_guard
                else guarded_forecasts
            )
            return ForecastBuildResult(
                forecasts=midday_guarded_forecasts,
                model_name="lgbm_quantile_q50",
                stages={
                    "raw_lgbm": raw_lgbm_forecasts,
                    "analog_adjusted": analog_adjusted_forecasts,
                    "post_holiday_guarded": guarded_forecasts,
                    "midday_guarded": midday_guarded_forecasts,
                    "pre_calibration": midday_guarded_forecasts,
                },
            )
        except Exception as e:
            print(f"[WARN] LightGBM predict failed for {target_date}: {e}", file=sys.stderr)
    baseline_forecasts = compute_forecast(cache, target_date, n_weeks, min_samples)
    return ForecastBuildResult(
        forecasts=baseline_forecasts,
        model_name="baseline_dow_hour_mean",
        stages={
            "baseline": baseline_forecasts,
            "pre_calibration": baseline_forecasts,
        },
    )


def _build_forecast_with_fallback(
    forecaster,
    cache: pd.DataFrame,
    target_date: date,
    n_weeks: int,
    min_samples: int,
    config: dict | None = None,
    adjuster=None,
    guard=None,
    midday_guard=None,
) -> tuple[list, str]:
    """Return (forecasts, model_name), preserving the historical helper API."""
    result = _build_forecast_pipeline(
        forecaster,
        cache,
        target_date,
        n_weeks,
        min_samples,
        config,
        adjuster,
        guard,
        midday_guard,
    )
    return result.forecasts, result.model_name


def _load_actual_series(out_dir: Path, target_date: date) -> list[dict]:
    actual_path = out_dir / "actual" / f"{target_date.isoformat()}.json"
    if not actual_path.exists():
        return []
    try:
        data = json.loads(actual_path.read_text(encoding="utf-8"))
        return data.get("series", [])
    except Exception as e:
        print(f"[WARN] Failed to read actual/{target_date.isoformat()}.json: {e}", file=sys.stderr)
        return []


def _forecast_snapshot_config(config: dict) -> dict:
    snapshot_config = config.get("forecast_snapshots", {})
    return {
        "enabled": bool(snapshot_config.get("enabled", True)),
        "retention_days": max(int(snapshot_config.get("retention_days", 21)), 1),
        "max_per_day": max(int(snapshot_config.get("max_per_day", 16)), 1),
    }


def _snapshot_filename(generated_at: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in generated_at)
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "snapshot"


def _actual_observation_summary(actual_series: list[dict]) -> dict:
    actual_hours: set[int] = set()
    observed_hours: set[int] = set()
    fallback_hours: set[int] = set()
    for point in actual_series:
        if point.get("actualMw") is None:
            continue
        try:
            hour = int(str(point.get("ts", ""))[11:13])
        except ValueError:
            continue
        actual_hours.add(hour)
        if point.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE:
            fallback_hours.add(hour)
        else:
            observed_hours.add(hour)

    return {
        "actualHoursAtGeneration": len(actual_hours),
        "observedActualHoursAtGeneration": len(observed_hours),
        "fallbackActualHoursAtGeneration": len(fallback_hours),
        "lastActualHour": max(actual_hours) if actual_hours else None,
        "lastObservedActualHour": max(observed_hours) if observed_hours else None,
        "lastFallbackActualHour": max(fallback_hours) if fallback_hours else None,
    }


def _forecast_hour_map(forecasts: list[HourlyForecast]) -> dict[int, HourlyForecast]:
    return {
        pd.Timestamp(forecast.ts).hour: forecast
        for forecast in forecasts
    }


def _forecast_stage_summary(stages: dict[str, list[HourlyForecast]]) -> dict:
    return {
        name: {
            "hours": len(forecasts),
            "peak": peak_of_forecasts(forecasts),
        }
        for name, forecasts in stages.items()
    }


def _forecast_stage_rows(stages: dict[str, list[HourlyForecast]]) -> list[dict]:
    if not stages:
        return []

    stage_maps = {
        name: _forecast_hour_map(forecasts)
        for name, forecasts in stages.items()
    }
    hours = sorted({
        hour
        for forecasts_by_hour in stage_maps.values()
        for hour in forecasts_by_hour
    })
    rows = []
    for hour in hours:
        ts = None
        forecasts_by_stage = {}
        for name, forecasts_by_hour in stage_maps.items():
            forecast = forecasts_by_hour.get(hour)
            if forecast is None:
                continue
            ts = ts or forecast.ts
            forecasts_by_stage[name] = round(float(forecast.forecast_mw), 1)
        rows.append({
            "hour": hour,
            "ts": ts,
            "forecastMwByStage": forecasts_by_stage,
        })
    return rows


def _snapshot_sort_key(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = str(payload.get("generatedAt") or "")
    except Exception:
        generated_at = ""
    return generated_at, path.name


def _snapshot_index_entry(path: Path, out_dir: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Failed to read forecast snapshot {path}: {e}", file=sys.stderr)
        return None

    observation_summary = payload.get("observationSummary", {})
    return {
        "targetDate": payload.get("targetDate"),
        "generatedAt": payload.get("generatedAt"),
        "runType": payload.get("runType"),
        "path": path.relative_to(out_dir).as_posix(),
        "model": payload.get("model"),
        "peak": payload.get("peak"),
        "observedActualHoursAtGeneration": observation_summary.get("observedActualHoursAtGeneration"),
        "fallbackActualHoursAtGeneration": observation_summary.get("fallbackActualHoursAtGeneration"),
        "lastObservedActualHour": observation_summary.get("lastObservedActualHour"),
    }


def _prune_forecast_snapshots(
    out_dir: Path,
    current_date: date,
    retention_days: int,
    max_per_day: int,
) -> None:
    snapshot_root = out_dir / _FORECAST_SNAPSHOT_PATH_NAME
    if not snapshot_root.exists():
        return

    cutoff_date = current_date - timedelta(days=retention_days - 1)
    for date_dir in snapshot_root.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            target_date = date.fromisoformat(date_dir.name)
        except ValueError:
            continue
        if target_date < cutoff_date:
            shutil.rmtree(date_dir)
            continue

        snapshot_files = sorted(
            [
                path for path in date_dir.glob("*.json")
                if path.name != "index.json"
            ],
            key=_snapshot_sort_key,
        )
        for stale_file in snapshot_files[:-max_per_day]:
            stale_file.unlink()


def _write_forecast_snapshot_indexes(out_dir: Path, generated_at: str, config: dict) -> None:
    snapshot_root = out_dir / _FORECAST_SNAPSHOT_PATH_NAME
    if not snapshot_root.exists():
        return

    snapshot_config = _forecast_snapshot_config(config)
    dates: list[dict] = []
    for date_dir in sorted(path for path in snapshot_root.iterdir() if path.is_dir()):
        snapshot_files = sorted(
            [
                path for path in date_dir.glob("*.json")
                if path.name != "index.json"
            ],
            key=_snapshot_sort_key,
        )
        entries = [
            entry for entry in (
                _snapshot_index_entry(path, out_dir)
                for path in snapshot_files
            )
            if entry is not None
        ]
        if not entries:
            continue

        date_index = {
            "schemaVersion": "1.0.0",
            "timezone": "Asia/Tokyo",
            "generatedAt": generated_at,
            "targetDate": date_dir.name,
            "snapshots": entries,
        }
        write_json(date_dir / "index.json", date_index)
        dates.append({
            "date": date_dir.name,
            "path": (date_dir / "index.json").relative_to(out_dir).as_posix(),
            "snapshotCount": len(entries),
            "latest": entries[-1],
        })

    write_json(snapshot_root / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "retentionDays": snapshot_config["retention_days"],
        "maxPerDay": snapshot_config["max_per_day"],
        "dates": dates,
    })


def _write_forecast_snapshot(
    out_dir: Path,
    target_date: date,
    forecasts: list[HourlyForecast],
    config: dict,
    model_name: str,
    generated_at: str,
    run_type: str,
    preserve_observed_forecast_hours: bool,
    stage_forecasts: dict[str, list[HourlyForecast]] | None = None,
) -> Path | None:
    snapshot_config = _forecast_snapshot_config(config)
    if not snapshot_config["enabled"] or not forecasts:
        return None

    forecast_json = build_forecast_json(target_date, forecasts, config, model_name)
    if forecast_json.get("availability") != "ok":
        return None

    try:
        current_date = datetime.fromisoformat(generated_at).date()
    except ValueError:
        current_date = datetime.now(tz=JST).date()
    cutoff_date = current_date - timedelta(days=snapshot_config["retention_days"] - 1)
    if target_date < cutoff_date:
        _prune_forecast_snapshots(
            out_dir,
            current_date,
            snapshot_config["retention_days"],
            snapshot_config["max_per_day"],
        )
        _write_forecast_snapshot_indexes(out_dir, generated_at, config)
        return None

    actual_series = _load_actual_series(out_dir, target_date)
    snapshot = {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "targetDate": target_date.isoformat(),
        "generatedAt": generated_at,
        "runType": run_type,
        "preserveObservedForecastHours": preserve_observed_forecast_hours,
        "model": forecast_json.get("model"),
        "peak": forecast_json.get("peak"),
        "observationSummary": _actual_observation_summary(actual_series),
        "series": forecast_json.get("series", []),
    }
    if stage_forecasts:
        snapshot["forecastBuild"] = {
            "stageSummary": _forecast_stage_summary(stage_forecasts),
            "series": _forecast_stage_rows(stage_forecasts),
        }

    snapshot_dir = out_dir / _FORECAST_SNAPSHOT_PATH_NAME / target_date.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    base_name = _snapshot_filename(generated_at)
    snapshot_path = snapshot_dir / f"{base_name}.json"
    suffix = 2
    while snapshot_path.exists():
        snapshot_path = snapshot_dir / f"{base_name}-{suffix}.json"
        suffix += 1

    write_json(snapshot_path, snapshot)
    _prune_forecast_snapshots(
        out_dir,
        current_date,
        snapshot_config["retention_days"],
        snapshot_config["max_per_day"],
    )
    _write_forecast_snapshot_indexes(out_dir, generated_at, config)
    print(
        "[SNAPSHOT] Forecast snapshot "
        f"{target_date.isoformat()} {run_type} -> {snapshot_path.relative_to(out_dir)}"
    )
    return snapshot_path


def _actual_series_by_hour(actual_series: list[dict]) -> dict[int, dict]:
    result = {}
    for point in actual_series:
        try:
            hour = int(str(point.get("ts", ""))[11:13])
        except ValueError:
            continue
        result[hour] = point
    return result


def _round_mw(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return round(float(value), 1)


def _operational_calibration_rows(
    actual_series: list[dict],
    stage_forecasts: dict[str, list[HourlyForecast]],
    post_calibration_forecasts: list[HourlyForecast],
    residual_adjustments_by_hour: list[dict] | None = None,
    inference_features: pd.DataFrame | None = None,
) -> list[dict]:
    actual_by_hour = _actual_series_by_hour(actual_series)
    stage_maps = {
        name: _forecast_hour_map(forecasts)
        for name, forecasts in stage_forecasts.items()
    }
    post_by_hour = _forecast_hour_map(post_calibration_forecasts)
    pre_by_hour = stage_maps.get("pre_calibration", {})
    residual_adjustment_map = {
        int(item["hour"]): item
        for item in (residual_adjustments_by_hour or [])
        if item.get("hour") is not None
    }
    feature_map: dict[int, pd.Series] = {}
    if inference_features is not None and not inference_features.empty:
        try:
            for _, feature_row in inference_features.iterrows():
                if "hour" not in feature_row:
                    continue
                hour_value = feature_row.get("hour")
                if pd.isna(hour_value):
                    continue
                feature_map[int(hour_value)] = feature_row
        except Exception:
            feature_map = {}
    hours = sorted(
        set(actual_by_hour)
        | set(post_by_hour)
        | {
            hour
            for forecasts_by_hour in stage_maps.values()
            for hour in forecasts_by_hour
        }
    )

    rows = []
    for hour in hours:
        actual_point = actual_by_hour.get(hour, {})
        post_forecast = post_by_hour.get(hour)
        pre_forecast = pre_by_hour.get(hour)
        ts = (
            (post_forecast.ts if post_forecast is not None else None)
            or (pre_forecast.ts if pre_forecast is not None else None)
            or actual_point.get("ts")
        )
        forecasts_by_stage = {
            name: _round_mw(forecasts_by_hour[hour].forecast_mw)
            for name, forecasts_by_hour in stage_maps.items()
            if hour in forecasts_by_hour
        }
        actual_mw = _round_mw(actual_point.get("actualMw"))
        tepco_forecast_mw = _round_mw(actual_point.get("tepcoForecastMw"))
        pre_mw = _round_mw(pre_forecast.forecast_mw if pre_forecast is not None else None)
        post_mw = _round_mw(
            post_forecast.forecast_mw if post_forecast is not None else None
        )
        previous_pre = pre_by_hour.get(hour - 1)
        previous_post = post_by_hour.get(hour - 1)
        previous_pre_mw = _round_mw(
            previous_pre.forecast_mw if previous_pre is not None else None
        )
        previous_post_mw = _round_mw(
            previous_post.forecast_mw if previous_post is not None else None
        )
        feature_row = feature_map.get(hour)
        residual_carryover = residual_adjustment_map.get(hour)
        row = {
            "hour": hour,
            "ts": ts,
            "actualMw": actual_mw,
            "actualSource": actual_point.get("actualSource"),
            "tepcoForecastMw": tepco_forecast_mw,
            "forecastMwByStage": forecasts_by_stage,
            "preCalibrationForecastMw": pre_mw,
            "postCalibrationForecastMw": post_mw,
            "forecastDeltaMw": (
                round(pre_mw - previous_pre_mw, 1)
                if pre_mw is not None and previous_pre_mw is not None
                else None
            ),
            "postCalibrationForecastDeltaMw": (
                round(post_mw - previous_post_mw, 1)
                if post_mw is not None and previous_post_mw is not None
                else None
            ),
            "lag24DeltaMw": _round_mw(
                feature_row.get("lag_24h_hourly_delta")
                if feature_row is not None
                else None
            ),
            "recentSameBusinessTypeDeltaMw": _round_mw(
                feature_row.get("recent_same_business_type_delta_mean")
                if feature_row is not None
                else None
            ),
            "sameDayActualSlopeMw": _round_mw(
                feature_row.get("same_day_latest_hourly_delta")
                if feature_row is not None
                else None
            ),
            "residualAdjustmentMw": _round_mw(
                residual_carryover.get("finalAdjustmentMw")
                if residual_carryover
                else None
            ),
            "weatherDeltaC": _round_mw(
                feature_row.get("temp_delta_24h")
                if feature_row is not None
                else None
            ),
            "calibrationDeltaMw": (
                round(post_mw - pre_mw, 1)
                if post_mw is not None and pre_mw is not None
                else None
            ),
            "actualVsPreCalibrationResidualMw": (
                round(actual_mw - pre_mw, 1)
                if actual_mw is not None and pre_mw is not None
                else None
            ),
            "actualVsPostCalibrationResidualMw": (
                round(actual_mw - post_mw, 1)
                if actual_mw is not None and post_mw is not None
                else None
            ),
            "tepcoErrorMw": (
                round(tepco_forecast_mw - actual_mw, 1)
                if tepco_forecast_mw is not None and actual_mw is not None
                else None
            ),
            "residualCarryover": residual_carryover,
        }
        rows.append(row)
    return rows


def _operational_calibration_snapshot_config(config: dict) -> dict:
    snapshot_config = config.get("operational_calibration_snapshots", {})
    return {
        "enabled": bool(snapshot_config.get("enabled", True)),
        "retention_days": max(int(snapshot_config.get("retention_days", 14)), 1),
        "max_per_day": max(int(snapshot_config.get("max_per_day", 24)), 1),
    }


def _operational_calibration_snapshot_entry(path: Path, out_dir: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Failed to read operational calibration snapshot {path}: {e}", file=sys.stderr)
        return None

    correction = payload.get("correction") or {}
    hourly_rows = payload.get("hourlyDiagnostics") or []
    observed_hours = [
        row.get("hour")
        for row in hourly_rows
        if row.get("actualMw") is not None
        and row.get("actualSource") != _TEPCO_FORECAST_FALLBACK_SOURCE
    ]
    fallback_hours = [
        row.get("hour")
        for row in hourly_rows
        if row.get("actualMw") is not None
        and row.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE
    ]
    deltas = [
        abs(float(row["calibrationDeltaMw"]))
        for row in hourly_rows
        if row.get("calibrationDeltaMw") is not None
    ]
    applied_regime_reason = (
        payload.get("applied_regime_reason")
        or correction.get("appliedRegimeReason")
        or []
    )

    return {
        "date": payload.get("date"),
        "generatedAt": payload.get("generatedAt"),
        "path": path.relative_to(out_dir).as_posix(),
        "model": payload.get("model"),
        "applied": correction.get("applied"),
        "observedHours": correction.get("observedHours", len(observed_hours)),
        "fallbackActualHours": len(fallback_hours),
        "lastObservedHour": correction.get(
            "lastObservedHour",
            max(observed_hours) if observed_hours else None,
        ),
        "baseAdjustmentMw": correction.get("baseAdjustmentMw"),
        "appliedDayBiasMw": correction.get(
            "appliedDayBiasMw",
            payload.get("applied_day_bias"),
        ),
        "appliedRegimeReason": applied_regime_reason,
        "sourceConfidence": payload.get("source_confidence") or correction.get("sourceConfidence"),
        "businessTypeTransitionPriorApplied": correction.get(
            "businessTypeTransitionPriorApplied",
        ),
        "businessTypeTransitionApplied": correction.get("businessTypeTransitionApplied"),
        "positiveResidualMitigationApplied": correction.get(
            "positiveResidualMitigationApplied",
        ),
        "positiveResidualSlopeDampingApplied": correction.get(
            "positiveResidualSlopeDampingApplied",
        ),
        "positiveResidualSlopeDampingFactor": correction.get(
            "positiveResidualSlopeDampingFactor",
        ),
        "positiveResidualSlopeDampingMaxMw": correction.get(
            "positiveResidualSlopeDampingMaxMw",
        ),
        "morningRampContinuityGuardApplied": correction.get(
            "morningRampContinuityGuardApplied",
        ),
        "morningRampContinuityMaxRestoreMw": correction.get(
            "morningRampContinuityMaxRestoreMw",
        ),
        "morningObservedAnchorCapApplied": correction.get(
            "morningObservedAnchorCapApplied",
        ),
        "morningObservedAnchorCapMaxReductionMw": correction.get(
            "morningObservedAnchorCapMaxReductionMw",
        ),
        "afternoonObservedAnchorCapApplied": correction.get(
            "afternoonObservedAnchorCapApplied",
        ),
        "afternoonObservedAnchorCapMaxReductionMw": correction.get(
            "afternoonObservedAnchorCapMaxReductionMw",
        ),
        "eveningDeclineContinuityGuardApplied": correction.get(
            "eveningDeclineContinuityGuardApplied",
        ),
        "eveningDeclineContinuityMaxReductionMw": correction.get(
            "eveningDeclineContinuityMaxReductionMw",
        ),
        "negResidualRecoveryDampingApplied": correction.get(
            "negResidualRecoveryDampingApplied",
        ),
        "residualCarryoverHours": len(correction.get("residualCarryoverByHour") or []),
        "changedForecastHours": len(deltas),
        "maxAbsCalibrationDeltaMw": round(max(deltas), 1) if deltas else 0.0,
    }


def _prune_operational_calibration_snapshots(
    out_dir: Path,
    current_date: date,
    retention_days: int,
    max_per_day: int,
) -> None:
    snapshot_root = out_dir / _OPERATIONAL_CALIBRATION_SNAPSHOT_PATH_NAME
    if not snapshot_root.exists():
        return

    cutoff_date = current_date - timedelta(days=retention_days - 1)
    for date_dir in snapshot_root.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            target_date = date.fromisoformat(date_dir.name)
        except ValueError:
            continue
        if target_date < cutoff_date:
            shutil.rmtree(date_dir)
            continue

        snapshot_files = sorted(
            [
                path for path in date_dir.glob("*.json")
                if path.name != "index.json"
            ],
            key=_snapshot_sort_key,
        )
        for stale_file in snapshot_files[:-max_per_day]:
            stale_file.unlink()


def _write_operational_calibration_snapshot_indexes(
    out_dir: Path,
    generated_at: str,
    config: dict,
) -> None:
    snapshot_root = out_dir / _OPERATIONAL_CALIBRATION_SNAPSHOT_PATH_NAME
    if not snapshot_root.exists():
        return

    snapshot_config = _operational_calibration_snapshot_config(config)
    dates: list[dict] = []
    for date_dir in sorted(path for path in snapshot_root.iterdir() if path.is_dir()):
        snapshot_files = sorted(
            [
                path for path in date_dir.glob("*.json")
                if path.name != "index.json"
            ],
            key=_snapshot_sort_key,
        )
        entries = [
            entry for entry in (
                _operational_calibration_snapshot_entry(path, out_dir)
                for path in snapshot_files
            )
            if entry is not None
        ]
        if not entries:
            continue

        date_index = {
            "schemaVersion": "1.0.0",
            "timezone": "Asia/Tokyo",
            "generatedAt": generated_at,
            "date": date_dir.name,
            "snapshots": entries,
        }
        write_json(date_dir / "index.json", date_index)
        dates.append({
            "date": date_dir.name,
            "path": (date_dir / "index.json").relative_to(out_dir).as_posix(),
            "snapshotCount": len(entries),
            "latest": entries[-1],
        })

    write_json(snapshot_root / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": generated_at,
        "retentionDays": snapshot_config["retention_days"],
        "maxPerDay": snapshot_config["max_per_day"],
        "dates": dates,
    })


def _write_operational_calibration_snapshot(
    out_dir: Path,
    target_date: date,
    calibration_payload: dict,
    config: dict,
) -> Path | None:
    snapshot_config = _operational_calibration_snapshot_config(config)
    if not snapshot_config["enabled"]:
        return None

    generated_at = str(calibration_payload.get("generatedAt") or ts_now())
    try:
        current_date = datetime.fromisoformat(generated_at).date()
    except ValueError:
        current_date = datetime.now(tz=JST).date()

    _prune_operational_calibration_snapshots(
        out_dir,
        current_date,
        snapshot_config["retention_days"],
        snapshot_config["max_per_day"],
    )

    cutoff_date = current_date - timedelta(days=snapshot_config["retention_days"] - 1)
    if target_date < cutoff_date:
        _write_operational_calibration_snapshot_indexes(out_dir, generated_at, config)
        return None

    snapshot_dir = (
        out_dir
        / _OPERATIONAL_CALIBRATION_SNAPSHOT_PATH_NAME
        / target_date.isoformat()
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    base_name = _snapshot_filename(generated_at)
    snapshot_path = snapshot_dir / f"{base_name}.json"
    suffix = 2
    while snapshot_path.exists():
        snapshot_path = snapshot_dir / f"{base_name}-{suffix}.json"
        suffix += 1

    write_json(snapshot_path, calibration_payload)
    _prune_operational_calibration_snapshots(
        out_dir,
        current_date,
        snapshot_config["retention_days"],
        snapshot_config["max_per_day"],
    )
    _write_operational_calibration_snapshot_indexes(out_dir, generated_at, config)
    print(
        "[SNAPSHOT] Operational calibration snapshot "
        f"{target_date.isoformat()} -> {snapshot_path.relative_to(out_dir)}"
    )
    return snapshot_path


def _apply_intraday_residual_correction(
    out_dir: Path,
    target_date: date,
    forecasts: list[HourlyForecast],
    model_name: str,
    config: dict,
    cache: pd.DataFrame | None = None,
    stage_forecasts: dict[str, list[HourlyForecast]] | None = None,
) -> tuple[list[HourlyForecast], str]:
    """Adjust the remaining hours of today's forecast using observed residuals."""
    actual_series = _load_actual_series(out_dir, target_date)
    previous_actual_series = _load_actual_series(out_dir, target_date - timedelta(days=1))
    previous_forecasts, _ = _load_existing_forecast(out_dir, target_date - timedelta(days=1))
    inference_features = None
    if cache is not None and not cache.empty:
        try:
            from python.forecast.feature_builder import build_inference_features
            inference_features = build_inference_features(
                cache,
                target_date,
                config,
                include_context=True,
            )
        except Exception as e:
            print(
                f"[WARN] Operational calibration feature build failed for {target_date}: {e}",
                file=sys.stderr,
            )
    try:
        from python.forecast.intraday_correction import IntradayResidualCorrector
        correction = IntradayResidualCorrector(config).apply(
            forecasts,
            actual_series,
            previous_actual_series=previous_actual_series,
            previous_forecasts=previous_forecasts,
            inference_features=inference_features,
        )
    except Exception as e:
        print(f"[WARN] Intraday residual correction failed for {target_date}: {e}", file=sys.stderr)
        return forecasts, model_name

    calibration_metadata = correction.metadata()
    effective_stage_forecasts = dict(stage_forecasts or {})
    effective_stage_forecasts.setdefault("pre_calibration", forecasts)
    generated_at = ts_now()
    calibration_payload = {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "date": target_date.isoformat(),
        "generatedAt": generated_at,
        "model": model_name,
        "source_confidence": calibration_metadata.get("sourceConfidence"),
        "applied_regime_reason": calibration_metadata.get("appliedRegimeReason"),
        "applied_day_bias": calibration_metadata.get("appliedDayBiasMw"),
        "forecast_build": {
            "stageSummary": _forecast_stage_summary(effective_stage_forecasts),
        },
        "correction": calibration_metadata,
        "hourlyDiagnostics": _operational_calibration_rows(
            actual_series,
            effective_stage_forecasts,
            correction.forecasts,
            calibration_metadata.get("residualCarryoverByHour"),
            inference_features,
        ),
    }
    write_json(
        out_dir
        / "reports"
        / "internal"
        / "operational-calibration"
        / f"{target_date.isoformat()}.json",
        calibration_payload,
    )
    _write_operational_calibration_snapshot(
        out_dir,
        target_date,
        calibration_payload,
        config,
    )

    if not correction.applied:
        return forecasts, model_name

    corrected_model_name = f"{model_name}_intraday_residual"
    after_hour = (
        f"{correction.last_observed_hour:02d}"
        if correction.last_observed_hour is not None
        else "--"
    )
    ramp_guard_note = " ramp_guard=applied" if correction.ramp_guard_applied else ""
    negative_damping_note = (
        " negative_residual_damping=applied"
        if getattr(correction, "negative_adjustment_damped", False)
        else ""
    )
    shape_guard_note = (
        " shape_guard=applied"
        if getattr(correction, "shape_guard_applied", False)
        else ""
    )
    observed_drop_note = (
        " observed_drop_relaxation=active"
        if getattr(correction, "observed_drop_relaxation_active", False)
        else ""
    )
    carryover_note = (
        f" carryover={correction.carryover_adjustment_mw:+.1f}MW"
        if getattr(correction, "carryover_adjustment_mw", 0.0)
        else ""
    )
    day_bias_note = (
        f" day_bias={correction.applied_day_bias_mw:+.1f}MW"
        if getattr(correction, "applied_day_bias_mw", 0.0)
        else ""
    )
    positive_slope_note = (
        " positive_residual_slope_damping=applied"
        if getattr(correction, "positive_residual_slope_damping_applied", False)
        else ""
    )
    morning_ramp_note = (
        " morning_ramp_continuity=applied"
        if getattr(correction, "morning_ramp_continuity_guard_applied", False)
        else ""
    )
    print(
        "[INTRADAY] Residual correction "
        f"{target_date}: base={correction.base_adjustment_mw:+.1f} MW "
        f"after hour={after_hour} "
        f"(observed={correction.observed_hours})"
        f"{ramp_guard_note}"
        f"{negative_damping_note}"
        f"{shape_guard_note}"
        f"{observed_drop_note}"
        f"{carryover_note}"
        f"{day_bias_note}"
        f"{positive_slope_note}"
        f"{morning_ramp_note}"
    )
    return correction.forecasts, corrected_model_name


def _write_forecast_accuracy_report(out_dir: Path) -> None:
    try:
        from python.eval.forecast_accuracy import build_forecast_accuracy_report
        report = build_forecast_accuracy_report(out_dir, generated_at=ts_now())
        write_json(out_dir / "metrics" / "forecast_accuracy.json", report)
        hours = report.get("summary", {}).get("hours", 0)
        print(f"[METRICS] Forecast accuracy report updated ({hours} comparable hours)")
    except Exception as e:
        print(f"[WARN] Forecast accuracy report failed: {e}", file=sys.stderr)


def _write_model_backtest_report(out_dir: Path, cache: pd.DataFrame) -> None:
    try:
        from python.eval.compare_models import build_model_backtest_report
        report = build_model_backtest_report(cache, generated_at=ts_now())
        write_json(out_dir / "metrics" / "model_backtest.json", report)
        test = report.get("testPeriod", {})
        print(
            "[METRICS] Model backtest report updated "
            f"({test.get('start')} -> {test.get('end')})"
        )
    except Exception as e:
        print(f"[WARN] Model backtest report failed: {e}", file=sys.stderr)


def _write_daily_operation_reports(out_dir: Path) -> None:
    try:
        from python.eval.daily_operation_report import build_daily_operation_reports
        index, reports = build_daily_operation_reports(out_dir, generated_at=ts_now())
        report_dir = out_dir / "reports" / "daily"
        write_json(report_dir / "index.json", index)
        for report in reports:
            write_json(report_dir / f"{report['date']}.json", report)
        latest = index.get("latest", {})
        print(
            "[METRICS] Daily operation reports updated "
            f"({len(reports)} reports, latest={latest.get('date')})"
        )
    except Exception as e:
        print(f"[WARN] Daily operation report failed: {e}", file=sys.stderr)


def _write_internal_daily_diagnostics(
    out_dir: Path,
    cache: pd.DataFrame,
    config: dict,
    diagnostics_dir: Path,
) -> None:
    try:
        from python.eval.daily_operation_report import build_internal_daily_diagnostics
        index, diagnostics = build_internal_daily_diagnostics(
            out_dir,
            generated_at=ts_now(),
            cache=cache,
            config=config,
        )
        write_json(diagnostics_dir / "index.json", index)
        for diagnostic in diagnostics:
            write_json(diagnostics_dir / f"{diagnostic['date']}.json", diagnostic)
        latest = index.get("latest") or {}
        print(
            "[INTERNAL] Daily diagnostics updated "
            f"({len(diagnostics)} reports, latest={latest.get('date')}) -> {diagnostics_dir}"
        )
    except Exception as e:
        print(f"[WARN] Internal daily diagnostics failed: {e}", file=sys.stderr)


def _write_ai_daily_reports(out_dir: Path) -> None:
    try:
        from python.eval.ai_daily_report import (
            OPENAI_DEFAULT_LOCALES,
            OPENAI_DEFAULT_MAX_CALLS_PER_RUN,
            _env_bool,
            _env_csv,
            _env_int,
            build_ai_daily_reports_multilingual,
        )
        generated_at = ts_now()
        report_dir = out_dir / "reports" / "ai" / "daily"
        latest = {}
        openai_budget = {
            "remaining": _env_int(
                "OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN",
                OPENAI_DEFAULT_MAX_CALLS_PER_RUN,
            ),
            "used": 0,
        }
        openai_locales = _env_csv("OPENAI_DAILY_REPORT_LOCALES", OPENAI_DEFAULT_LOCALES)
        use_openai = _env_bool("OPENAI_DAILY_REPORT_AUTO_ENABLE", False)
        languages = ("ko", "en", "ja")
        indexes, reports_by_language, openai_budget = build_ai_daily_reports_multilingual(
            out_dir,
            generated_at=generated_at,
            languages=languages,
            existing_report_root=report_dir,
            skip_existing=True,
            use_openai=use_openai,
            openai_budget=openai_budget,
            openai_locales=openai_locales,
        )
        total_reports = 0
        def should_write_report(path: Path, report: dict) -> bool:
            if not path.exists():
                return True
            return (report.get("generator") or {}).get("provider") == "openai"

        for language in ("ko", "en", "ja"):
            language_dir = report_dir / language
            index = indexes[language]
            reports = reports_by_language[language]
            write_json(language_dir / "index.json", index)
            for report in reports:
                report_path = language_dir / f"{report['date']}.json"
                if should_write_report(report_path, report):
                    write_json(report_path, report)
            if language == "ko":
                write_json(report_dir / "index.json", index)
                for report in reports:
                    report_path = report_dir / f"{report['date']}.json"
                    if should_write_report(report_path, report):
                        write_json(report_path, report)
                latest = index.get("latest") or {}
            total_reports += len(reports)
        print(
            "[AI-REPORT] Daily operation reports updated "
            f"({total_reports} localized reports, latest={latest.get('date')}, "
            f"openai_attempts={openai_budget.get('used', 0)})"
        )
    except Exception as e:
        print(f"[WARN] AI daily report failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Status-only update (used by intraday workflow)
# ---------------------------------------------------------------------------

def _summary_from_actual_json(out_dir: Path, d: date) -> dict | None:
    """Derive a LatestSummary-compatible dict from actual/{d}.json (CSV not yet available)."""
    path = out_dir / "actual" / f"{d.isoformat()}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Use actualMw where available, fall back to tepcoForecastMw for missing hours
        series = []
        for pt in data.get("series", []):
            mw = pt.get("actualMw") if pt.get("actualMw") is not None else pt.get("tepcoForecastMw")
            if mw is not None:
                series.append({**pt, "_mw": mw})
        if not series:
            return None
        peak = max(series, key=lambda pt: pt["_mw"])
        usage_pcts = [pt["usagePct"] for pt in series if pt.get("usagePct") is not None]
        supply_mws = [pt["supplyMw"] for pt in series if pt.get("supplyMw") is not None]
        return {
            "date": d.isoformat(),
            "peakActualMw": round(float(peak["_mw"]), 1),
            "peakActualAt": peak["ts"],
            "peakUsagePct": round(max(usage_pcts), 1) if usage_pcts else None,
            "peakSupplyMw": round(max(supply_mws), 1) if supply_mws else None,
        }
    except Exception as e:
        print(f"[WARN] _summary_from_actual_json({d}): {e}", file=sys.stderr)
        return None


def _apply_actual_json_latest_fallback(
    out_dir: Path,
    today: date,
    ok_set: set[date],
    summaries: dict,
) -> tuple[set[date], dict]:
    """Use yesterday's actual JSON in status when the monthly CSV is not ready yet."""
    yesterday = today - timedelta(days=1)
    if yesterday in ok_set:
        return ok_set, summaries

    json_summary = _summary_from_actual_json(out_dir, yesterday)
    if not json_summary:
        return ok_set, summaries

    updated_ok = set(ok_set)
    updated_ok.add(yesterday)
    updated_summaries = {**summaries, yesterday.isoformat(): json_summary}
    print(f"[STATUS] Using actual/{yesterday.isoformat()}.json for latest (CSV pending)")
    return updated_ok, updated_summaries


def _finalize_previous_actual_json_fallbacks(
    out_dir: Path,
    today: date,
    lookback_days: int = 2,
) -> int:
    """Mark previous-day missing actuals with TEPCO forecast fallback.

    The live TEPCO intraday CSV can stop with the last one or two buckets still
    blank, and GitHub scheduled runs may be delayed past midnight. Once the date
    has rolled over, use the already captured TEPCO forecast values as temporary
    lag inputs until the official monthly CSV replaces them with observations.
    """
    actual_dir = out_dir / "actual"
    if not actual_dir.exists():
        return 0

    total_updated = 0
    for offset in range(1, max(1, lookback_days) + 1):
        d = today - timedelta(days=offset)
        path = actual_dir / f"{d.isoformat()}.json"
        if not path.exists():
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to read actual/{d.isoformat()}.json for fallback finalization: {e}", file=sys.stderr)
            continue

        updated = 0
        for pt in data.get("series", []):
            if pt.get("actualMw") is not None:
                continue
            tepco_forecast_mw = pt.get("tepcoForecastMw")
            if tepco_forecast_mw is None:
                continue
            try:
                fallback_mw = float(tepco_forecast_mw)
            except (TypeError, ValueError):
                continue
            if fallback_mw <= 0:
                continue
            pt["actualMw"] = round(fallback_mw, 1)
            pt["actualSource"] = _TEPCO_FORECAST_FALLBACK_SOURCE
            updated += 1

        if updated:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            total_updated += updated
            print(
                f"[STATUS] Finalized {updated} missing actual hours for {d.isoformat()} "
                "with TEPCO forecast fallback"
            )

    return total_updated


def _run_status_only(
    out_dir: Path,
    config: dict,
    preserve_observed_forecast_hours: bool = True,
    internal_diagnostics_out: Path | None = None,
) -> None:
    from python.etl.fetch_weather import enrich_cache_with_weather
    from python.etl.fetch_today import fetch_csv, parse_hourly, write_actual_json

    # Fetch today's intraday actuals from TEPCO before building forecasts/alerts
    try:
        text = fetch_csv()
        date_iso, series = parse_hourly(text)
        if date_iso and series:
            write_actual_json(date_iso, series, out_dir)
    except SystemExit:
        pass  # fetch_csv calls sys.exit on HTTP error — treat as soft failure
    except Exception as e:
        print(f"[WARN] Intraday fetch failed: {e}", file=sys.stderr)

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

    _finalize_previous_actual_json_fallbacks(out_dir, today)

    # If yesterday's CSV hasn't been processed yet, derive latest from actual/{yesterday}.json
    ok_set, summaries = _apply_actual_json_latest_fallback(out_dir, today, ok_set, summaries)

    # Fill any missing temp_c in recent cache rows, then extend with forecast weather.
    # Keep the raw forecast-weather cache for display/persistence; use the bias-corrected
    # copy only as model input so operational UI temperatures remain source temperatures.
    hourly_cache = enrich_cache_with_weather(hourly_cache)
    forecast_weather_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)
    extended_cache = _apply_weather_forecast_bias_correction(forecast_weather_cache, config)

    forecaster = _try_load_lgbm(out_dir)
    adjuster   = _make_adjuster(config)
    guard      = _make_guard(config)
    midday_guard = _make_midday_guard(config)

    # Inject recent missing actuals (yesterday + today) for both forecasts
    extended_with_actuals = _inject_today_actuals(out_dir, today, extended_cache)
    display_with_actuals = _inject_today_actuals(out_dir, today, forecast_weather_cache)
    # Persist the display cache after actual JSON injection so the next run's
    # lag features see the same observed/fallback actuals shown on the UI.
    save_hourly_cache(out_dir, display_with_actuals)
    if forecaster is None:
        forecaster = _try_train_lgbm(extended_with_actuals, out_dir, config)

    # Today's forecast: uses injected cache so lag_24h (yesterday) is populated
    today_build = _build_forecast_pipeline(
        forecaster, extended_with_actuals, today, n_weeks, min_samples,
        config, adjuster, guard, midday_guard
    )
    today_fc, today_model = today_build.forecasts, today_build.model_name
    today_fc, today_model = _apply_intraday_residual_correction(
        out_dir,
        today,
        today_fc,
        today_model,
        config,
        extended_with_actuals,
        stage_forecasts=today_build.stages,
    )
    today_fc, today_model = _freeze_observed_forecast_hours(
        out_dir, today, today_fc, today_model, preserve_observed_forecast_hours
    )

    # Tomorrow's forecast: same injected cache gives lag_24h (today) when available
    tomorrow_build = _build_forecast_pipeline(
        forecaster, extended_with_actuals, tomorrow, n_weeks, min_samples,
        config, adjuster, guard, midday_guard
    )
    tomorrow_fc, tomorrow_model = tomorrow_build.forecasts, tomorrow_build.model_name

    snapshot_generated_at = ts_now()
    snapshot_run_type = (
        "intraday_refresh"
        if not preserve_observed_forecast_hours
        else "intraday"
    )
    write_json(out_dir / "forecast" / f"{today.isoformat()}.json",
               build_forecast_json(today, today_fc, config, today_model))
    write_json(out_dir / "forecast" / f"{tomorrow.isoformat()}.json",
               build_forecast_json(tomorrow, tomorrow_fc, config, tomorrow_model))
    _write_forecast_snapshot(
        out_dir,
        today,
        today_fc,
        config,
        today_model,
        snapshot_generated_at,
        snapshot_run_type,
        preserve_observed_forecast_hours,
        today_build.stages,
    )
    _write_forecast_snapshot(
        out_dir,
        tomorrow,
        tomorrow_fc,
        config,
        tomorrow_model,
        snapshot_generated_at,
        snapshot_run_type,
        preserve_observed_forecast_hours,
        tomorrow_build.stages,
    )

    # Rebuild recent actual alerts with the current config. This keeps yesterday's
    # alert file in sync after threshold/config changes even when the daily CSV
    # has already been processed.
    yesterday = today - timedelta(days=1)
    _build_alerts_for_date(out_dir, yesterday, config, extended_with_actuals)
    alerts_summary = _build_alerts_for_date(out_dir, today, config, extended_with_actuals)

    # The day badge is a reserve-risk signal, not a generic model-error alert.
    today_severity = _reserve_risk_severity_from_alerts_payload(alerts_summary)

    write_json(out_dir / "status.json", build_status_json(
        ok_set, fail_set, summaries, ok_set | fail_set,
        today, today_fc, tomorrow, tomorrow_fc, hourly_cache, config,
        today_severity=today_severity,
        extended_cache=extended_with_actuals,
        display_cache=display_with_actuals,
    ))
    _write_forecast_accuracy_report(out_dir)
    _write_daily_operation_reports(out_dir)
    if internal_diagnostics_out is not None:
        _write_internal_daily_diagnostics(out_dir, extended_with_actuals, config, internal_diagnostics_out)
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
    ap.add_argument("--refresh-today-forecast", action="store_true",
                    help="Deprecated no-op; observed forecast hours are always preserved")
    ap.add_argument("--internal-diagnostics-out", default=None,
                    help="Write internal lag/weather diagnostics JSON. Defaults under web/public/reports/internal/")
    args = ap.parse_args()

    input_dir = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(Path(args.config))
    internal_diagnostics_out = (
        Path(args.internal_diagnostics_out)
        if args.internal_diagnostics_out
        else out_dir / "reports" / "internal" / "daily-diagnostics"
    )

    if args.status_only:
        _run_status_only(
            out_dir,
            config,
            preserve_observed_forecast_hours=True,
            internal_diagnostics_out=internal_diagnostics_out,
        )
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
    new_ok_dates: list[date] = []
    reforecast_dates: list[date] = []

    for d, csv_path in csv_map.items():
        if d in ok_set or d in fail_set:
            continue

        print(f"[ETL] {d}  ←  {csv_path.name}")
        try:
            parsed = parse_tepc_daily_csv(csv_path)
            if run_quality_gate(parsed) == QualityStatus.FAILED:
                raise ValueError("quality gate: FAILED")

            hourly = parsed.hourly

            existing_fc_list, existing_model_name = _load_existing_forecast(out_dir, d)
            should_write_forecast = not existing_fc_list
            if existing_fc_list:
                fc_list = existing_fc_list
                print(
                    f"[ETL] Preserving existing forecast/{d.isoformat()}.json "
                    f"({existing_model_name or 'unknown model'})"
                )
            else:
                # Forecast uses only history BEFORE this date (filtered inside compute_forecast)
                fc_list = compute_forecast(hourly_cache, d, n_weeks, min_samples)
                reforecast_dates.append(d)

            # Anomaly detection on today's actuals vs forecast
            events = detect_anomalies(hourly, fc_list, config.get("anomaly", {}))

            write_json(out_dir / "alerts" / f"{d.isoformat()}.json",
                       build_alerts_json(d, events))
            if should_write_forecast:
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
            new_ok_dates.append(d)
            new_ok += 1

        except Exception as e:
            print(f"[WARN]  {d}: {e}", file=sys.stderr)
            fail_set.add(d)
            new_fail += 1

    # Enrich with weather, then persist state and cache
    from python.etl.fetch_weather import enrich_cache_with_weather
    hourly_cache = enrich_cache_with_weather(hourly_cache)
    save_state(out_dir, {
        "okDates": [d.isoformat() for d in sorted(ok_set)],
        "failedDates": [d.isoformat() for d in sorted(fail_set)],
        "summaries": summaries,
    })
    save_hourly_cache(out_dir, hourly_cache)

    # Train and save LightGBM on the weather-enriched cache
    forecaster = _try_train_lgbm(hourly_cache, out_dir, config)
    adjuster   = _make_adjuster(config)
    guard      = _make_guard(config)
    midday_guard = _make_midday_guard(config)

    # Re-generate backfilled forecasts using LightGBM only when no operational
    # forecast JSON already existed for that date.
    if forecaster is not None and reforecast_dates:
        for d in reforecast_dates:
            try:
                historical_forecaster = _try_train_lgbm_as_of(hourly_cache, d, config)
                historical_cache = hourly_cache[hourly_cache["ts"] < pd.Timestamp(d, tz=JST)].copy()
                fc_list, model_name = _build_forecast_with_fallback(
                    historical_forecaster, historical_cache, d, n_weeks, min_samples,
                    config, adjuster, guard, midday_guard
                )
                write_json(out_dir / "forecast" / f"{d.isoformat()}.json",
                           build_forecast_json(d, fc_list, config, model_name))
                _build_today_alerts(out_dir, d, config)
                print(f"[LGBM] Re-forecast {d} -> {model_name}")
            except Exception as e:
                print(f"[WARN] LightGBM re-forecast {d}: {e}", file=sys.stderr)

    # Extend cache with forecast weather for today/tomorrow inference. Persist the
    # unadjusted forecast-weather cache after actual JSON injection; the
    # bias-corrected copy is model input only.
    forecast_weather_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)
    extended_cache = _apply_weather_forecast_bias_correction(forecast_weather_cache, config)

    # Today / tomorrow forecasts
    today    = datetime.now(tz=JST).date()
    tomorrow = today + timedelta(days=1)
    _finalize_previous_actual_json_fallbacks(out_dir, today)
    status_ok_set, status_summaries = _apply_actual_json_latest_fallback(
        out_dir, today, ok_set, summaries
    )

    extended_with_actuals = _inject_today_actuals(out_dir, today, extended_cache)
    display_with_actuals = _inject_today_actuals(out_dir, today, forecast_weather_cache)
    save_hourly_cache(out_dir, display_with_actuals)
    today_build = _build_forecast_pipeline(
        forecaster, extended_with_actuals, today, n_weeks, min_samples,
        config, adjuster, guard, midday_guard
    )
    today_fc, today_model = today_build.forecasts, today_build.model_name
    today_fc, today_model = _apply_intraday_residual_correction(
        out_dir,
        today,
        today_fc,
        today_model,
        config,
        extended_with_actuals,
        stage_forecasts=today_build.stages,
    )
    today_fc, today_model = _freeze_observed_forecast_hours(
        out_dir, today, today_fc, today_model,
        preserve_observed_hours=True,
    )
    tomorrow_build = _build_forecast_pipeline(
        forecaster, extended_with_actuals, tomorrow, n_weeks, min_samples,
        config, adjuster, guard, midday_guard
    )
    tomorrow_fc, tomorrow_model = tomorrow_build.forecasts, tomorrow_build.model_name

    snapshot_generated_at = ts_now()
    snapshot_run_type = "etl"
    write_json(out_dir / "forecast" / f"{today.isoformat()}.json",
               build_forecast_json(today, today_fc, config, today_model))
    write_json(out_dir / "forecast" / f"{tomorrow.isoformat()}.json",
               build_forecast_json(tomorrow, tomorrow_fc, config, tomorrow_model))
    _write_forecast_snapshot(
        out_dir,
        today,
        today_fc,
        config,
        today_model,
        snapshot_generated_at,
        snapshot_run_type,
        True,
        today_build.stages,
    )
    _write_forecast_snapshot(
        out_dir,
        tomorrow,
        tomorrow_fc,
        config,
        tomorrow_model,
        snapshot_generated_at,
        snapshot_run_type,
        True,
        tomorrow_build.stages,
    )

    # Keep recent alert files aligned with the current anomaly thresholds, even
    # if their daily CSVs were processed by an older config.
    yesterday = today - timedelta(days=1)
    _build_alerts_for_date(out_dir, yesterday, config, extended_with_actuals)
    today_alerts_summary = _build_alerts_for_date(out_dir, today, config, extended_with_actuals)

    # status.json
    write_json(out_dir / "status.json", build_status_json(
        status_ok_set, fail_set, status_summaries, set(csv_map.keys()) | status_ok_set | fail_set,
        today, today_fc, tomorrow, tomorrow_fc, hourly_cache, config,
        today_severity=_reserve_risk_severity_from_alerts_payload(today_alerts_summary),
        extended_cache=extended_with_actuals,
        display_cache=display_with_actuals,
    ))
    _write_forecast_accuracy_report(out_dir)
    _write_model_backtest_report(out_dir, hourly_cache)
    _write_daily_operation_reports(out_dir)
    if internal_diagnostics_out is not None:
        _write_internal_daily_diagnostics(out_dir, hourly_cache, config, internal_diagnostics_out)
    _write_ai_daily_reports(out_dir)

    coverage_to = max(ok_set) if ok_set else None
    print(
        f"[ETL] Done -- new: {new_ok} ok / {new_fail} failed  |  "
        f"total: {len(ok_set)} ok / {len(fail_set)} failed  |  coverage -> {coverage_to}"
    )


if __name__ == "__main__":
    main()
