"""Daily demand-level features used by the v14 hierarchical q50 contract."""
from __future__ import annotations

import numpy as np
import pandas as pd


DAILY_CALENDAR_FEATURES = (
    "dayofweek",
    "month",
    "is_holiday",
    "is_weekend",
    "is_non_business_day",
    "consec_holiday_len",
    "days_since_holiday_end",
    "major_holiday_season",
    "lag_24h_business_type_mismatch",
)

DAILY_DEMAND_FEATURES = (
    "lag_24h",
    "lag_48h",
    "lag_168h",
    "lag_336h",
    "roll_4w_mean",
    "roll_4w_std",
    "lag_last_biz_hour",
    "lag_last_nonhol_hour",
    "recent_same_business_type_mean",
    "lag_24h_to_last_biz_gap",
    "lag_24h_to_same_business_type_gap",
)

DAILY_WEATHER_FEATURES = (
    "temp_c",
    "cooling_degree",
    "heating_degree",
    "apparent_temp_c",
    "apparent_cooling_degree",
    "humidity_pct",
    "discomfort_index",
    "temp_anomaly_7d",
    "temp_anomaly_doy",
    "temp_delta_24h",
    "cooling_delta_24h",
    "temp_delta_168h",
    "cooling_delta_168h",
    "temp_72h_mean",
    "cooling_degree_72h_mean",
    "heating_degree_72h_mean",
)

_TIME_BANDS = (
    ("overnight", slice(0, 6)),
    ("morning", slice(6, 12)),
    ("daytime", slice(12, 18)),
    ("evening", slice(18, 24)),
)


def _finite_stat(values: np.ndarray, operation: str) -> float:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return float("nan")
    if operation == "mean":
        return float(np.mean(finite))
    if operation == "min":
        return float(np.min(finite))
    if operation == "max":
        return float(np.max(finite))
    if operation == "std":
        return float(np.std(finite))
    raise ValueError(f"Unsupported daily statistic: {operation}")


def _complete_day_starts(hourly: pd.DataFrame) -> list[int]:
    hours = hourly["hour"].to_numpy(dtype=int)
    starts: list[int] = []
    for index in np.flatnonzero(hours == 0):
        end = int(index) + 24
        if end <= len(hours) and np.array_equal(hours[index:end], np.arange(24)):
            starts.append(int(index))
    return starts


def build_daily_level_features(
    hourly: pd.DataFrame,
) -> tuple[pd.DataFrame, list[int]]:
    """Aggregate every complete 00-23 feature block into one daily row."""
    required = {
        "hour",
        *DAILY_CALENDAR_FEATURES,
        *DAILY_DEMAND_FEATURES,
        *DAILY_WEATHER_FEATURES,
    }
    missing = sorted(required.difference(hourly.columns))
    if missing:
        raise ValueError(
            "Daily-level feature input is incomplete: " + ", ".join(missing)
        )

    starts = _complete_day_starts(hourly)
    records: list[dict[str, float]] = []
    for start in starts:
        day = hourly.iloc[start:start + 24]
        record: dict[str, float] = {}
        for column in DAILY_CALENDAR_FEATURES:
            record[column] = float(day[column].iloc[0])
        for column in DAILY_DEMAND_FEATURES:
            values = day[column].to_numpy(dtype=float)
            record[f"{column}__mean"] = _finite_stat(values, "mean")
            record[f"{column}__min"] = _finite_stat(values, "min")
            record[f"{column}__max"] = _finite_stat(values, "max")
            record[f"{column}__std"] = _finite_stat(values, "std")
            for band_name, band_slice in _TIME_BANDS:
                record[f"{column}__{band_name}_mean"] = _finite_stat(
                    values[band_slice],
                    "mean",
                )
        for column in DAILY_WEATHER_FEATURES:
            values = day[column].to_numpy(dtype=float)
            record[f"{column}__mean"] = _finite_stat(values, "mean")
            record[f"{column}__min"] = _finite_stat(values, "min")
            record[f"{column}__max"] = _finite_stat(values, "max")
        records.append(record)

    features = pd.DataFrame.from_records(records)
    if not features.empty and np.isinf(features.to_numpy(dtype=float)).any():
        raise ValueError("Daily-level features contain infinite values.")
    return features, starts


def build_daily_level_training_set(
    hourly_features: pd.DataFrame,
    hourly_target: pd.Series,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return daily inputs and the corresponding observed daily mean demand."""
    if len(hourly_features) != len(hourly_target):
        raise ValueError("Hourly feature and target row counts differ.")
    daily_features, starts = build_daily_level_features(hourly_features)
    target = hourly_target.to_numpy(dtype=float)
    daily_target = pd.Series(
        [float(np.mean(target[start:start + 24])) for start in starts],
        name="daily_mean_actual_mw",
        dtype=float,
    )
    return daily_features, daily_target
