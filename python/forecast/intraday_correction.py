"""Intraday residual correction for the remaining hours of today's forecast."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from python.forecast.baseline import HourlyForecast


@dataclass(frozen=True)
class IntradayCorrectionResult:
    forecasts: list[HourlyForecast]
    applied: bool
    observed_hours: int
    last_observed_hour: int | None
    base_adjustment_mw: float


class IntradayResidualCorrector:
    """Adjust future same-day forecasts using recent actual-minus-model residuals."""

    def __init__(self, config: dict) -> None:
        correction_config = config.get("intraday_correction", {})
        self._enabled = bool(correction_config.get("enabled", True))
        self._lookback_hours = int(correction_config.get("lookback_hours", 3))
        self._min_observed_hours = int(correction_config.get("min_observed_hours", 3))
        self._shrinkage = float(correction_config.get("shrinkage", 0.6))
        self._max_abs_adjustment_mw = float(correction_config.get("max_abs_adjustment_mw", 1200.0))
        self._decay_per_hour = float(correction_config.get("decay_per_hour", 0.92))

    def apply(
        self,
        forecasts: list[HourlyForecast],
        actual_series: list[dict],
    ) -> IntradayCorrectionResult:
        if not self._enabled or not forecasts:
            return IntradayCorrectionResult(forecasts, False, 0, None, 0.0)

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        residuals_by_hour: list[tuple[int, float]] = []

        for point in actual_series:
            actual_mw = point.get("actualMw")
            if actual_mw is None or not point.get("ts"):
                continue
            hour = pd.Timestamp(point["ts"]).hour
            forecast = forecast_by_hour.get(hour)
            if forecast is None:
                continue
            residuals_by_hour.append((hour, float(actual_mw) - float(forecast.forecast_mw)))

        residuals_by_hour.sort(key=lambda item: item[0])
        recent_residuals = residuals_by_hour[-self._lookback_hours:]
        if len(recent_residuals) < self._min_observed_hours:
            return IntradayCorrectionResult(
                forecasts,
                False,
                len(residuals_by_hour),
                residuals_by_hour[-1][0] if residuals_by_hour else None,
                0.0,
            )

        last_observed_hour = recent_residuals[-1][0]
        max_forecast_hour = max(forecast_by_hour)
        if last_observed_hour >= max_forecast_hour:
            return IntradayCorrectionResult(
                forecasts,
                False,
                len(residuals_by_hour),
                last_observed_hour,
                0.0,
            )

        base_adjustment_mw = float(np.mean([residual for _, residual in recent_residuals]))
        base_adjustment_mw *= self._shrinkage
        base_adjustment_mw = float(np.clip(
            base_adjustment_mw,
            -self._max_abs_adjustment_mw,
            self._max_abs_adjustment_mw,
        ))

        adjusted_forecasts: list[HourlyForecast] = []
        for forecast in forecasts:
            forecast_hour = pd.Timestamp(forecast.ts).hour
            if forecast_hour <= last_observed_hour:
                adjusted_forecasts.append(forecast)
                continue

            lead_hours = forecast_hour - last_observed_hour
            decayed_adjustment_mw = round(
                base_adjustment_mw * (self._decay_per_hour ** (lead_hours - 1)),
                1,
            )
            adjusted_forecasts.append(HourlyForecast(
                ts=forecast.ts,
                forecast_mw=round(forecast.forecast_mw + decayed_adjustment_mw, 1),
                p95_lower_mw=round(forecast.p95_lower_mw + decayed_adjustment_mw, 1),
                p95_upper_mw=round(forecast.p95_upper_mw + decayed_adjustment_mw, 1),
                p99_lower_mw=round(forecast.p99_lower_mw + decayed_adjustment_mw, 1),
                p99_upper_mw=round(forecast.p99_upper_mw + decayed_adjustment_mw, 1),
            ))

        return IntradayCorrectionResult(
            adjusted_forecasts,
            True,
            len(residuals_by_hour),
            last_observed_hour,
            round(base_adjustment_mw, 1),
        )
