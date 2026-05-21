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
    _apply_forecast_humidity_fallbacks,
    _fetch_json,
    _parse_jma_amedas_point,
    _parse_jma_official_timeseries,
    _parse_response,
    _empty_weather_frame,
    enrich_cache_with_weather,
    fetch_forecast_temps,
    fetch_jma_observed_temps,
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
        "relative_humidity_2m": [70, 72, 74, 76],
    }
}

_SAMPLE_WITH_NULL = {
    "hourly": {
        "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
        "temperature_2m": [5.2, None],
        "apparent_temperature": [3.2, None],
        "relative_humidity_2m": [70, None],
    }
}

_JMA_OFFICIAL_TIMESERIES_RESPONSE = {
    "firstAreaCode": "130010",
    "reportDateTime": "2026-05-17T17:00:00+09:00",
    "pointTimeSeries": {
        "pointNameEN": "Tokyo",
        "timeDefines": [
            {"dateTime": "2026-05-18T00:00:00+09:00"},
            {"dateTime": "2026-05-18T03:00:00+09:00"},
            {"dateTime": "2026-05-18T06:00:00+09:00"},
            {"dateTime": "2026-05-18T09:00:00+09:00"},
            {"dateTime": "2026-05-18T12:00:00+09:00"},
            {"dateTime": "2026-05-18T15:00:00+09:00"},
            {"dateTime": "2026-05-18T18:00:00+09:00"},
            {"dateTime": "2026-05-18T21:00:00+09:00"},
            {"dateTime": "2026-05-19T00:00:00+09:00"},
        ],
        "temperature": [18, 17, 17, 21, 27, 28, 23, 20, 19],
        "maxTemperature": ["", "", "", 29, 29, 29, 29, "", ""],
        "minTemperature": [16, 16, 16, 16, "", "", "", "", ""],
    },
}

_JMA_AMEDAS_POINT_RESPONSE = {
    "20260518090000": {
        "prefNumber": 44,
        "observationNumber": 132,
        "temp": [24.6, 0],
        "humidity": [70, 0],
        "wind": [1.0, 0],
    },
    "20260518091000": {
        "prefNumber": 44,
        "observationNumber": 132,
        "temp": [24.9, 0],
        "humidity": [72, 0],
        "wind": [1.1, 0],
    },
    "20260518100000": {
        "prefNumber": 44,
        "observationNumber": 132,
        "temp": [25.6, 0],
        "humidity": [75, 0],
        "wind": [1.0, 0],
    },
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
    assert list(df.columns) == [
        "ts", "temp_c", "apparent_temp_c", "humidity_pct",
        "discomfort_index", "weather_source",
    ]


def test_parse_response_tz_is_jst():
    df = _parse_response(_SAMPLE_RESPONSE)
    assert str(df["ts"].dt.tz) == "Asia/Tokyo"


def test_parse_response_values():
    df = _parse_response(_SAMPLE_RESPONSE)
    assert df["temp_c"].iloc[0] == pytest.approx(5.2)
    assert df["temp_c"].iloc[1] == pytest.approx(4.8)
    assert df["apparent_temp_c"].iloc[0] == pytest.approx(3.2)
    assert df["humidity_pct"].iloc[0] == pytest.approx(70.0)
    assert df["discomfort_index"].iloc[0] == pytest.approx(44.1)
    assert df["weather_source"].iloc[0] == "OPEN_METEO"


def test_parse_response_null_becomes_nan():
    import math
    df = _parse_response(_SAMPLE_WITH_NULL)
    assert math.isnan(df["temp_c"].iloc[1])
    assert math.isnan(df["apparent_temp_c"].iloc[1])
    assert math.isnan(df["humidity_pct"].iloc[1])
    assert math.isnan(df["discomfort_index"].iloc[1])


# ---------------------------------------------------------------------------
# _parse_jma_official_timeseries
# ---------------------------------------------------------------------------

def test_parse_jma_official_timeseries_interpolates_to_hourly():
    df = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )

    assert len(df) == 24
    assert str(df["ts"].dt.tz) == "Asia/Tokyo"
    assert df["ts"].iloc[0] == pd.Timestamp("2026-05-18T00:00:00+09:00")
    assert df["ts"].iloc[-1] == pd.Timestamp("2026-05-18T23:00:00+09:00")


def test_parse_jma_official_timeseries_keeps_official_min_max():
    df = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )

    assert df["temp_c"].min() == pytest.approx(16.0)
    assert df["temp_c"].max() == pytest.approx(29.0)
    assert df["weather_source"].unique().tolist() == ["JMA_FORECAST"]


# ---------------------------------------------------------------------------
# _parse_jma_amedas_point / fetch_jma_observed_temps
# ---------------------------------------------------------------------------

def test_parse_jma_amedas_point_keeps_exact_hourly_observations():
    df = _parse_jma_amedas_point(_JMA_AMEDAS_POINT_RESPONSE)

    assert len(df) == 2
    assert df["ts"].iloc[0] == pd.Timestamp("2026-05-18T09:00:00+09:00")
    assert df["temp_c"].iloc[0] == pytest.approx(24.6)
    assert df["humidity_pct"].iloc[1] == pytest.approx(75.0)
    assert df["discomfort_index"].iloc[1] == pytest.approx(75.3)
    assert df["apparent_temp_c"].iloc[1] > df["temp_c"].iloc[1]
    assert df["weather_source"].iloc[0] == "AMEDAS_ACTUAL"


def test_fetch_jma_observed_temps_fetches_three_hour_blocks():
    with patch("python.etl.fetch_weather._fetch_json", return_value=_JMA_AMEDAS_POINT_RESPONSE) as mock:
        result = fetch_jma_observed_temps(date(2026, 5, 18), date(2026, 5, 18))

    assert mock.call_count == 8
    assert len(result) == 2
    first_url = mock.call_args_list[0][0][0]
    assert first_url.endswith("/44132/20260518_00.json")


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


def test_fetch_past_temps_uses_tokyo_center_coordinates():
    with patch("python.etl.fetch_weather._fetch_json", return_value=_SAMPLE_RESPONSE) as mock:
        fetch_past_temps(date(2024, 3, 15), date(2024, 3, 20))
    params = mock.call_args[0][1]
    assert params["latitude"] == pytest.approx(35.6589)
    assert params["longitude"] == pytest.approx(139.7066)


# ---------------------------------------------------------------------------
# fetch_forecast_temps
# ---------------------------------------------------------------------------

def test_fetch_forecast_temps_returns_dataframe():
    official = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )
    with (
        patch("python.etl.fetch_weather.fetch_jma_official_forecast_temps", return_value=official),
        patch("python.etl.fetch_weather.fetch_jma_observed_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_open_meteo_jma_forecast_temps", return_value=_empty_weather_frame()),
    ):
        result = fetch_forecast_temps(days=1)
    assert isinstance(result, pd.DataFrame)
    assert "temp_c" in result.columns
    assert "apparent_temp_c" in result.columns
    assert "weather_source" in result.columns


def test_fetch_forecast_temps_passes_days():
    official = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )
    with (
        patch("python.etl.fetch_weather.fetch_jma_official_forecast_temps", return_value=official) as mock,
        patch("python.etl.fetch_weather.fetch_jma_observed_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_open_meteo_jma_forecast_temps", return_value=_empty_weather_frame()),
    ):
        fetch_forecast_temps(days=5)
    mock.assert_called_once_with(days=5)


def test_fetch_forecast_temps_uses_official_jma_timeseries_endpoint():
    official = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )
    with (
        patch("python.etl.fetch_weather._parse_jma_official_timeseries", return_value=official),
        patch("python.etl.fetch_weather.fetch_jma_observed_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_open_meteo_jma_forecast_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_json", return_value={}) as mock,
    ):
        fetch_forecast_temps(days=5)
    url = mock.call_args_list[0][0][0]
    assert url == "https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/130010.json"


def test_fetch_forecast_temps_passes_no_open_meteo_coordinates():
    official = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )
    with (
        patch("python.etl.fetch_weather._parse_jma_official_timeseries", return_value=official),
        patch("python.etl.fetch_weather.fetch_jma_observed_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_open_meteo_jma_forecast_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_json", return_value={}) as mock,
    ):
        fetch_forecast_temps(days=5)
    params = mock.call_args_list[0][0][1]
    assert params == {}


def test_fetch_forecast_temps_keeps_official_temperature_and_fills_humidity_from_open_meteo():
    official = _parse_jma_official_timeseries(
        _JMA_OFFICIAL_TIMESERIES_RESPONSE,
        days=1,
        today=date(2026, 5, 18),
    )
    fallback = official[["ts"]].copy()
    fallback["temp_c"] = 99.0
    fallback["apparent_temp_c"] = 99.0
    fallback["humidity_pct"] = 82.0
    fallback["discomfort_index"] = 80.0
    fallback["weather_source"] = "OPEN_METEO_JMA"

    with (
        patch("python.etl.fetch_weather.fetch_jma_official_forecast_temps", return_value=official),
        patch("python.etl.fetch_weather.fetch_jma_observed_temps", return_value=_empty_weather_frame()),
        patch("python.etl.fetch_weather._fetch_open_meteo_jma_forecast_temps", return_value=fallback),
    ):
        result = fetch_forecast_temps(days=1)

    assert len(result) == 24
    assert result["temp_c"].max() == pytest.approx(29.0)
    assert result["temp_c"].min() == pytest.approx(16.0)
    assert result["humidity_pct"].iloc[0] == pytest.approx(82.0)
    peak = result.loc[result["temp_c"].idxmax()]
    assert peak["apparent_temp_c"] != pytest.approx(99.0)
    assert peak["weather_source"] == "JMA_FORECAST+OPEN_METEO_JMA"


def test_forecast_humidity_fallback_prefers_short_amedas_forward_fill():
    base = pd.Timestamp("2026-05-18T09:00:00+09:00")
    forecast = pd.DataFrame({
        "ts": [base + pd.Timedelta(hours=i) for i in range(5)],
        "temp_c": [24.0, 25.0, 26.0, 27.0, 28.0],
        "apparent_temp_c": [24.0, 25.0, 26.0, 27.0, 28.0],
        "humidity_pct": [float("nan")] * 5,
        "discomfort_index": [float("nan")] * 5,
        "weather_source": ["JMA_FORECAST"] * 5,
    })
    observed = pd.DataFrame({
        "ts": [base],
        "temp_c": [24.0],
        "apparent_temp_c": [26.0],
        "humidity_pct": [74.0],
        "discomfort_index": [73.0],
        "weather_source": ["AMEDAS_ACTUAL"],
    })
    fallback = pd.DataFrame({
        "ts": forecast["ts"],
        "temp_c": [99.0] * 5,
        "apparent_temp_c": [99.0] * 5,
        "humidity_pct": [55.0] * 5,
        "discomfort_index": [60.0] * 5,
        "weather_source": ["OPEN_METEO_JMA"] * 5,
    })

    result = _apply_forecast_humidity_fallbacks(
        forecast,
        observed,
        fallback,
        forward_fill_hours=3,
    )

    assert result.loc[result["ts"] == base + pd.Timedelta(hours=1), "humidity_pct"].iloc[0] == pytest.approx(74.0)
    assert result.loc[result["ts"] == base + pd.Timedelta(hours=3), "humidity_pct"].iloc[0] == pytest.approx(74.0)
    assert result.loc[result["ts"] == base + pd.Timedelta(hours=4), "humidity_pct"].iloc[0] == pytest.approx(55.0)
    assert result.loc[result["ts"] == base + pd.Timedelta(hours=1), "weather_source"].iloc[0] == "JMA_FORECAST+FORWARD_FILL"
    assert result["temp_c"].iloc[-1] == pytest.approx(28.0)


def test_forecast_humidity_fallback_uses_seasonal_mean_last():
    ts = pd.Timestamp("2026-05-18T12:00:00+09:00")
    forecast = pd.DataFrame({
        "ts": [ts],
        "temp_c": [25.0],
        "apparent_temp_c": [25.0],
        "humidity_pct": [float("nan")],
        "discomfort_index": [float("nan")],
        "weather_source": ["JMA_FORECAST"],
    })

    result = _apply_forecast_humidity_fallbacks(
        forecast,
        _empty_weather_frame(),
        _empty_weather_frame(),
        forward_fill_hours=3,
    )

    assert result["humidity_pct"].iloc[0] == pytest.approx(68.0)
    assert result["weather_source"].iloc[0] == "JMA_FORECAST+SEASONAL_MEAN"


def test_fetch_forecast_temps_raises_when_official_jma_fails():
    with (
        patch(
            "python.etl.fetch_weather.fetch_jma_official_forecast_temps",
            side_effect=OSError("official unavailable"),
        ),
        patch("python.etl.fetch_weather._fetch_open_meteo_jma_forecast_temps") as fallback,
        pytest.raises(OSError),
    ):
        fetch_forecast_temps(days=1)

    fallback.assert_not_called()


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
    cache["humidity_pct"] = [60.0, 61.0, 62.0, 63.0]
    cache["discomfort_index"] = [45.0, 46.0, 47.0, 48.0]

    with patch("python.etl.fetch_weather._fetch_json") as mock:
        result = enrich_cache_with_weather(cache)

    mock.assert_not_called()
    assert list(result["temp_c"]) == [5.0, 6.0, 7.0, 8.0]
    assert list(result["apparent_temp_c"]) == [4.0, 5.0, 6.0, 7.0]


def test_enrich_does_not_backfill_legacy_humidity_only_gaps():
    cache = _make_cache_no_temp(4)
    cache["temp_c"] = [5.0, 6.0, 7.0, 8.0]
    cache["apparent_temp_c"] = [4.0, 5.0, 6.0, 7.0]
    cache["humidity_pct"] = float("nan")
    cache["discomfort_index"] = float("nan")

    with patch("python.etl.fetch_weather._fetch_json") as mock:
        result = enrich_cache_with_weather(cache)

    mock.assert_not_called()
    assert result["humidity_pct"].isna().all()


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
