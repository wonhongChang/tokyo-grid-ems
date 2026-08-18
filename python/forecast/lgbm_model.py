"""LightGBM quantile regression forecaster for hourly electricity demand."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from python.forecast.baseline import HourlyForecast
from python.forecast.feature_builder import (
    build_inference_features,
    build_training_features,
)
from python.forecast.interval_calibration import calibrate_p95_half_widths

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
    "random_state": 42,
    "verbose": -1,
}


class LGBMForecaster:
    MIN_TRAIN_ROWS = 90 * 24
    INTERVAL_VERSION = "q025_q50_q975_p95_v13_transition_cooling_blend"
    REGIME_Q50_INTERVAL_VERSIONS = {
        INTERVAL_VERSION,
        "q025_q50_q975_p95_v12_regime_q50",
    }
    LEGACY_INTERVAL_VERSIONS = {
        "q025_q50_q975_p95_v11_lag24_residual_ensemble",
        "q025_q50_q975_p95_v12_regime_q50",
    }

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
        self.model_q50_lag24_residual: "LGBMRegressor | None" = None
        self.model_q50_non_business: "LGBMRegressor | None" = None
        self.q50_non_business_feature_columns: list[str] | None = None
        self.training_window_days: int | None = None
        self.training_window_start: str | None = None

    def _make_model(self, alpha: float) -> "LGBMRegressor":
        forecast_config = (getattr(self, "config", {}) or {}).get("forecast", {})
        configured_params = forecast_config.get("lightgbm_params", {})
        allowed_params = {
            "num_leaves",
            "min_child_samples",
            "subsample",
            "subsample_freq",
            "colsample_bytree",
            "reg_alpha",
            "reg_lambda",
            "max_depth",
        }
        unknown = sorted(set(configured_params).difference(allowed_params))
        if unknown:
            raise ValueError(
                "forecast.lightgbm_params contains unsupported keys: "
                + ", ".join(unknown)
            )
        model_params = {**_LGBM_PARAMS, **configured_params}
        n_estimators = int(
            forecast_config.get("n_estimators", self.n_estimators)
        )
        learning_rate = float(
            forecast_config.get("learning_rate", self.learning_rate)
        )
        return LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            **model_params,
        )

    def _calibrate_interval_half_widths(
        self,
        half_lo: float,
        half_hi: float,
    ) -> tuple[float, float]:
        return calibrate_p95_half_widths(
            half_lo,
            half_hi,
            getattr(self, "config", {}) or {},
        )

    def _lag24_residual_ensemble_config(
        self,
    ) -> tuple[bool, bool, bool, float]:
        forecast_config = (getattr(self, "config", {}) or {}).get("forecast", {})
        ensemble_config = forecast_config.get("lag24_residual_ensemble", {})
        enabled = bool(ensemble_config.get("enabled", False))
        business_day_only = bool(ensemble_config.get("business_day_only", True))
        same_business_type_only = bool(
            ensemble_config.get("same_business_type_only", False)
        )
        weight = min(1.0, max(0.0, float(ensemble_config.get("weight", 0.5))))
        return enabled, business_day_only, same_business_type_only, weight

    def _q50_regime_config(
        self,
    ) -> tuple[bool, tuple[str, ...], int, float]:
        forecast_config = (getattr(self, "config", {}) or {}).get("forecast", {})
        regime_config = forecast_config.get("q50_regime_model", {})
        enabled = bool(regime_config.get("enabled", False))
        excluded_features = tuple(
            str(feature)
            for feature in regime_config.get("excluded_features", [])
        )
        min_non_business_rows = max(
            int(regime_config.get("min_non_business_training_rows", 14 * 24)),
            1,
        )
        weight = min(1.0, max(0.0, float(regime_config.get("weight", 0.5))))
        return enabled, excluded_features, min_non_business_rows, weight

    def _transition_cooling_attenuation_config(
        self,
    ) -> tuple[bool, float, float]:
        forecast_config = (getattr(self, "config", {}) or {}).get("forecast", {})
        ensemble_config = forecast_config.get("lag24_residual_ensemble", {})
        attenuation_config = ensemble_config.get(
            "transition_cooling_attenuation",
            {},
        )
        enabled = bool(attenuation_config.get("enabled", False))
        zero_weight_delta_c = float(
            attenuation_config.get("zero_weight_delta_c", -4.0)
        )
        full_weight_delta_c = float(
            attenuation_config.get("full_weight_delta_c", 0.0)
        )
        if (
            not np.isfinite(zero_weight_delta_c)
            or not np.isfinite(full_weight_delta_c)
            or full_weight_delta_c <= zero_weight_delta_c
        ):
            enabled = False
        return enabled, zero_weight_delta_c, full_weight_delta_c

    def _lag24_residual_weights(
        self,
        features: pd.DataFrame,
        configured_weight: float,
    ) -> np.ndarray:
        """Return row-level residual blend weights for the current model contract."""
        weights = np.full(len(features), configured_weight, dtype=float)
        attenuation_enabled, zero_delta, full_delta = (
            self._transition_cooling_attenuation_config()
        )
        if (
            getattr(self, "interval_version", None) != self.INTERVAL_VERSION
            or not attenuation_enabled
            or "lag_24h_business_type_mismatch" not in features.columns
            or "cooling_delta_24h" not in features.columns
        ):
            return weights

        mismatch = (
            features["lag_24h_business_type_mismatch"].to_numpy(dtype=float) > 0.0
        )
        business_day = (
            features["is_non_business_day"].to_numpy(dtype=float) == 0.0
            if "is_non_business_day" in features.columns
            else np.ones(len(features), dtype=bool)
        )
        cooling_delta = features["cooling_delta_24h"].to_numpy(dtype=float)
        transition_rows = mismatch & business_day & np.isfinite(cooling_delta)
        attenuation = np.clip(
            (cooling_delta - zero_delta) / (full_delta - zero_delta),
            0.0,
            1.0,
        )
        weights[transition_rows] *= attenuation[transition_rows]
        return weights

    def _non_business_q50_inputs(
        self,
        features: pd.DataFrame,
    ) -> pd.DataFrame:
        columns = getattr(self, "q50_non_business_feature_columns", None)
        if not columns:
            raise RuntimeError(
                "LightGBM non-business q50 feature contract is missing."
            )
        missing = [column for column in columns if column not in features.columns]
        if missing:
            raise RuntimeError(
                "LightGBM non-business q50 feature contract is incomplete: "
                + ", ".join(missing)
            )
        return features[columns]

    def fit(self, cache: pd.DataFrame) -> None:
        """Train interval, q50, residual, and non-business regime models."""
        forecast_config = (getattr(self, "config", {}) or {}).get("forecast", {})
        configured_window = forecast_config.get("training_window_days")
        training_start = None
        self.training_window_days = None
        self.training_window_start = None
        if configured_window is not None:
            window_days = int(configured_window)
            if window_days < 90:
                raise ValueError(
                    "forecast.training_window_days must be at least 90 days."
                )
            observed_mask = cache["actual_mw"].notna()
            if "actual_source" in cache.columns:
                observed_mask &= (
                    cache["actual_source"].fillna("observed")
                    != "tepco_forecast_fallback"
                )
            observed_ts = pd.to_datetime(
                cache.loc[observed_mask, "ts"],
                utc=True,
            ).dt.tz_convert(JST)
            if observed_ts.empty:
                raise ValueError(
                    "LGBMForecaster.fit: no observed timestamp for training window."
                )
            training_start = observed_ts.max() - pd.Timedelta(days=window_days)
            self.training_window_days = window_days
            self.training_window_start = training_start.isoformat()

        X, y = build_training_features(
            cache,
            self.config,
            start_ts=training_start,
        )
        if len(X) < self.MIN_TRAIN_ROWS:
            raise ValueError(
                f"LGBMForecaster.fit: need >= {self.MIN_TRAIN_ROWS} rows (90 days), "
                f"got {len(X)} after feature build."
            )

        regime_enabled, excluded_features, min_non_business_rows, _ = (
            self._q50_regime_config()
        )
        for alpha, attr in [
            (0.025, "model_q025"),
            (0.975, "model_q975"),
        ]:
            m = self._make_model(alpha)
            m.fit(X, y)
            setattr(self, attr, m)

        q50_model = self._make_model(0.50)
        q50_model.fit(X, y)
        self.model_q50 = q50_model

        residual_model = self._make_model(0.50)
        residual_model.fit(X, y - X["lag_24h"])
        self.model_q50_lag24_residual = residual_model

        self.model_q50_non_business = None
        self.q50_non_business_feature_columns = None
        if regime_enabled:
            excluded = set(excluded_features)
            unknown_exclusions = sorted(excluded.difference(X.columns))
            if unknown_exclusions:
                raise ValueError(
                    "LGBMForecaster.fit: unknown non-business q50 exclusions: "
                    + ", ".join(unknown_exclusions)
                )
            self.q50_non_business_feature_columns = [
                column for column in X.columns if column not in excluded
            ]
            if not self.q50_non_business_feature_columns:
                raise ValueError(
                    "LGBMForecaster.fit: non-business q50 feature set is empty."
                )
            non_business_mask = X["is_non_business_day"] == 1
            non_business_rows = int(non_business_mask.sum())
            if non_business_rows < min_non_business_rows:
                raise ValueError(
                    "LGBMForecaster.fit: need >= "
                    f"{min_non_business_rows} non-business rows, "
                    f"got {non_business_rows}."
                )
            non_business_model = self._make_model(0.50)
            non_business_model.fit(
                X.loc[
                    non_business_mask,
                    self.q50_non_business_feature_columns,
                ],
                y.loc[non_business_mask],
            )
            self.model_q50_non_business = non_business_model

        self.interval_version = self.INTERVAL_VERSION

    def is_compatible(self) -> bool:
        """Return True when a loaded pickle has the current interval model layout."""
        interval_version = getattr(self, "interval_version", None)
        compatible = (
            interval_version
            in {self.INTERVAL_VERSION, *self.LEGACY_INTERVAL_VERSIONS}
            and getattr(self, "model_q025", None) is not None
            and getattr(self, "model_q50", None) is not None
            and getattr(self, "model_q975", None) is not None
        )
        enabled, _, _, _ = self._lag24_residual_ensemble_config()
        if not compatible or (
            enabled and getattr(self, "model_q50_lag24_residual", None) is None
        ):
            return False

        regime_enabled, _, _, _ = self._q50_regime_config()
        if interval_version in self.REGIME_Q50_INTERVAL_VERSIONS and regime_enabled:
            return (
                bool(
                    getattr(
                        self,
                        "q50_non_business_feature_columns",
                        None,
                    )
                )
                and getattr(self, "model_q50_non_business", None) is not None
            )
        return True

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """Return 24-hour HourlyForecast list for target_date."""
        if not self.is_compatible():
            raise RuntimeError("Call fit() before predict(), or retrain an older LightGBM model.")
        X = build_inference_features(cache, target_date, getattr(self, "config", {}))
        q025 = self.model_q025.predict(X)
        q50_base = self.model_q50.predict(X)
        q975 = self.model_q975.predict(X)

        q50 = np.asarray(q50_base, dtype=float).copy()
        non_business_q50 = None
        regime_enabled, _, _, regime_weight = self._q50_regime_config()
        regime_active = (
            getattr(self, "interval_version", None)
            in self.REGIME_Q50_INTERVAL_VERSIONS
            and regime_enabled
        )
        if regime_active:
            non_business_mask = (
                X["is_non_business_day"].to_numpy(dtype=float) == 1.0
            )
            non_business_q50 = np.asarray(
                self.model_q50_non_business.predict(
                    self._non_business_q50_inputs(X)
                ),
                dtype=float,
            )
            blended_non_business_q50 = (
                (1.0 - regime_weight) * q50
                + regime_weight * non_business_q50
            )
            q50 = np.where(
                non_business_mask,
                blended_non_business_q50,
                q50,
            )

        enabled, business_day_only, same_business_type_only, weight = (
            self._lag24_residual_ensemble_config()
        )
        if enabled:
            residual_q50 = np.asarray(
                self.model_q50_lag24_residual.predict(X),
                dtype=float,
            )
            lag24 = X["lag_24h"].to_numpy(dtype=float)
            lag24_q50 = lag24 + residual_q50
            blend_weights = self._lag24_residual_weights(X, weight)
            blended_q50 = (
                (1.0 - blend_weights) * q50
                + blend_weights * lag24_q50
            )
            blend_available = (
                np.isfinite(lag24)
                & np.isfinite(residual_q50)
                & np.isfinite(blended_q50)
            )
            if business_day_only:
                business_mask = X["is_non_business_day"].to_numpy(dtype=float) == 0.0
                blend_available &= business_mask
            if same_business_type_only:
                same_business_type_mask = (
                    X["lag_24h_business_type_mismatch"].to_numpy(dtype=float)
                    == 0.0
                )
                blend_available &= same_business_type_mask
            q50 = np.where(blend_available, blended_q50, q50)

        forecast_arrays = {
            "q025": np.asarray(q025, dtype=float),
            "q50_base": np.asarray(q50_base, dtype=float),
            "q50": np.asarray(q50, dtype=float),
            "q975": np.asarray(q975, dtype=float),
        }
        if non_business_q50 is not None:
            forecast_arrays["q50_non_business"] = non_business_q50
        invalid = [
            name
            for name, values in forecast_arrays.items()
            if len(values) != 24 or not np.isfinite(values).all()
        ]
        if invalid:
            raise RuntimeError(
                "LightGBM produced incomplete or non-finite forecasts: "
                + ", ".join(invalid)
            )

        result: list[HourlyForecast] = []
        for hour in range(24):
            ts = pd.Timestamp(
                year=target_date.year, month=target_date.month, day=target_date.day,
                hour=hour, tzinfo=JST,
            )
            base_mid = round(float(q50_base[hour]), 1)
            mid = round(float(q50[hour]), 1)
            lo = round(min(float(q025[hour]), float(q975[hour]), base_mid), 1)
            hi = round(max(float(q025[hour]), float(q975[hour]), base_mid), 1)
            # p99 = 2x half-width beyond the q025/q975 interval as a conservative outer band.
            half_lo = max(0.0, base_mid - lo)
            half_hi = max(0.0, hi - base_mid)
            half_lo, half_hi = self._calibrate_interval_half_widths(half_lo, half_hi)
            lo = round(mid - half_lo, 1)
            hi = round(mid + half_hi, 1)
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
