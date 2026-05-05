#!/usr/bin/env python3
"""
Fetch TEPCO juyo-d1-j.csv (today's intraday data) and write
web/public/actual/YYYY-MM-DD.json with confirmed hourly actuals.

URL: https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv
Updated roughly every 30 minutes throughout the day.

Hours where 当日実績 = 0 are future (unconfirmed) and are excluded.

Usage:
    python python/etl/fetch_today.py
    python python/etl/fetch_today.py --out web/public
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
_JUYO_URL = "https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv"
_HOURLY_HEADER_PREFIX = "DATE,TIME,"
JST = ZoneInfo("Asia/Tokyo")


def fetch_csv() -> str:
    try:
        with urllib.request.urlopen(_JUYO_URL, timeout=15) as r:
            return r.read().decode("shift-jis")
    except urllib.error.HTTPError as e:
        print(f"[TODAY] HTTP {e.code} fetching {_JUYO_URL}", file=sys.stderr)
        sys.exit(1)


def parse_hourly(text: str) -> tuple[str | None, list[dict]]:
    """
    Find the hourly block (DATE,TIME,当日実績...) and return
    (date_iso, series) for hours where actual > 0.

    Values in the CSV are in 万kW; stored as MW (x10) to match ETL output.
    """
    lines = text.splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith(_HOURLY_HEADER_PREFIX) and "実績" in line:
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

        parts = stripped.split(",")
        if len(parts) < 6:
            continue

        date_str, time_str, actual_str, forecast_str, pct_str, supply_str = parts[:6]

        # "2026/5/5", "0:00" -> datetime
        try:
            y, m, d = (int(x) for x in date_str.split("/"))
            h, mi = (int(x) for x in time_str.split(":"))
        except ValueError:
            continue

        ts = datetime(y, m, d, h, mi, tzinfo=JST)
        if date_iso is None:
            date_iso = ts.date().isoformat()

        try:
            actual_mankw = float(actual_str)
        except ValueError:
            actual_mankw = 0.0

        try:
            tepco_fc_mankw = float(forecast_str)
        except ValueError:
            tepco_fc_mankw = None

        series.append({
            "ts": ts.isoformat(timespec="seconds"),
            "actualMw":        round(actual_mankw * 10, 1) if actual_mankw > 0 else None,
            "tepcoForecastMw": round(tepco_fc_mankw * 10, 1) if tepco_fc_mankw else None,
            "usagePct":        float(pct_str) if pct_str.strip() else None,
            "supplyMw":        round(float(supply_str) * 10, 1) if supply_str.strip() else None,
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
    print(f"[TODAY] {date_iso}: {len(series)} confirmed hours -> {path.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch TEPCO today's intraday actual data")
    ap.add_argument("--out", default=str(_REPO_ROOT / "web" / "public"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    print(f"[TODAY] Fetching {_JUYO_URL}")

    text = fetch_csv()
    date_iso, series = parse_hourly(text)

    if not date_iso or not series:
        print("[TODAY] No confirmed hourly data yet, nothing to write")
        sys.exit(0)

    write_actual_json(date_iso, series, out_dir)


if __name__ == "__main__":
    main()
