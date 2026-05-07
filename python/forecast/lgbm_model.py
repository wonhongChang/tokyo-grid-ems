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

    def __init__(self, n_estimators: int = 500, learning_rate: float = 0.05) -> None:
        if not _HAS_LGBM:
            raise ImportError("lightgbm is required: pip install lightgbm")
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.model_q10: "LGBMRegressor | None" = None
        self.model_q50: "LGBMRegressor | None" = None
        self.model_q90: "LGBMRegressor | None" = None

    def _make_model(self, alpha: float) -> "LGBMRegressor":
        return LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            **_LGBM_PARAMS,
        )

    def fit(self, cache: pd.DataFrame) -> None:
        """Train q10/q50/q90 quantile models on hourly cache. Needs >= 90 days."""
        X, y = build_training_features(cache)
        if len(X) < self.MIN_TRAIN_ROWS:
            raise ValueError(
                f"LGBMForecaster.fit: need >= {self.MIN_TRAIN_ROWS} rows (90 days), "
                f"got {len(X)} after feature build."
            )
        for alpha, attr in [
            (0.10, "model_q10"),
            (0.50, "model_q50"),
            (0.90, "model_q90"),
        ]:
            m = self._make_model(alpha)
            m.fit(X, y)
            setattr(self, attr, m)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """Return 24-hour HourlyForecast list for target_date."""
        if self.model_q50 is None:
            raise RuntimeError("Call fit() before predict().")
        X = build_inference_features(cache, target_date)
        q10 = self.model_q10.predict(X)
        q50 = self.model_q50.predict(X)
        q90 = self.model_q90.predict(X)

        result: list[HourlyForecast] = []
        for hour in range(24):
            ts = pd.Timestamp(
                year=target_date.year, month=target_date.month, day=target_date.day,
                hour=hour, tzinfo=JST,
            )
            lo  = round(float(q10[hour]), 1)
            mid = round(float(q50[hour]), 1)
            hi  = round(float(q90[hour]), 1)
            # p99 = 2× half-width beyond q10/q90, approximating 99th pct interval
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
