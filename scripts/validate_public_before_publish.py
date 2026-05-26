#!/usr/bin/env python3
"""Validate generated web/public before publishing it to the data branch."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO_ROOT / "web" / "public"
JST = ZoneInfo("Asia/Tokyo")
FALLBACK_SOURCE = "tepco_forecast_fallback"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON {path}: {exc}") from exc


def _observed_hours(actual_payload: dict, date_iso: str) -> set[int]:
    hours: set[int] = set()
    for point in actual_payload.get("series") or []:
        if point.get("actualMw") is None:
            continue
        if point.get("actualSource") == FALLBACK_SOURCE:
            continue
        ts = str(point.get("ts") or "")
        if not ts.startswith(date_iso):
            continue
        try:
            hours.add(int(ts[11:13]))
        except (IndexError, ValueError):
            continue
    return hours


def _require_forecast(public_dir: Path, date_iso: str, label: str) -> None:
    payload = _load_json(public_dir / "forecast" / f"{date_iso}.json")
    if payload.get("availability") != "ok":
        raise RuntimeError(f"{label} forecast availability is not ok: {date_iso}")
    series = payload.get("series") or []
    if len(series) != 24:
        raise RuntimeError(f"{label} forecast must have 24 rows: {date_iso} has {len(series)}")
    missing = [idx for idx, point in enumerate(series) if point.get("forecastMw") is None]
    if missing:
        raise RuntimeError(f"{label} forecast has missing forecastMw hours: {missing}")


def validate(public_dir: Path = PUBLIC_DIR, min_yesterday_hours: int = 24) -> dict:
    today = datetime.now(tz=JST).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    today_iso = today.isoformat()
    yesterday_iso = yesterday.isoformat()
    tomorrow_iso = tomorrow.isoformat()

    status = _load_json(public_dir / "status.json")
    if status.get("availability") != "ok":
        raise RuntimeError(f"status availability is not ok: {status.get('availability')}")
    if status.get("failedDays"):
        raise RuntimeError(f"status has failedDays: {status.get('failedDays')}")
    if status.get("missingDays"):
        raise RuntimeError(f"status has missingDays: {status.get('missingDays')}")
    coverage_to = str(status.get("coverageTo") or "")
    if coverage_to < yesterday_iso:
        raise RuntimeError(f"coverageTo {coverage_to!r} is older than yesterday {yesterday_iso}")

    actual = _load_json(public_dir / "actual" / f"{yesterday_iso}.json")
    if actual.get("availability") != "ok":
        raise RuntimeError(f"yesterday actual availability is not ok: {yesterday_iso}")
    observed = _observed_hours(actual, yesterday_iso)
    if len(observed) < min_yesterday_hours:
        raise RuntimeError(
            f"yesterday actual has {len(observed)} observed hours; "
            f"required {min_yesterday_hours}"
        )

    _require_forecast(public_dir, today_iso, "today")
    _require_forecast(public_dir, tomorrow_iso, "tomorrow")

    report_path = public_dir / "reports" / "ai" / "daily" / f"{yesterday_iso}.json"
    ai_provider = None
    if report_path.exists():
        report = _load_json(report_path)
        ai_provider = (report.get("generator") or {}).get("provider")

    return {
        "status": "ok",
        "coverageTo": coverage_to,
        "yesterday": yesterday_iso,
        "yesterdayObservedHours": len(observed),
        "todayForecast": today_iso,
        "tomorrowForecast": tomorrow_iso,
        "aiReportProvider": ai_provider,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", default=str(PUBLIC_DIR))
    parser.add_argument("--min-yesterday-hours", type=int, default=24)
    args = parser.parse_args()

    try:
        result = validate(Path(args.public_dir), args.min_yesterday_hours)
    except Exception as exc:
        print(f"[VALIDATE] failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("[VALIDATE] " + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
