"""
TEPCO multi-section CSV parser (Tokyo Electric Power Grid).

This parser is tailored to TEPCO's daily CSV format where multiple tables are
concatenated and separated by blank lines.

Improvements vs. the initial version:
- Robust CSV splitting via Python's built-in csv module (handles quoted commas).
- Optional timezone localization (default: Asia/Tokyo) for all timestamps.
- Stronger data-quality checks: duplicates, monotonicity, expected frequency, gap counts.
- Optional normalization helper to map volatile Japanese header keys to stable identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Iterable
import datetime as dt
import io
import csv

import pandas as pd


# -----------------------------
# Helpers
# -----------------------------

def _read_text_with_fallback(path: Path, encoding: Optional[str]) -> tuple[str, str]:
    """
    Read text with a safe encoding strategy.
    If encoding is provided, use it. Otherwise try utf-8, then cp932, then shift_jis.

    Returns (text, encoding_used).
    """
    raw = path.read_bytes()

    if encoding:
        return raw.decode(encoding), encoding

    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue

    # Last resort: replace invalid characters
    return raw.decode("cp932", errors="replace"), "cp932(errors=replace)"


def _split_csv_line(line: str) -> List[str]:
    """
    Split one CSV line robustly using Python's csv module.
    This handles quoted fields and embedded commas safely.
    """
    reader = csv.reader([line], delimiter=",", quotechar='"', skipinitialspace=False)
    row = next(reader, [])
    return [c.strip() for c in row]


def _parse_update_line(line: str) -> Optional[dt.datetime]:
    """
    Example: '2025/12/1 23:55 UPDATE'
    Returns timezone-naive datetime (timezone localization can be applied downstream).
    """
    try:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].upper() == "UPDATE":
            date_s, time_s = parts[0], parts[1]
            y, m, d = [int(x) for x in date_s.split("/")]
            hh, mm = [int(x) for x in time_s.split(":")]
            return dt.datetime(y, m, d, hh, mm)
    except Exception:
        return None
    return None


def _parse_date_time(date_s: str, time_s: str) -> Optional[pd.Timestamp]:
    """
    Build a pandas Timestamp from DATE and TIME columns.
    DATE: '2025/12/1' or '2025/12/01'
    TIME: '0:00', '23:55'
    """
    try:
        y, m, d = [int(x) for x in str(date_s).split("/")]
        hh, mm = [int(x) for x in str(time_s).split(":")]
        return pd.Timestamp(year=y, month=m, day=d, hour=hh, minute=mm)
    except Exception:
        return None


def _localize_ts(ts: pd.Series, tz: Optional[str]) -> pd.Series:
    """
    Localize a timestamp series if tz is provided.
    Keeps NaT as-is.
    """
    if tz is None:
        return ts
    try:
        if getattr(ts.dt, "tz", None) is None:
            return ts.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
        return ts.dt.tz_convert(tz)
    except Exception:
        return ts


def _skip_blanks(lines: List[str], pos: int) -> int:
    while pos < len(lines) and lines[pos].strip() == "":
        pos += 1
    return pos


def _read_one_row_block(lines: List[str], start: int) -> Tuple[Optional[Tuple[List[str], List[str]]], int]:
    """
    Read a one-row CSV block: header + one row.
    Returns ((header,row), next_index) or (None, next_index)
    """
    if start >= len(lines):
        return None, start
    if lines[start].strip() == "":
        return None, start + 1

    header = _split_csv_line(lines[start])
    if start + 1 >= len(lines):
        return None, start + 1
    row = _split_csv_line(lines[start + 1])
    return (header, row), start + 2


def _quality_time_series(ts: pd.Series, expected_count: int, expected_freq: str) -> Dict[str, Any]:
    """
    Lightweight time-series QA: duplicates, monotonicity, expected frequency.
    """
    q: Dict[str, Any] = {}
    q["rows"] = int(len(ts))
    q["expected_count_ok"] = bool(len(ts) == expected_count)
    q["missing_ts"] = int(ts.isna().sum())

    ts_nn = ts.dropna()
    q["duplicates"] = int(ts_nn.duplicated().sum())
    q["unique_ok"] = (q["duplicates"] == 0)
    q["monotonic_increasing"] = bool(ts_nn.is_monotonic_increasing)

    gap_count = None
    try:
        if len(ts_nn) > 1:
            ts_sorted = ts_nn.sort_values()
            diffs = ts_sorted.diff().dropna()
            expected = pd.Timedelta(expected_freq)
            gap_count = int((diffs != expected).sum())
    except Exception:
        gap_count = None
    q["freq_mismatch_count"] = gap_count

    return q


def normalize_summary_blocks(summary_blocks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert volatile Japanese headers into stable keys when possible.
    """
    out: Dict[str, Any] = {}

    def find_block(prefixes: Iterable[str]) -> Optional[Dict[str, Any]]:
        for k, v in summary_blocks.items():
            for pfx in prefixes:
                if k.startswith(pfx):
                    return v
        return None

    blk = find_block(["ピーク時供給力"])
    if blk:
        for col in ("当日", "当日ピーク時供給力(万kW)", "ピーク時供給力(万kW)"):
            if col in blk:
                out["peak_supply_today_mankw"] = _to_float(blk.get(col))
                break

    blk = find_block(["予測最大電力"])
    if blk:
        for col in ("当日", "当日予測最大電力(万kW)", "予測最大電力(万kW)"):
            if col in blk:
                out["forecast_max_today_mankw"] = _to_float(blk.get(col))
                break

    blk = summary_blocks.get("最大使用率(%)")
    if blk:
        for col in ("当日", "最大使用率(%)"):
            if col in blk:
                out["max_usage_pct"] = _to_float(blk.get(col))
                break

    blk = find_block(["ピーク時供給力(万kW)【翌日】", "ピーク時供給力(万kW)（翌日", "翌日ピーク時供給力"])
    if blk:
        for col in ("翌日", "翌日ピーク時供給力(万kW)"):
            if col in blk:
                out["peak_supply_tomorrow_mankw"] = _to_float(blk.get(col))
                break

    blk = find_block(["予測最大電力(万kW)【翌日】", "予測最大電力(万kW)（翌日", "翌日予測最大電力"])
    if blk:
        for col in ("翌日", "翌日予測最大電力(万kW)"):
            if col in blk:
                out["forecast_max_tomorrow_mankw"] = _to_float(blk.get(col))
                break

    return out


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# -----------------------------
# Public API
# -----------------------------

@dataclass(frozen=True)
class TepcoDailyParsed:
    source_path: str
    encoding_used: str
    updated_at: Optional[pd.Timestamp]
    summary_blocks: Dict[str, Dict[str, Any]]
    hourly: pd.DataFrame
    five_min: pd.DataFrame
    quality: Dict[str, Any]


def parse_tepc_daily_csv(
    csv_path: str | Path,
    *,
    encoding: Optional[str] = None,
    convert_to_mw: bool = True,
    tz: Optional[str] = "Asia/Tokyo",
) -> TepcoDailyParsed:
    """
    Parse one TEPCO daily multi-section CSV.

    Parameters
    ----------
    csv_path:
        Path to the CSV.
    encoding:
        If None, auto-detect via utf-8/utf-8-sig/cp932/shift_jis fallback.
    convert_to_mw:
        If True, add MW-converted numeric columns (万kW × 10).
    tz:
        Timezone for all timestamps (default: Asia/Tokyo). None = naive.
    """
    path = Path(csv_path)
    text, enc_used = _read_text_with_fallback(path, encoding)

    lines = [ln.rstrip("\n\r") for ln in text.splitlines()]
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()

    i = 0

    # 1) Update line
    updated_at: Optional[pd.Timestamp] = None
    if i < len(lines):
        upd = _parse_update_line(lines[i])
        if upd:
            updated_at = pd.Timestamp(upd)
            i += 1

    i = _skip_blanks(lines, i)

    def is_hourly_header(line: str) -> bool:
        return line.startswith("DATE,TIME,当日実績(万kW)")

    def is_five_min_header(line: str) -> bool:
        return line.startswith("DATE,TIME,当日実績(５分間隔値)(万kW)")

    summary_blocks: Dict[str, Dict[str, Any]] = {}

    # 2) Pre-hourly summary blocks
    while i < len(lines) and not is_hourly_header(lines[i]):
        if lines[i].strip() == "":
            i += 1
            continue
        blk, ni = _read_one_row_block(lines, i)
        if blk is None:
            i = ni
            continue
        header, row = blk
        block_name = header[0] if header else f"block_{i}"
        summary_blocks[block_name] = {h: (row[idx] if idx < len(row) else "") for idx, h in enumerate(header)}
        i = _skip_blanks(lines, ni)
        if i < len(lines) and is_hourly_header(lines[i]):
            break

    # 3) Hourly table
    i = _skip_blanks(lines, i)
    if i >= len(lines) or not is_hourly_header(lines[i]):
        raise ValueError("Hourly header not found. Input format may differ.")

    hourly_header = _split_csv_line(lines[i])
    i += 1

    hourly_rows: List[List[str]] = []
    while i < len(lines) and lines[i].strip() != "":
        hourly_rows.append(_split_csv_line(lines[i]))
        i += 1

    hourly_df = pd.DataFrame(hourly_rows, columns=hourly_header)
    hourly_df["ts"] = [_parse_date_time(d, t) for d, t in zip(hourly_df["DATE"], hourly_df["TIME"])]
    hourly_df["ts"] = _localize_ts(pd.to_datetime(hourly_df["ts"], errors="coerce"), tz)

    for col in ("当日実績(万kW)", "予測値(万kW)", "供給力(万kW)"):
        if col in hourly_df.columns:
            hourly_df[col] = pd.to_numeric(hourly_df[col], errors="coerce")
    if "使用率(%)" in hourly_df.columns:
        hourly_df["使用率(%)"] = pd.to_numeric(hourly_df["使用率(%)"], errors="coerce")

    if convert_to_mw:
        if "当日実績(万kW)" in hourly_df.columns:
            hourly_df["actual_mw"] = hourly_df["当日実績(万kW)"] * 10.0
        if "予測値(万kW)" in hourly_df.columns:
            hourly_df["forecast_mw"] = hourly_df["予測値(万kW)"] * 10.0
        if "供給力(万kW)" in hourly_df.columns:
            hourly_df["supply_mw"] = hourly_df["供給力(万kW)"] * 10.0
        if "使用率(%)" in hourly_df.columns:
            hourly_df["usage_pct"] = hourly_df["使用率(%)"]

    # 4) Max usage block
    i = _skip_blanks(lines, i)
    if i < len(lines) and lines[i].startswith("最大使用率(%)"):
        blk, i2 = _read_one_row_block(lines, i)
        if blk:
            header, row = blk
            summary_blocks[header[0]] = {h: (row[idx] if idx < len(row) else "") for idx, h in enumerate(header)}
        i = i2
    i = _skip_blanks(lines, i)

    # 5) Next-day blocks until five-min header
    while i < len(lines) and not is_five_min_header(lines[i]):
        if lines[i].strip() == "":
            i += 1
            continue
        blk, ni = _read_one_row_block(lines, i)
        if blk:
            header, row = blk
            block_name = header[0] if header else f"block_{i}"
            summary_blocks[block_name] = {h: (row[idx] if idx < len(row) else "") for idx, h in enumerate(header)}
        i = _skip_blanks(lines, ni)

    # 6) Five-minute table
    i = _skip_blanks(lines, i)
    if i >= len(lines) or not is_five_min_header(lines[i]):
        raise ValueError("5-minute header not found. Input format may differ.")

    min5_header = _split_csv_line(lines[i])
    i += 1

    min5_rows: List[List[str]] = []
    while i < len(lines) and lines[i].strip() != "":
        min5_rows.append(_split_csv_line(lines[i]))
        i += 1

    min5_df = pd.DataFrame(min5_rows, columns=min5_header)
    min5_df["ts"] = [_parse_date_time(d, t) for d, t in zip(min5_df["DATE"], min5_df["TIME"])]
    min5_df["ts"] = _localize_ts(pd.to_datetime(min5_df["ts"], errors="coerce"), tz)

    for col in (
        "当日実績(５分間隔値)(万kW)",
        "太陽光発電実績(５分間隔値)(万kW)",
        "太陽光発電量(電力使用量に対する割合)(%)",
    ):
        if col in min5_df.columns:
            min5_df[col] = pd.to_numeric(min5_df[col], errors="coerce")

    if convert_to_mw:
        if "当日実績(５分間隔値)(万kW)" in min5_df.columns:
            min5_df["actual_mw"] = min5_df["当日実績(５分間隔値)(万kW)"] * 10.0
        if "太陽光発電実績(５分間隔値)(万kW)" in min5_df.columns:
            min5_df["solar_mw"] = min5_df["太陽光発電実績(５分間隔値)(万kW)"] * 10.0
        if "太陽光発電量(電力使用量に対する割合)(%)" in min5_df.columns:
            min5_df["solar_ratio_pct"] = min5_df["太陽光発電量(電力使用量に対する割合)(%)"]

    if updated_at is not None and tz is not None:
        try:
            updated_at = updated_at.tz_localize(tz)
        except Exception:
            pass

    # 7) Quality checks
    quality: Dict[str, Any] = {}
    quality["hourly"] = _quality_time_series(hourly_df["ts"], expected_count=24, expected_freq="1h")
    quality["five_min"] = _quality_time_series(min5_df["ts"], expected_count=288, expected_freq="5min")

    if "solar_mw" in min5_df.columns:
        quality["five_min_solar_all_zero"] = bool((min5_df["solar_mw"].fillna(0.0) == 0.0).all())

    def _range_check(series_name: str, s: pd.Series, low: float, high: float) -> Dict[str, Any]:
        s2 = pd.to_numeric(s, errors="coerce")
        bad = s2[(s2 < low) | (s2 > high)]
        return {"count": int(len(bad)), "examples": [float(x) for x in bad.head(3).tolist()]}

    if "usage_pct" in hourly_df.columns:
        quality["usage_pct_out_of_range"] = _range_check("usage_pct", hourly_df["usage_pct"], 0.0, 110.0)

    if "actual_mw" in hourly_df.columns:
        quality["actual_mw_negative"] = {"count": int((hourly_df["actual_mw"] < 0).sum())}

    quality["summary_normalized"] = normalize_summary_blocks(summary_blocks)

    return TepcoDailyParsed(
        source_path=str(path),
        encoding_used=enc_used,
        updated_at=updated_at,
        summary_blocks=summary_blocks,
        hourly=hourly_df,
        five_min=min5_df,
        quality=quality,
    )


def parse_directory(
    dir_path: str | Path,
    *,
    glob_pattern: str = "*.csv",
    encoding: Optional[str] = None,
    convert_to_mw: bool = True,
    tz: Optional[str] = "Asia/Tokyo",
) -> pd.DataFrame:
    """
    Parse many TEPCO daily CSVs under a directory and return a single hourly DataFrame.
    """
    p = Path(dir_path)
    rows: List[pd.DataFrame] = []
    for fp in sorted(p.glob(glob_pattern)):
        parsed = parse_tepc_daily_csv(fp, encoding=encoding, convert_to_mw=convert_to_mw, tz=tz)
        df = parsed.hourly.copy()
        df["source_file"] = fp.name
        df["updated_at"] = parsed.updated_at
        rows.append(df)

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows, ignore_index=True)
