#!/usr/bin/env python3
"""
Fetch TEPCO juyo-d1-j.csv (today's intraday data) and write
web/public/actual/YYYY-MM-DD.json with today's hourly rows.

URL: https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv
Updated roughly every 30 minutes throughout the day.

Hours whose actual value is not published yet are kept with actualMw=null.
At the final 23:00 hour, the 23:40 JST workflow has no later same-day retry,
so TEPCO's forecast is used as a marked fallback when the actual is still blank.

Usage:
    python python/etl/fetch_today.py
    python python/etl/fetch_today.py --out web/public
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
_JUYO_URL = "https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv"
_HOURLY_HEADER_PREFIX = "DATE,TIME,"

JST = ZoneInfo("Asia/Tokyo")
OBSERVED_ACTUAL_SOURCE = "observed"
TEPCO_FORECAST_FALLBACK_SOURCE = "tepco_forecast_fallback"


def fetch_csv() -> str:
    try:
        with urllib.request.urlopen(_JUYO_URL, timeout=15) as r:
            return r.read().decode("shift-jis")
    except urllib.error.HTTPError as e:
        print(f"[TODAY] HTTP {e.code} fetching {_JUYO_URL}", file=sys.stderr)
        sys.exit(1)


def _to_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _use_final_hour_forecast_fallback(
    ts: datetime,
    actual_mankw: float | None,
    tepco_fc_mankw: float | None,
    now: datetime,
) -> bool:
    if actual_mankw is not None and actual_mankw > 0:
        return False
    if tepco_fc_mankw is None or tepco_fc_mankw <= 0:
        return False

    now_jst = now.astimezone(JST)
    age = now_jst - ts
    return ts.hour == 23 and timedelta(minutes=30) <= age <= timedelta(hours=2)


def parse_hourly(text: str, now: datetime | None = None) -> tuple[str | None, list[dict]]:
    """
    Find the first DATE,TIME hourly block and return (date_iso, series).

    Values in the CSV are in 10 MW units; stored as MW (x10) to match ETL output.
    """
    now = now or datetime.now(tz=JST)
    lines = text.splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith(_HOURLY_HEADER_PREFIX):
            header_idx = i
            break

    if header_idx is None:
        return None, []

    date_iso = None
    series: list[dict] = []

    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or not stripped[:4].isdigit():
            break

        parts = next(csv.reader([stripped]), [])
        if len(parts) < 6:
            continue

        date_str, time_str, actual_str, forecast_str, pct_str, supply_str = parts[:6]

        try:
            y, m, d = (int(x) for x in date_str.split("/"))
            h, mi = (int(x) for x in time_str.split(":"))
        except ValueError:
            continue

        ts = datetime(y, m, d, h, mi, tzinfo=JST)
        if date_iso is None:
            date_iso = ts.date().isoformat()

        actual_mankw = _to_float(actual_str)
        tepco_fc_mankw = _to_float(forecast_str)
        usage_pct = _to_float(pct_str)
        supply_mankw = _to_float(supply_str)

        actual_mw = None
        actual_source = None
        if actual_mankw is not None and actual_mankw > 0:
            actual_mw = round(actual_mankw * 10, 1)
            actual_source = OBSERVED_ACTUAL_SOURCE
        elif _use_final_hour_forecast_fallback(ts, actual_mankw, tepco_fc_mankw, now):
            actual_mw = round(tepco_fc_mankw * 10, 1)
            actual_source = TEPCO_FORECAST_FALLBACK_SOURCE

        series.append({
            "ts": ts.isoformat(timespec="seconds"),
            "actualMw": actual_mw,
            "actualSource": actual_source,
            "tepcoForecastMw": round(tepco_fc_mankw * 10, 1) if tepco_fc_mankw else None,
            "usagePct": usage_pct,
            "supplyMw": round(supply_mankw * 10, 1) if supply_mankw else None,
        })

    return date_iso, series


def write_actual_json(date_iso: str, series: list[dict], out_dir: Path) -> None:
    path = out_dir / "actual" / f"{date_iso}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "date": date_iso,
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "series": series,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    observed = sum(1 for point in series if point.get("actualSource") == OBSERVED_ACTUAL_SOURCE)
    fallback = sum(1 for point in series if point.get("actualSource") == TEPCO_FORECAST_FALLBACK_SOURCE)
    print(f"[TODAY] {date_iso}: {observed} observed hours, {fallback} forecast fallback -> {path.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch TEPCO today's intraday actual data")
    ap.add_argument("--out", default=str(_REPO_ROOT / "web" / "public"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    print(f"[TODAY] Fetching {_JUYO_URL}")

    text = fetch_csv()
    date_iso, series = parse_hourly(text)

    if not date_iso or not series:
        print("[TODAY] No hourly data yet, nothing to write")
        sys.exit(0)

    write_actual_json(date_iso, series, out_dir)


if __name__ == "__main__":
    main()
