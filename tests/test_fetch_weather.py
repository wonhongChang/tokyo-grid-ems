"""Tests for python/etl/fetch_weather.py."""
from __future__ import annotations

import json
import urllib.error
from datetime import date
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from python.etl.fetch_weather import (
    _fetch_json,
    _parse_response,
    enrich_cache_with_weather,
    fetch_forecast_temps,
    fetch_past_temps,
)

JST = ZoneInfo("Asia/Tokyo")

_SAMPLE_RESPONSE = {
    "hourly": {
        "time": [
            "2024-01-01T00:00", "2024-01-01T01:00",
            "2024-01-01T02:00", "2024-01-01T03:00",
        ],
        "temperature_2m": [5.2, 4.8, 4.5, 4.1],
        "apparent_temperature": [3.2, 2.8, 2.5, 2.1],
    }
}

_SAMPLE_WITH_NULL = {
    "hourly": {
        "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
        "temperature_2m": [5.2, None],
        "apparent_temperature": [3.2, None],
    }
}


class _MockHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _make_mock_fetch(data: dict):
    """Patch _fetch_json to return data."""
    return patch("python.etl.fetch_weather._fetch_json", return_value=data)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_shape():
    df = _parse_response(_SAMPLE_RESPONSE)
    assert len(df) == 4
    assert list(df.columns) == ["ts", "temp_c", "apparent_temp_c"]


def test_parse_response_tz_is_jst():
    df = _parse_response(_SAMPLE_RESPONSE)
    assert str(df["ts"].dt.tz) == "Asia/Tokyo"


def test_parse_response_values():
    df = _parse_response(_SAMPLE_RESPONSE)
    assert df["temp_c"].iloc[0] == pytest.approx(5.2)
    assert df["temp_c"].iloc[1] == pytest.approx(4.8)
    assert df["apparent_temp_c"].iloc[0] == pytest.approx(3.2)


def test_parse_response_null_becomes_nan():
    import math
    df = _parse_response(_SAMPLE_WITH_NULL)
    assert math.isnan(df["temp_c"].iloc[1])
    assert math.isnan(df["apparent_temp_c"].iloc[1])


# ---------------------------------------------------------------------------
# _fetch_json
# ---------------------------------------------------------------------------

def test_fetch_json_retries_transient_failure():
    with (
        patch("python.etl.fetch_weather.time.sleep") as sleep,
        patch(
            "python.etl.fetch_weather.urllib.request.urlopen",
            side_effect=[OSError("temporary network error"), _MockHTTPResponse(_SAMPLE_RESPONSE)],
        ) as urlopen,
    ):
        result = _fetch_json("https://example.test/weather", {"forecast_days": 1})

    assert result == _SAMPLE_RESPONSE
    assert urlopen.call_count == 2
    sleep.assert_called_once()


def test_fetch_json_does_not_retry_non_rate_limited_4xx():
    err = urllib.error.HTTPError(
        "https://example.test/weather", 404, "not found", hdrs=None, fp=None
    )

    with (
        patch("python.etl.fetch_weather.time.sleep") as sleep,
        patch("python.etl.fetch_weather.urllib.request.urlopen", side_effect=err) as urlopen,
        pytest.raises(urllib.error.HTTPError),
    ):
        _fetch_json("https://example.test/weather", {"forecast_days": 1})

    assert urlopen.call_count == 1
    sleep.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_past_temps
# ---------------------------------------------------------------------------

def test_fetch_past_temps_returns_dataframe():
    with _make_mock_fetch(_SAMPLE_RESPONSE):
        result = fetch_past_temps(date(2024, 1, 1), date(2024, 1, 1))
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 4


def test_fetch_past_temps_passes_correct_dates():
    with patch("python.etl.fetch_weather._fetch_json", return_value=_SAMPLE_RESPONSE) as mock:
        fetch_past_temps(date(2024, 3, 15), date(2024, 3, 20))
    _, kwargs = mock.call_args
    args = mock.call_args[0]
    params = args[1]
    assert params["start_date"] == "2024-03-15"
    assert params["end_date"]   == "2024-03-20"


# ---------------------------------------------------------------------------
# fetch_forecast_temps
# ---------------------------------------------------------------------------

def test_fetch_forecast_temps_returns_dataframe():
    with _make_mock_fetch(_SAMPLE_RESPONSE):
        result = fetch_forecast_temps(days=1)
    assert isinstance(result, pd.DataFrame)
    assert "temp_c" in result.columns
    assert "apparent_temp_c" in result.columns


def test_fetch_forecast_temps_passes_days():
    with patch("python.etl.fetch_weather._fetch_json", return_value=_SAMPLE_RESPONSE) as mock:
        fetch_forecast_temps(days=5)
    params = mock.call_args[0][1]
    assert params["forecast_days"] == 5


# ---------------------------------------------------------------------------
# enrich_cache_with_weather
# ---------------------------------------------------------------------------

def _make_cache_no_temp(n: int = 48) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-01", tz=JST)
    ts = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({
        "ts":        ts,
        "actual_mw": 20_000.0,
        "temp_c":    float("nan"),
    })


def test_enrich_fills_missing_temp_c():
    cache = _make_cache_no_temp(4)
    weather_response = {
        "hourly": {
            "time": [t.strftime("%Y-%m-%dT%H:%M") for t in cache["ts"]],
            "temperature_2m": [10.0, 11.0, 12.0, 13.0],
            "apparent_temperature": [9.0, 10.0, 11.0, 12.0],
        }
    }
    with _make_mock_fetch(weather_response):
        result = enrich_cache_with_weather(cache)

    assert result["temp_c"].notna().all()
    assert result["apparent_temp_c"].notna().all()
    assert result["temp_c"].iloc[0] == pytest.approx(10.0)
    assert result["apparent_temp_c"].iloc[0] == pytest.approx(9.0)


def test_enrich_no_op_when_already_filled():
    cache = _make_cache_no_temp(4)
    cache["temp_c"] = [5.0, 6.0, 7.0, 8.0]
    cache["apparent_temp_c"] = [4.0, 5.0, 6.0, 7.0]

    with patch("python.etl.fetch_weather._fetch_json") as mock:
        result = enrich_cache_with_weather(cache)

    mock.assert_not_called()
    assert list(result["temp_c"]) == [5.0, 6.0, 7.0, 8.0]
    assert list(result["apparent_temp_c"]) == [4.0, 5.0, 6.0, 7.0]


def test_enrich_no_op_when_no_temp_col():
    cache = _make_cache_no_temp(4).drop(columns=["temp_c"])
    cache["temp_c"] = float("nan")   # explicit NaN column

    # No actual_mw data → nothing to fill
    cache_no_actual = cache.copy()
    cache_no_actual["actual_mw"] = float("nan")

    with patch("python.etl.fetch_weather._fetch_json") as mock:
        enrich_cache_with_weather(cache_no_actual)

    mock.assert_not_called()


def test_enrich_does_not_modify_original():
    cache = _make_cache_no_temp(4)
    original_temp = cache["temp_c"].copy()

    weather_response = {
        "hourly": {
            "time": [t.strftime("%Y-%m-%dT%H:%M") for t in cache["ts"]],
            "temperature_2m": [10.0, 11.0, 12.0, 13.0],
            "apparent_temperature": [9.0, 10.0, 11.0, 12.0],
        }
    }
    with _make_mock_fetch(weather_response):
        enrich_cache_with_weather(cache)

    # Original must be untouched
    assert cache["temp_c"].isna().all()


def test_enrich_graceful_on_api_failure():
    cache = _make_cache_no_temp(4)

    with patch("python.etl.fetch_weather._fetch_json", side_effect=OSError("network error")):
        result = enrich_cache_with_weather(cache)

    # Cache returned unchanged (temp_c still NaN), no exception raised
    assert result["temp_c"].isna().all()
