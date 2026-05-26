#!/usr/bin/env python3
"""
Download TEPCO monthly power-usage ZIP and extract daily CSVs to data/raw/.

URL pattern:
  https://www.tepco.co.jp/forecast/html/images/YYYYMM_power_usage.zip

Each ZIP contains daily CSVs named YYYYMMDD_power_usage.csv.
Already-existing files are skipped (idempotent).

Usage:
  python python/etl/fetch_tepco.py              # current month (+ prev if day <= 3)
  python python/etl/fetch_tepco.py --month 202604
  python python/etl/fetch_tepco.py --month 202604 --month 202605
"""
from __future__ import annotations

import argparse
import io
import sys
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

_BASE_URL = "https://www.tepco.co.jp/forecast/html/images"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RAW_DIR = _REPO_ROOT / "data" / "raw"
_HTTP_TIMEOUT_SECONDS = 30
_FETCH_ATTEMPTS = 3
_RETRYABLE_HTTP_CODES = {403, 408, 425, 429, 500, 502, 503, 504}
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.tepco.co.jp/forecast/",
}


def _zip_url(yyyymm: str) -> str:
    return f"{_BASE_URL}/{yyyymm}_power_usage.zip"


def _open_with_retry(url: str):
    last_error: Exception | None = None
    for attempt in range(1, _FETCH_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
            return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code not in _RETRYABLE_HTTP_CODES or attempt >= _FETCH_ATTEMPTS:
                raise
            wait_seconds = 2 ** (attempt - 1)
            print(
                f"[WARN] TEPCO fetch HTTP {e.code} "
                f"(attempt {attempt}/{_FETCH_ATTEMPTS}); retrying in {wait_seconds}s",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
            if attempt >= _FETCH_ATTEMPTS:
                raise
            wait_seconds = 2 ** (attempt - 1)
            print(
                f"[WARN] TEPCO fetch failed "
                f"(attempt {attempt}/{_FETCH_ATTEMPTS}): {e}; retrying in {wait_seconds}s",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    if last_error is not None:
        raise last_error
    raise RuntimeError("TEPCO fetch failed without an exception")


def _download_with_curl(url: str) -> bytes:
    """Fallback downloader for environments where urllib is blocked by the edge."""
    cmd = [
        "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--max-time",
        str(_HTTP_TIMEOUT_SECONDS),
    ]
    for key, value in _REQUEST_HEADERS.items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)

    completed = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _download_zip_bytes(url: str) -> bytes:
    try:
        with _open_with_retry(url) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise
        if e.code in _RETRYABLE_HTTP_CODES:
            print(
                f"[WARN] TEPCO urllib fetch ended with HTTP {e.code}; "
                "trying curl fallback",
                file=sys.stderr,
            )
            try:
                return _download_with_curl(url)
            except (FileNotFoundError, subprocess.CalledProcessError) as curl_error:
                raise RuntimeError(
                    f"TEPCO ZIP fetch failed after urllib and curl fallback "
                    f"(last HTTP {e.code})"
                ) from curl_error
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(
            f"[WARN] TEPCO urllib fetch failed ({e}); trying curl fallback",
            file=sys.stderr,
        )
        try:
            return _download_with_curl(url)
        except (FileNotFoundError, subprocess.CalledProcessError) as curl_error:
            raise RuntimeError(
                "TEPCO ZIP fetch failed after urllib and curl fallback"
            ) from curl_error


def _recent_csv_names(today: date, days: int) -> set[str]:
    if days <= 0:
        return set()
    return {
        f"{(today - timedelta(days=offset)).strftime('%Y%m%d')}_power_usage.csv"
        for offset in range(days)
    }


def fetch_month(
    yyyymm: str,
    raw_dir: Path = _RAW_DIR,
    overwrite_recent_days: int = 0,
    today: date | None = None,
) -> tuple[int, int]:
    """Download and extract one monthly ZIP.

    Returns (new_count, overwritten_count). Existing files are normally kept, but
    recent dates can be overwritten to absorb TEPCO's delayed corrections.
    """
    year = int(yyyymm[:4])
    url = _zip_url(yyyymm)
    dest_dir = raw_dir / str(year) / f"{yyyymm}_power_usage"
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"[FETCH] {url}")
    try:
        data = _download_zip_bytes(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[FETCH] {yyyymm}: not yet published (404), skipping")
            return 0, 0
        raise

    if today is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(tz=ZoneInfo("Asia/Tokyo")).date()
    overwrite_names = _recent_csv_names(today, overwrite_recent_days)

    new_count = 0
    overwritten_count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for entry in zf.namelist():
            fname = Path(entry).name
            if not fname.endswith(".csv"):
                continue
            target = dest_dir / fname
            should_overwrite = target.exists() and fname in overwrite_names
            if target.exists() and not should_overwrite:
                continue
            target.write_bytes(zf.read(entry))
            if should_overwrite:
                print(f"[FETCH]   ~ {fname}")
                overwritten_count += 1
            else:
                print(f"[FETCH]   + {fname}")
                new_count += 1

    print(
        f"[FETCH] {yyyymm}: {new_count} new file(s), "
        f"{overwritten_count} overwritten recent file(s)"
    )
    return new_count, overwritten_count


def months_to_fetch(today: date | None = None) -> list[str]:
    """Return list of YYYYMM strings to fetch for a typical daily run."""
    if today is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(tz=ZoneInfo("Asia/Tokyo")).date()

    current = f"{today.year}{today.month:02d}"
    targets = [current]

    # First few days of a month: previous month may still be getting corrections
    if today.day <= 3:
        if today.month == 1:
            prev = f"{today.year - 1}12"
        else:
            prev = f"{today.year}{today.month - 1:02d}"
        targets.insert(0, prev)

    return targets


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch TEPCO power-usage ZIPs")
    ap.add_argument(
        "--month", action="append", metavar="YYYYMM",
        help="Month(s) to fetch (e.g. 202605). Defaults to current month.",
    )
    ap.add_argument("--out", default=str(_RAW_DIR), help="Root data/raw directory")
    ap.add_argument(
        "--overwrite-recent-days",
        type=int,
        default=0,
        help=(
            "Overwrite already-downloaded CSVs for the last N JST dates. "
            "Use this for local operational ETL to absorb delayed TEPCO corrections."
        ),
    )
    args = ap.parse_args()

    raw_dir = Path(args.out)
    targets = args.month if args.month else months_to_fetch()

    total_new = 0
    total_overwritten = 0
    for yyyymm in targets:
        if len(yyyymm) != 6 or not yyyymm.isdigit():
            print(f"[ERROR] Invalid month format: {yyyymm} (expected YYYYMM)", file=sys.stderr)
            sys.exit(1)
        new_count, overwritten_count = fetch_month(
            yyyymm,
            raw_dir,
            overwrite_recent_days=max(0, args.overwrite_recent_days),
        )
        total_new += new_count
        total_overwritten += overwritten_count

    print(
        f"[FETCH] Done -- {total_new} new CSV(s), "
        f"{total_overwritten} overwritten recent CSV(s) across {len(targets)} month(s)"
    )


if __name__ == "__main__":
    main()
