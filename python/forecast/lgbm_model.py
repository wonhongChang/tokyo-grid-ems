"""LightGBM quantile regression forecaster for hourly electricity demand."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from python.forecast.baseline import HourlyForecast
from python.forecast.feature_builder import (
    build_inference_features,
    build_training_features,
)

try:
    from lightgbm import LGBMRegressor
    _HAS_LGBM = True
except ImportError:
    _HAS_LGBM = False

JST = ZoneInfo("Asia/Tokyo")

_LGBM_PARAMS = {
    "num_leaves": 31,
    "min_child_samples": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "verbose": -1,
}


class LGBMForecaster:
    MIN_TRAIN_ROWS = 90 * 24
    INTERVAL_VERSION = "q025_q50_q975_p95_v2_weather_delta"

    def __init__(
        self,
        n_estimators: int = 500,
        learning_rate: float = 0.05,
        config: dict | None = None,
    ) -> None:
        if not _HAS_LGBM:
            raise ImportError("lightgbm is required: pip install lightgbm")
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.config = config or {}
        self.interval_version = self.INTERVAL_VERSION
        self.model_q025: "LGBMRegressor | None" = None
        self.model_q50: "LGBMRegressor | None" = None
        self.model_q975: "LGBMRegressor | None" = None

    def _make_model(self, alpha: float) -> "LGBMRegressor":
        return LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            **_LGBM_PARAMS,
        )

    def fit(self, cache: pd.DataFrame) -> None:
        """Train q025/q50/q975 quantile models on hourly cache. Needs >= 90 days."""
        X, y = build_training_features(cache, self.config)
        if len(X) < self.MIN_TRAIN_ROWS:
            raise ValueError(
                f"LGBMForecaster.fit: need >= {self.MIN_TRAIN_ROWS} rows (90 days), "
                f"got {len(X)} after feature build."
            )
        for alpha, attr in [
            (0.025, "model_q025"),
            (0.50, "model_q50"),
            (0.975, "model_q975"),
        ]:
            m = self._make_model(alpha)
            m.fit(X, y)
            setattr(self, attr, m)
        self.interval_version = self.INTERVAL_VERSION

    def is_compatible(self) -> bool:
        """Return True when a loaded pickle has the current interval model layout."""
        return (
            getattr(self, "interval_version", None) == self.INTERVAL_VERSION
            and getattr(self, "model_q025", None) is not None
            and getattr(self, "model_q50", None) is not None
            and getattr(self, "model_q975", None) is not None
        )

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """Return 24-hour HourlyForecast list for target_date."""
        if not self.is_compatible():
            raise RuntimeError("Call fit() before predict(), or retrain an older LightGBM model.")
        X = build_inference_features(cache, target_date, getattr(self, "config", {}))
        q025 = self.model_q025.predict(X)
        q50 = self.model_q50.predict(X)
        q975 = self.model_q975.predict(X)

        result: list[HourlyForecast] = []
        for hour in range(24):
            ts = pd.Timestamp(
                year=target_date.year, month=target_date.month, day=target_date.day,
                hour=hour, tzinfo=JST,
            )
            mid = round(float(q50[hour]), 1)
            lo = round(min(float(q025[hour]), float(q975[hour]), mid), 1)
            hi = round(max(float(q025[hour]), float(q975[hour]), mid), 1)
            # p99 = 2x half-width beyond the q025/q975 interval as a conservative outer band.
            half_lo = max(0.0, mid - lo)
            half_hi = max(0.0, hi - mid)
            result.append(HourlyForecast(
                ts=ts.isoformat(timespec="seconds"),
                forecast_mw=mid,
                p95_lower_mw=lo,
                p95_upper_mw=hi,
                p99_lower_mw=round(lo - half_lo, 1),
                p99_upper_mw=round(hi + half_hi, 1),
            ))
        return result

    def save(self, path: Path) -> None:
        import joblib
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "LGBMForecaster":
        import joblib
        return joblib.load(path)
