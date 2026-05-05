"""Tests for python/etl/quality_gate.py."""
from __future__ import annotations

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from python.etl.quality_gate import run_quality_gate, QualityStatus
from python.tepc_parser import TepcoDailyParsed

JST = ZoneInfo("Asia/Tokyo")


def _make_hourly(n: int = 24, with_actual: bool = True, all_nan: bool = False) -> pd.DataFrame:
    base = pd.Timestamp("2024-01-01", tz=JST)
    ts = [base + pd.Timedelta(hours=h) for h in range(n)]
    df = pd.DataFrame({"ts": ts})
    if with_actual:
        df["actual_mw"] = float("nan") if all_nan else 30000.0
    return df


def _make_quality(
    n: int = 24,
    duplicates: int = 0,
    monotonic: bool = True,
    freq_mismatch: int | None = 0,
) -> dict:
    return {
        "hourly": {
            "rows": n,
            "expected_count_ok": n == 24,
            "duplicates": duplicates,
            "monotonic_increasing": monotonic,
            "freq_mismatch_count": freq_mismatch,
        }
    }


def _parsed(hourly: pd.DataFrame, quality: dict) -> TepcoDailyParsed:
    return TepcoDailyParsed(
        source_path="fake.csv",
        encoding_used="utf-8",
        updated_at=None,
        summary_blocks={},
        hourly=hourly,
        five_min=pd.DataFrame(),
        quality=quality,
    )


# ── PASSED ──────────────────────────────────────────────────────────────────

def test_passed_clean_data():
    p = _parsed(_make_hourly(), _make_quality())
    assert run_quality_gate(p) == QualityStatus.PASSED


def test_passed_freq_mismatch_exactly_at_boundary():
    p = _parsed(_make_hourly(), _make_quality(freq_mismatch=4))
    assert run_quality_gate(p) == QualityStatus.PASSED


# ── FAILED ───────────────────────────────────────────────────────────────────

def test_failed_empty_hourly():
    p = _parsed(pd.DataFrame(), _make_quality(n=0))
    assert run_quality_gate(p) == QualityStatus.FAILED


def test_failed_wrong_row_count_23():
    p = _parsed(_make_hourly(n=23), _make_quality(n=23))
    assert run_quality_gate(p) == QualityStatus.FAILED


def test_failed_wrong_row_count_25():
    p = _parsed(_make_hourly(n=25), _make_quality(n=25))
    assert run_quality_gate(p) == QualityStatus.FAILED


def test_failed_no_actual_mw_column():
    p = _parsed(_make_hourly(with_actual=False), _make_quality())
    assert run_quality_gate(p) == QualityStatus.FAILED


def test_failed_all_nan_actual_mw():
    h = _make_hourly(all_nan=True)
    p = _parsed(h, _make_quality())
    assert run_quality_gate(p) == QualityStatus.FAILED


# ── WARNING ──────────────────────────────────────────────────────────────────

def test_warning_duplicate_timestamps():
    p = _parsed(_make_hourly(), _make_quality(duplicates=1))
    assert run_quality_gate(p) == QualityStatus.WARNING


def test_warning_non_monotonic_timestamps():
    p = _parsed(_make_hourly(), _make_quality(monotonic=False))
    assert run_quality_gate(p) == QualityStatus.WARNING


def test_warning_freq_mismatch_above_threshold():
    p = _parsed(_make_hourly(), _make_quality(freq_mismatch=5))
    assert run_quality_gate(p) == QualityStatus.WARNING


def test_warning_freq_mismatch_well_above():
    p = _parsed(_make_hourly(), _make_quality(freq_mismatch=20))
    assert run_quality_gate(p) == QualityStatus.WARNING
