"""Tests for daily-level feature aggregation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from python.forecast.daily_level import (
    DAILY_CALENDAR_FEATURES,
    DAILY_DEMAND_FEATURES,
    DAILY_WEATHER_FEATURES,
    build_daily_level_features,
    build_daily_level_training_set,
)


def _hourly_features(days: int = 2) -> pd.DataFrame:
    hours = np.tile(np.arange(24), days)
    data: dict[str, np.ndarray] = {"hour": hours}
    for column in DAILY_CALENDAR_FEATURES:
        data[column] = np.repeat(np.arange(days), 24).astype(float)
    for column in (*DAILY_DEMAND_FEATURES, *DAILY_WEATHER_FEATURES):
        data[column] = np.arange(days * 24, dtype=float)
    return pd.DataFrame(data)


def test_daily_level_features_aggregate_complete_days_and_time_bands():
    hourly = _hourly_features()

    daily, starts = build_daily_level_features(hourly)

    assert starts == [0, 24]
    assert len(daily) == 2
    assert daily.loc[0, "lag_24h__mean"] == pytest.approx(11.5)
    assert daily.loc[0, "lag_24h__morning_mean"] == pytest.approx(8.5)
    assert daily.loc[1, "temp_c__max"] == pytest.approx(47.0)


def test_daily_level_features_skip_partial_edges():
    complete = _hourly_features()
    prefix = complete.iloc[21:24]
    suffix = complete.iloc[:2]
    hourly = pd.concat([prefix, complete, suffix], ignore_index=True)

    daily, starts = build_daily_level_features(hourly)

    assert starts == [3, 27]
    assert len(daily) == 2


def test_daily_level_training_target_is_observed_daily_mean():
    hourly = _hourly_features()
    target = pd.Series(np.arange(48, dtype=float))

    daily, daily_target = build_daily_level_training_set(hourly, target)

    assert len(daily) == 2
    assert daily_target.tolist() == pytest.approx([11.5, 35.5])


def test_daily_level_features_reject_missing_contract_column():
    hourly = _hourly_features().drop(columns=["temp_c"])

    with pytest.raises(ValueError, match="temp_c"):
        build_daily_level_features(hourly)


def test_daily_level_features_allow_missing_future_weather_values():
    hourly = _hourly_features(days=1)
    hourly["humidity_pct"] = np.nan
    hourly.loc[0, "temp_c"] = np.nan

    daily, _ = build_daily_level_features(hourly)

    assert np.isnan(daily.loc[0, "humidity_pct__mean"])
    assert daily.loc[0, "temp_c__mean"] == pytest.approx(np.mean(np.arange(1, 24)))
