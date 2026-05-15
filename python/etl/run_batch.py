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
_TEPCO_FORECAST_FALLBACK_SOURCE = "tepco_forecast_fallback"

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

_CACHE_COLS = [
    "ts", "actual_mw", "forecast_mw", "usage_pct", "supply_mw",
    "temp_c", "apparent_temp_c",
]
_CACHE_PATH_NAME = ".hourly_cache.parquet"


def load_hourly_cache(out_dir: Path) -> pd.DataFrame:
    p = out_dir / _CACHE_PATH_NAME
    if p.exists():
        df = pd.read_parquet(p)
        if "ts" in df.columns and df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("Asia/Tokyo")
        if "temp_c" not in df.columns:
            df["temp_c"] = float("nan")
        if "apparent_temp_c" not in df.columns:
            df["apparent_temp_c"] = float("nan")
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


def _normalize_forecast_bands(fc_list: list[HourlyForecast]) -> list[HourlyForecast]:
    result: list[HourlyForecast] = []
    for forecast in fc_list:
        point_forecast_mw = round(float(forecast.forecast_mw), 1)
        p95_lower = round(
            min(float(forecast.p95_lower_mw), float(forecast.p95_upper_mw), point_forecast_mw),
            1,
        )
        p95_upper = round(
            max(float(forecast.p95_lower_mw), float(forecast.p95_upper_mw), point_forecast_mw),
            1,
        )
        p99_lower = round(
            min(float(forecast.p99_lower_mw), float(forecast.p99_upper_mw), p95_lower, point_forecast_mw),
            1,
        )
        p99_upper = round(
            max(float(forecast.p99_lower_mw), float(forecast.p99_upper_mw), p95_upper, point_forecast_mw),
            1,
        )
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
    fc_list = _normalize_forecast_bands(fc_list)
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
            new_rows.append({c: row.get(c, float("nan")) for c in _CACHE_COLS})
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
    """Build and write today's alerts JSON.  Returns the alerts summary dict, or None on failure."""
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
        print(f"[STATUS] Today alerts: {len(events)} events -> {alerts_path.name}")
        return payload.get("summary")
    except Exception as e:
        print(f"[WARN] Failed to build today alerts: {e}", file=sys.stderr)
    return None



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
    peak_fc_mw = max(f.forecast_mw for f in fc_list)
    recent_supply = None
    if "supply_mw" in cache.columns:
        supply_df = cache[["ts", "supply_mw"]].dropna(subset=["supply_mw"])
        # p75 of recent weekday supply: robust against GW-low outliers and peak-day highs
        weekday_supply = supply_df[supply_df["ts"].dt.dayofweek < 5].tail(24 * 14)
        if not weekday_supply.empty:
            recent_supply = weekday_supply["supply_mw"].quantile(0.75)
    if recent_supply and recent_supply > 0:
        est_pct = peak_fc_mw / recent_supply * 100
        rr = config.get("anomaly", {}).get("reserve_risk", {})
        if est_pct >= rr.get("critical_pct", 95.0):
            return "critical" if allow_critical else "warning"
        if est_pct >= rr.get("warning_pct", 90.0):
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
            else _forecast_severity(fc_list, cache, config, allow_critical=d <= today)
        )
        result = {
            "date": d.isoformat(),
            "peakForecastMw": peak["forecastMw"] if peak else None,
            "peakForecastAt": peak["at"] if peak else None,
            "severity": sev,
        }
        if peak and extended_cache is not None and "temp_c" in extended_cache.columns:
            peak_ts = pd.Timestamp(peak["at"]).tz_convert("Asia/Tokyo")
            temp_row = extended_cache.loc[extended_cache["ts"] == peak_ts, "temp_c"]
            if not temp_row.empty and pd.notna(temp_row.iloc[0]):
                result["peakTempC"] = round(float(temp_row.iloc[0]), 1)
        return result

    def _alerts_severity(summary: dict | None) -> str:
        if not summary:
            return "info"
        if summary.get("critical", 0) > 0:
            return "critical"
        if summary.get("warning", 0) > 0:
            return "warning"
        return "info"

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
            result[col] = float("nan")

    weather_cols = ["ts", "temp_c"]
    if "apparent_temp_c" in weather.columns:
        weather_cols.append("apparent_temp_c")
    weather_temp = weather[weather_cols].copy()
    forecast_temp_col = "_forecast_temp_c"
    forecast_apparent_temp_col = "_forecast_apparent_temp_c"
    result = result.merge(
        weather_temp.rename(columns={
            "temp_c": forecast_temp_col,
            "apparent_temp_c": forecast_apparent_temp_col,
        }),
        on="ts",
        how="left",
    )
    can_refresh_temp = result["actual_mw"].isna() & result[forecast_temp_col].notna()
    result.loc[can_refresh_temp, "temp_c"] = result.loc[can_refresh_temp, forecast_temp_col]
    if forecast_apparent_temp_col in result.columns:
        can_refresh_apparent_temp = (
            result["actual_mw"].isna()
            & result[forecast_apparent_temp_col].notna()
        )
        result.loc[can_refresh_apparent_temp, "apparent_temp_c"] = (
            result.loc[can_refresh_apparent_temp, forecast_apparent_temp_col]
        )
    result = result.drop(columns=[
        col for col in [forecast_temp_col, forecast_apparent_temp_col]
        if col in result.columns
    ])

    existing_ts = set(result["ts"])
    new_rows = weather_temp[~weather_temp["ts"].isin(existing_ts)].copy()
    for col in _CACHE_COLS:
        if col not in new_rows.columns:
            new_rows[col] = float("nan")

    result = pd.concat([result[_CACHE_COLS], new_rows[_CACHE_COLS]], ignore_index=True)
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


def _build_forecast_with_fallback(
    forecaster,
    cache: pd.DataFrame,
    target_date: date,
    n_weeks: int,
    min_samples: int,
    config: dict | None = None,
    adjuster=None,
    guard=None,
) -> tuple[list, str]:
    """Return (forecasts, model_name).

    Pipeline: LightGBM → AnalogousDayAdjuster → PostHolidayTimeBandGuard → output.
    Falls back to baseline when LightGBM is unavailable or fails.
    """
    if forecaster is not None:
        try:
            from python.forecast.feature_builder import build_inference_features
            inference_features = build_inference_features(cache, target_date, config)
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
            return guarded_forecasts, "lgbm_quantile_q50"
        except Exception as e:
            print(f"[WARN] LightGBM predict failed for {target_date}: {e}", file=sys.stderr)
    return compute_forecast(cache, target_date, n_weeks, min_samples), "baseline_dow_hour_mean"


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


def _apply_intraday_residual_correction(
    out_dir: Path,
    target_date: date,
    forecasts: list[HourlyForecast],
    model_name: str,
    config: dict,
) -> tuple[list[HourlyForecast], str]:
    """Adjust the remaining hours of today's forecast using observed residuals."""
    actual_series = _load_actual_series(out_dir, target_date)
    if not actual_series:
        return forecasts, model_name
    try:
        from python.forecast.intraday_correction import IntradayResidualCorrector
        correction = IntradayResidualCorrector(config).apply(forecasts, actual_series)
    except Exception as e:
        print(f"[WARN] Intraday residual correction failed for {target_date}: {e}", file=sys.stderr)
        return forecasts, model_name

    if not correction.applied:
        return forecasts, model_name

    corrected_model_name = f"{model_name}_intraday_residual"
    print(
        "[INTRADAY] Residual correction "
        f"{target_date}: base={correction.base_adjustment_mw:+.1f} MW "
        f"after hour={correction.last_observed_hour:02d} "
        f"(observed={correction.observed_hours})"
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


def _run_status_only(out_dir: Path, config: dict) -> None:
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

    # If yesterday's CSV hasn't been processed yet, derive latest from actual/{yesterday}.json
    ok_set, summaries = _apply_actual_json_latest_fallback(out_dir, today, ok_set, summaries)

    # Fill any missing temp_c in recent cache rows, then extend with forecast weather
    hourly_cache   = enrich_cache_with_weather(hourly_cache)
    extended_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)
    save_hourly_cache(out_dir, extended_cache)

    forecaster = _try_load_lgbm(out_dir)
    adjuster   = _make_adjuster(config)
    guard      = _make_guard(config)

    # Inject recent missing actuals (yesterday + today) for both forecasts
    extended_with_actuals = _inject_today_actuals(out_dir, today, extended_cache)
    if forecaster is None:
        forecaster = _try_train_lgbm(extended_with_actuals, out_dir, config)

    # Today's forecast: uses injected cache so lag_24h (yesterday) is populated
    today_fc, today_model = _build_forecast_with_fallback(
        forecaster, extended_with_actuals, today, n_weeks, min_samples, config, adjuster, guard
    )
    today_fc, today_model = _apply_intraday_residual_correction(
        out_dir, today, today_fc, today_model, config
    )

    # Tomorrow's forecast: same injected cache gives lag_24h (today) when available
    tomorrow_fc, tomorrow_model = _build_forecast_with_fallback(
        forecaster, extended_with_actuals, tomorrow, n_weeks, min_samples, config, adjuster, guard
    )

    write_json(out_dir / "forecast" / f"{today.isoformat()}.json",
               build_forecast_json(today, today_fc, config, today_model))
    write_json(out_dir / "forecast" / f"{tomorrow.isoformat()}.json",
               build_forecast_json(tomorrow, tomorrow_fc, config, tomorrow_model))

    day_context = None
    try:
        from python.forecast.feature_builder import build_inference_features
        day_context = _make_day_context(build_inference_features(extended_cache, today, config), config)
    except Exception:
        pass
    alerts_summary = _build_today_alerts(out_dir, today, config, day_context=day_context)

    # Derive today's severity from actual alerts (not from forecast-based reserve risk estimate)
    today_severity = None
    if alerts_summary is not None:
        if alerts_summary.get("critical", 0) > 0:
            today_severity = "critical"
        elif alerts_summary.get("warning", 0) > 0:
            today_severity = "warning"
        else:
            today_severity = "info"

    write_json(out_dir / "status.json", build_status_json(
        ok_set, fail_set, summaries, ok_set | fail_set,
        today, today_fc, tomorrow, tomorrow_fc, hourly_cache, config,
        today_severity=today_severity,
        extended_cache=extended_with_actuals,
    ))
    _write_forecast_accuracy_report(out_dir)
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

    # Re-generate backfilled forecasts using LightGBM only when no operational
    # forecast JSON already existed for that date.
    if forecaster is not None and reforecast_dates:
        for d in reforecast_dates:
            try:
                historical_forecaster = _try_train_lgbm_as_of(hourly_cache, d, config)
                historical_cache = hourly_cache[hourly_cache["ts"] < pd.Timestamp(d, tz=JST)].copy()
                fc_list, model_name = _build_forecast_with_fallback(
                    historical_forecaster, historical_cache, d, n_weeks, min_samples,
                    config, adjuster, guard
                )
                write_json(out_dir / "forecast" / f"{d.isoformat()}.json",
                           build_forecast_json(d, fc_list, config, model_name))
                _build_today_alerts(out_dir, d, config)
                print(f"[LGBM] Re-forecast {d} -> {model_name}")
            except Exception as e:
                print(f"[WARN] LightGBM re-forecast {d}: {e}", file=sys.stderr)

    # Extend cache with forecast weather for today/tomorrow inference
    extended_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)
    save_hourly_cache(out_dir, extended_cache)

    # Today / tomorrow forecasts
    today    = datetime.now(tz=JST).date()
    tomorrow = today + timedelta(days=1)
    status_ok_set, status_summaries = _apply_actual_json_latest_fallback(
        out_dir, today, ok_set, summaries
    )

    extended_with_actuals = _inject_today_actuals(out_dir, today, extended_cache)
    today_fc, today_model = _build_forecast_with_fallback(
        forecaster, extended_with_actuals, today, n_weeks, min_samples, config, adjuster, guard
    )
    today_fc, today_model = _apply_intraday_residual_correction(
        out_dir, today, today_fc, today_model, config
    )
    tomorrow_fc, tomorrow_model = _build_forecast_with_fallback(
        forecaster, extended_with_actuals, tomorrow, n_weeks, min_samples, config, adjuster, guard
    )

    write_json(out_dir / "forecast" / f"{today.isoformat()}.json",
               build_forecast_json(today, today_fc, config, today_model))
    write_json(out_dir / "forecast" / f"{tomorrow.isoformat()}.json",
               build_forecast_json(tomorrow, tomorrow_fc, config, tomorrow_model))

    # status.json
    write_json(out_dir / "status.json", build_status_json(
        status_ok_set, fail_set, status_summaries, set(csv_map.keys()) | status_ok_set | fail_set,
        today, today_fc, tomorrow, tomorrow_fc, hourly_cache, config,
        extended_cache=extended_with_actuals,
    ))
    _write_forecast_accuracy_report(out_dir)
    _write_model_backtest_report(out_dir, hourly_cache)

    coverage_to = max(ok_set) if ok_set else None
    print(
        f"[ETL] Done -- new: {new_ok} ok / {new_fail} failed  |  "
        f"total: {len(ok_set)} ok / {len(fail_set)} failed  |  coverage -> {coverage_to}"
    )


if __name__ == "__main__":
    main()
