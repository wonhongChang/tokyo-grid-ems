"""Tests for python/tepc_parser.py using a real TEPCO CSV file."""
import pandas as pd
import pytest


def test_hourly_row_count(parsed_sample):
    assert len(parsed_sample.hourly) == 24


def test_five_min_row_count(parsed_sample):
    assert len(parsed_sample.five_min) == 288


def test_hourly_ts_is_tz_aware(parsed_sample):
    assert parsed_sample.hourly["ts"].dt.tz is not None


def test_five_min_ts_is_tz_aware(parsed_sample):
    assert parsed_sample.five_min["ts"].dt.tz is not None


def test_actual_mw_is_numeric(parsed_sample):
    assert pd.api.types.is_numeric_dtype(parsed_sample.hourly["actual_mw"])


def test_actual_mw_no_negatives(parsed_sample):
    vals = parsed_sample.hourly["actual_mw"].dropna()
    assert (vals >= 0).all()


def test_supply_mw_column_present(parsed_sample):
    assert "supply_mw" in parsed_sample.hourly.columns


def test_usage_pct_in_range(parsed_sample):
    pct = parsed_sample.hourly["usage_pct"].dropna()
    assert (pct >= 0).all() and (pct <= 110).all()


def test_updated_at_is_set(parsed_sample):
    assert parsed_sample.updated_at is not None


def test_encoding_auto_detected(parsed_sample):
    valid_encodings = ("cp932", "shift_jis", "utf-8", "utf-8-sig", "cp932(errors=replace)")
    assert parsed_sample.encoding_used in valid_encodings


def test_quality_hourly_expected_count_ok(parsed_sample):
    assert parsed_sample.quality["hourly"]["expected_count_ok"] is True


def test_quality_five_min_expected_count_ok(parsed_sample):
    assert parsed_sample.quality["five_min"]["expected_count_ok"] is True


def test_hourly_ts_is_jst(parsed_sample):
    tz = parsed_sample.hourly["ts"].dt.tz
    assert str(tz) in ("Asia/Tokyo", "JST", "+09:00")


def test_mw_conversion_multiplier(parsed_sample):
    """actual_mw should be 万kW column × 10. Spot-check a row."""
    h = parsed_sample.hourly
    if "当日実績(万kW)" in h.columns:
        raw = h["当日実績(万kW)"].dropna()
        converted = h["actual_mw"].dropna()
        assert (abs(converted - raw * 10) < 0.1).all()
