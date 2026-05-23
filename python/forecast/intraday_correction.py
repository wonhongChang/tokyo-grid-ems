"""Intraday residual correction for the remaining hours of today's forecast."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from python.forecast.baseline import HourlyForecast

_TEPCO_FORECAST_FALLBACK_SOURCE = "tepco_forecast_fallback"


@dataclass(frozen=True)
class IntradayCorrectionResult:
    forecasts: list[HourlyForecast]
    applied: bool
    observed_hours: int
    last_observed_hour: int | None
    base_adjustment_mw: float
    ramp_guard_applied: bool = False
    negative_adjustment_damped: bool = False
    shape_guard_applied: bool = False
    observed_drop_relaxation_active: bool = False
    midday_residual_deweighted: bool = False
    fallback_residuals_ignored: int = 0
    carryover_adjustment_mw: float = 0.0
    carryover_source_hour: int | None = None
    applied_day_bias_mw: float = 0.0
    business_type_transition_prior_bias_mw: float = 0.0
    business_type_transition_prior_applied: bool = False
    business_type_transition_bias_mw: float = 0.0
    business_type_transition_applied: bool = False
    source_confidence: dict | None = None
    applied_regime_reason: tuple[str, ...] = ()
    positive_residual_mitigation_applied: bool = False
    positive_residual_mitigation_max_mw: float = 0.0

    def metadata(self) -> dict:
        return {
            "applied": self.applied,
            "observedHours": self.observed_hours,
            "lastObservedHour": self.last_observed_hour,
            "baseAdjustmentMw": round(float(self.base_adjustment_mw), 1),
            "fallbackResidualsIgnored": self.fallback_residuals_ignored,
            "carryoverAdjustmentMw": round(float(self.carryover_adjustment_mw), 1),
            "carryoverSourceHour": self.carryover_source_hour,
            "appliedDayBiasMw": round(float(self.applied_day_bias_mw), 1),
            "businessTypeTransitionPriorBiasMw": round(
                float(self.business_type_transition_prior_bias_mw),
                1,
            ),
            "businessTypeTransitionPriorApplied": (
                self.business_type_transition_prior_applied
            ),
            "businessTypeTransitionBiasMw": round(
                float(self.business_type_transition_bias_mw),
                1,
            ),
            "businessTypeTransitionApplied": self.business_type_transition_applied,
            "positiveResidualMitigationApplied": (
                self.positive_residual_mitigation_applied
            ),
            "positiveResidualMitigationMaxMw": round(
                float(self.positive_residual_mitigation_max_mw),
                1,
            ),
            "sourceConfidence": self.source_confidence or {},
            "appliedRegimeReason": list(self.applied_regime_reason),
        }


@dataclass(frozen=True)
class _ResidualPoint:
    hour: int
    residual_mw: float
    weight: float
    ts: pd.Timestamp


def _is_nonworking_day(ts: pd.Timestamp) -> bool:
    try:
        import jpholiday
        return ts.weekday() >= 5 or bool(jpholiday.is_holiday(ts.date()))
    except ImportError:
        return ts.weekday() >= 5


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
        calibration_config = correction_config.get("operational_calibration", {})
        carry_config = calibration_config.get("day_boundary_carryover", {})
        self._carryover_enabled = bool(carry_config.get("enabled", True))
        self._carryover_decay_per_hour = float(carry_config.get("decay_per_hour", 0.75))
        self._carryover_shrinkage = float(carry_config.get("shrinkage", 0.5))
        self._carryover_max_age_hours = float(carry_config.get("max_age_hours", 8.0))
        self._carryover_max_abs_adjustment_mw = float(
            carry_config.get("max_abs_adjustment_mw", 500.0)
        )
        scale_config = calibration_config.get("day_level_scale", {})
        self._day_scale_enabled = bool(scale_config.get("enabled", True))
        self._day_scale_lag_overheat_threshold_mw = float(
            scale_config.get("lag_overheat_threshold_mw", 600.0)
        )
        self._day_scale_temp_drop_threshold_c = float(
            scale_config.get("temp_drop_threshold_c", 1.5)
        )
        self._day_scale_lag_weight = float(scale_config.get("lag_overheat_weight", 0.25))
        self._day_scale_max_abs_bias_mw = float(scale_config.get("max_abs_bias_mw", 700.0))
        self._day_scale_observed_fade_hours = max(
            int(scale_config.get("observed_fade_hours", self._min_observed_hours)),
            1,
        )
        self._day_scale_max_heating_degree = float(
            scale_config.get("max_heating_degree", 7.0)
        )
        transition_prior_config = calibration_config.get(
            "business_type_transition_prior",
            {},
        )
        self._transition_prior_enabled = bool(
            transition_prior_config.get("enabled", True)
        )
        self._transition_prior_target_non_business_only = bool(
            transition_prior_config.get("target_non_business_only", True)
        )
        self._transition_prior_force_off_hour = int(
            transition_prior_config.get("force_off_hour", 6)
        )
        self._transition_prior_lag_overheat_threshold_mw = float(
            transition_prior_config.get("lag_overheat_threshold_mw", 1_500.0)
        )
        self._transition_prior_base_allowed_excess_mw = float(
            transition_prior_config.get("base_allowed_excess_mw", 900.0)
        )
        self._transition_prior_shrinkage = float(
            transition_prior_config.get("shrinkage", 0.25)
        )
        self._transition_prior_max_abs_bias_mw = float(
            transition_prior_config.get("max_abs_bias_mw", 500.0)
        )
        positive_mitigation_config = transition_prior_config.get(
            "positive_residual_mitigation",
            {},
        )
        self._transition_positive_mitigation_enabled = bool(
            positive_mitigation_config.get("enabled", True)
        )
        self._transition_positive_mitigation_hours = {
            int(hour)
            for hour in positive_mitigation_config.get(
                "hours",
                [6, 7, 8, 9, 10, 11],
            )
        }
        self._transition_positive_mitigation_multiplier = min(
            max(float(positive_mitigation_config.get("multiplier", 0.0)), 0.0),
            1.0,
        )
        transition_config = calibration_config.get("business_type_transition", {})
        self._transition_enabled = bool(transition_config.get("enabled", True))
        self._transition_target_non_business_only = bool(
            transition_config.get("target_non_business_only", True)
        )
        self._transition_min_observed_hour = int(
            transition_config.get("min_observed_hour", 6)
        )
        self._transition_max_recent_residual_mw = float(
            transition_config.get("max_recent_residual_mw", -300.0)
        )
        self._transition_lag_overheat_threshold_mw = float(
            transition_config.get("lag_overheat_threshold_mw", 1_500.0)
        )
        self._transition_base_allowed_excess_mw = float(
            transition_config.get("base_allowed_excess_mw", 900.0)
        )
        self._transition_temp_anomaly_allowance_mw_per_c = float(
            transition_config.get("temp_anomaly_allowance_mw_per_c", 120.0)
        )
        self._transition_cooling_allowance_mw_per_c = float(
            transition_config.get("cooling_allowance_mw_per_c", 160.0)
        )
        self._transition_max_weather_allowance_mw = float(
            transition_config.get("max_weather_allowance_mw", 900.0)
        )
        self._transition_shrinkage = float(
            transition_config.get("shrinkage", 0.55)
        )
        self._transition_max_abs_bias_mw = float(
            transition_config.get("max_abs_bias_mw", 1_200.0)
        )
        negative_damping_config = correction_config.get("negative_residual_damping", {})
        self._negative_damping_enabled = bool(negative_damping_config.get("enabled", False))
        self._negative_damping_min_reference_hour = int(
            negative_damping_config.get("min_reference_hour", 12)
        )
        negative_damping_multiplier = float(negative_damping_config.get("multiplier", 1.0))
        self._negative_damping_multiplier = min(max(negative_damping_multiplier, 0.0), 1.0)
        midday_deweight_config = correction_config.get("midday_residual_deweight", {})
        self._midday_deweight_enabled = bool(
            midday_deweight_config.get("enabled", True)
        )
        self._midday_deweight_hours = {
            int(hour) for hour in midday_deweight_config.get("hours", [12])
        }
        self._midday_deweight_weight = min(
            max(float(midday_deweight_config.get("weight", 0.25)), 0.0),
            1.0,
        )
        self._midday_deweight_min_abs_residual_mw = float(
            midday_deweight_config.get("min_abs_residual_mw", 600.0)
        )
        shape_guard_config = correction_config.get("shape_guard", {})
        self._shape_guard_enabled = bool(shape_guard_config.get("enabled", False))
        self._shape_guard_min_reference_hour = int(
            shape_guard_config.get("min_reference_hour", 12)
        )
        self._shape_guard_hours = {
            int(hour) for hour in shape_guard_config.get("hours", [15, 16, 17, 18, 19])
        }
        self._shape_guard_max_drop_mw = float(shape_guard_config.get("max_drop_mw", 1000.0))
        ramp_guard_config = correction_config.get("ramp_guard", {})
        self._ramp_guard_enabled = bool(ramp_guard_config.get("enabled", False))
        self._ramp_guard_min_reference_hour = int(ramp_guard_config.get("min_reference_hour", 10))
        self._ramp_guard_max_lead_hours = int(ramp_guard_config.get("max_lead_hours", 3))
        caps = ramp_guard_config.get("max_increase_mw_by_lead_hour", [1200, 1500, 2000])
        self._ramp_guard_increase_caps = [
            float(value) for value in caps
        ] or [1200.0, 1500.0, 2000.0]
        decrease_caps = ramp_guard_config.get("max_decrease_mw_by_lead_hour", [1000, 1800, 2400])
        self._ramp_guard_decrease_caps = [
            float(value) for value in decrease_caps
        ] or [1000.0, 1800.0, 2400.0]
        observed_drop_config = ramp_guard_config.get("observed_drop_relaxation", {})
        self._observed_drop_relaxation_enabled = bool(
            observed_drop_config.get("enabled", False)
        )
        self._observed_drop_threshold_mw = float(
            observed_drop_config.get("min_recent_drop_mw", 700.0)
        )
        self._observed_drop_lookback_hours = int(
            observed_drop_config.get("lookback_hours", 2)
        )
        self._observed_drop_skip_shape_guard = bool(
            observed_drop_config.get("skip_shape_guard", True)
        )
        observed_drop_caps = observed_drop_config.get(
            "max_decrease_mw_by_lead_hour",
            [2000, 3600, 5000],
        )
        self._observed_drop_decrease_caps = [
            float(value) for value in observed_drop_caps
        ] or [2000.0, 3600.0, 5000.0]

    def _ramp_guard_cap_for_lead(self, lead_hours: int) -> float:
        cap_index = min(max(lead_hours, 1), len(self._ramp_guard_increase_caps)) - 1
        return self._ramp_guard_increase_caps[cap_index]

    def _ramp_guard_drop_cap_for_lead(
        self,
        lead_hours: int,
        observed_drop_relaxation_active: bool,
    ) -> float:
        caps = self._ramp_guard_decrease_caps
        if observed_drop_relaxation_active:
            caps = self._observed_drop_decrease_caps
        cap_index = min(max(lead_hours, 1), len(caps)) - 1
        return caps[cap_index]

    def _is_observed_drop_relaxation_active(
        self,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
    ) -> bool:
        if (
            not self._observed_drop_relaxation_enabled
            or last_observed_hour is None
            or self._observed_drop_threshold_mw <= 0.0
        ):
            return False

        for offset in range(self._observed_drop_lookback_hours):
            hour = last_observed_hour - offset
            previous_hour = hour - 1
            if hour not in actual_mw_by_hour or previous_hour not in actual_mw_by_hour:
                continue
            observed_drop_mw = actual_mw_by_hour[previous_hour] - actual_mw_by_hour[hour]
            if observed_drop_mw >= self._observed_drop_threshold_mw:
                return True
        return False

    def _residual_weight(self, forecast_ts: pd.Timestamp, residual_mw: float) -> float:
        if (
            not self._midday_deweight_enabled
            or forecast_ts.hour not in self._midday_deweight_hours
            or _is_nonworking_day(forecast_ts)
            or abs(residual_mw) < self._midday_deweight_min_abs_residual_mw
        ):
            return 1.0
        return self._midday_deweight_weight

    @staticmethod
    def _is_observed_point(point: dict) -> bool:
        return (
            point.get("actualMw") is not None
            and point.get("actualSource") != _TEPCO_FORECAST_FALLBACK_SOURCE
        )

    @staticmethod
    def _source_confidence(
        actual_series: list[dict],
        usable_observed_hours: int,
        fallback_residuals_ignored: int,
    ) -> dict:
        actual_hours = sum(1 for point in actual_series if point.get("actualMw") is not None)
        missing_hours = sum(1 for point in actual_series if point.get("actualMw") is None)
        if usable_observed_hours >= 3:
            level = "observed"
        elif usable_observed_hours > 0:
            level = "partial_observed"
        elif fallback_residuals_ignored > 0:
            level = "fallback_only"
        else:
            level = "none"
        return {
            "level": level,
            "actualHours": actual_hours,
            "usableObservedHours": usable_observed_hours,
            "fallbackIgnoredHours": fallback_residuals_ignored,
            "missingHours": missing_hours,
        }

    @staticmethod
    def _shift_forecast(forecast: HourlyForecast, shift_mw: float) -> HourlyForecast:
        return HourlyForecast(
            ts=forecast.ts,
            forecast_mw=round(forecast.forecast_mw + shift_mw, 1),
            p95_lower_mw=round(forecast.p95_lower_mw + shift_mw, 1),
            p95_upper_mw=round(forecast.p95_upper_mw + shift_mw, 1),
            p99_lower_mw=round(forecast.p99_lower_mw + shift_mw, 1),
            p99_upper_mw=round(forecast.p99_upper_mw + shift_mw, 1),
        )

    def _latest_previous_observed_residual(
        self,
        previous_actual_series: list[dict],
        previous_forecasts: list[HourlyForecast],
        first_forecast_ts: pd.Timestamp,
    ) -> tuple[float, int, float] | None:
        if (
            not self._carryover_enabled
            or not previous_actual_series
            or not previous_forecasts
            or self._carryover_max_age_hours <= 0
        ):
            return None

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in previous_forecasts
        }
        candidates: list[tuple[pd.Timestamp, int, float]] = []
        for point in previous_actual_series:
            if not self._is_observed_point(point) or not point.get("ts"):
                continue
            point_ts = pd.Timestamp(point["ts"])
            forecast = forecast_by_hour.get(point_ts.hour)
            if forecast is None:
                continue
            residual = float(point["actualMw"]) - float(forecast.forecast_mw)
            candidates.append((point_ts, point_ts.hour, residual))
        if not candidates:
            return None

        point_ts, hour, residual_mw = max(candidates, key=lambda item: item[0])
        age_hours = (first_forecast_ts - point_ts).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > self._carryover_max_age_hours:
            return None
        decayed_adjustment = (
            residual_mw
            * self._carryover_shrinkage
            * (self._carryover_decay_per_hour ** age_hours)
        )
        decayed_adjustment = float(np.clip(
            decayed_adjustment,
            -self._carryover_max_abs_adjustment_mw,
            self._carryover_max_abs_adjustment_mw,
        ))
        return decayed_adjustment, hour, age_hours

    def _day_level_bias_by_hour(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        usable_observed_hours: int,
    ) -> dict[int, float]:
        if (
            not self._day_scale_enabled
            or inference_features is None
            or inference_features.empty
            or usable_observed_hours >= self._day_scale_observed_fade_hours
        ):
            return {}

        fade = max(
            0.0,
            1.0 - (usable_observed_hours / self._day_scale_observed_fade_hours),
        )
        if fade <= 0.0:
            return {}

        forecast_hours = {pd.Timestamp(forecast.ts).hour for forecast in forecasts}
        biases: dict[int, float] = {}
        for _, row in inference_features.iterrows():
            try:
                hour = int(row["hour"])
            except Exception:
                continue
            if hour not in forecast_hours:
                continue
            lag_24h = row.get("lag_24h")
            recent_mean = row.get("recent_same_business_type_mean")
            temp_delta_24h = row.get("temp_delta_24h")
            heating_degree = row.get("heating_degree")
            if (
                pd.isna(lag_24h)
                or pd.isna(recent_mean)
                or pd.isna(temp_delta_24h)
            ):
                continue

            lag_overheat_mw = float(lag_24h) - float(recent_mean)
            temp_drop_c = -float(temp_delta_24h)
            heating_degree_value = (
                float(heating_degree)
                if heating_degree is not None and not pd.isna(heating_degree)
                else 0.0
            )
            if (
                lag_overheat_mw <= self._day_scale_lag_overheat_threshold_mw
                or temp_drop_c <= self._day_scale_temp_drop_threshold_c
                or heating_degree_value > self._day_scale_max_heating_degree
            ):
                continue

            overheat_excess = lag_overheat_mw - self._day_scale_lag_overheat_threshold_mw
            temp_drop_factor = min(1.0, temp_drop_c / 5.0)
            bias = -overheat_excess * self._day_scale_lag_weight * temp_drop_factor * fade
            biases[hour] = float(np.clip(
                bias,
                -self._day_scale_max_abs_bias_mw,
                self._day_scale_max_abs_bias_mw,
            ))
        return biases

    def _apply_hourly_bias(
        self,
        forecasts: list[HourlyForecast],
        bias_by_hour: dict[int, float],
        last_observed_hour: int | None,
    ) -> tuple[list[HourlyForecast], float]:
        if not bias_by_hour:
            return forecasts, 0.0

        result: list[HourlyForecast] = []
        applied_values: list[float] = []
        for forecast in forecasts:
            forecast_hour = pd.Timestamp(forecast.ts).hour
            if last_observed_hour is not None and forecast_hour <= last_observed_hour:
                result.append(forecast)
                continue
            bias_mw = round(float(bias_by_hour.get(forecast_hour, 0.0)), 1)
            if bias_mw == 0.0:
                result.append(forecast)
                continue
            result.append(self._shift_forecast(forecast, bias_mw))
            applied_values.append(bias_mw)
        if not applied_values:
            return result, 0.0
        return result, float(np.mean(applied_values))

    @staticmethod
    def _finite_float(value) -> float | None:
        if value is None or pd.isna(value):
            return None
        parsed = float(value)
        if not np.isfinite(parsed):
            return None
        return parsed

    def _business_type_transition_bias_by_hour(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        last_observed_hour: int | None,
        recent_residuals: list[_ResidualPoint],
    ) -> dict[int, float]:
        if (
            not self._transition_enabled
            or inference_features is None
            or inference_features.empty
            or last_observed_hour is None
            or last_observed_hour < self._transition_min_observed_hour
            or not recent_residuals
        ):
            return {}

        recent_residual_mean = float(
            np.mean([point.residual_mw for point in recent_residuals])
        )
        if recent_residual_mean > self._transition_max_recent_residual_mw:
            return {}

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        biases: dict[int, float] = {}
        for _, row in inference_features.iterrows():
            hour = int(row.get("hour", -1))
            forecast = forecast_by_hour.get(hour)
            if forecast is None or hour <= last_observed_hour:
                continue

            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if mismatch is None or mismatch <= 0:
                continue
            if (
                self._transition_target_non_business_only
                and is_non_business_day != 1.0
            ):
                continue

            lag_24h = self._finite_float(row.get("lag_24h"))
            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
            if lag_24h is None or recent_mean is None:
                continue

            lag_overheat_mw = lag_24h - recent_mean
            if lag_overheat_mw <= self._transition_lag_overheat_threshold_mw:
                continue

            temp_anomaly_7d = max(
                0.0,
                self._finite_float(row.get("temp_anomaly_7d")) or 0.0,
            )
            cooling_degree = max(
                0.0,
                self._finite_float(row.get("cooling_degree")) or 0.0,
            )
            weather_allowance = min(
                self._transition_max_weather_allowance_mw,
                temp_anomaly_7d * self._transition_temp_anomaly_allowance_mw_per_c
                + cooling_degree * self._transition_cooling_allowance_mw_per_c,
            )
            allowed_forecast_mw = (
                recent_mean
                + self._transition_base_allowed_excess_mw
                + weather_allowance
            )
            excess_mw = forecast.forecast_mw - allowed_forecast_mw
            if excess_mw <= 0.0:
                continue

            bias = -min(
                self._transition_max_abs_bias_mw,
                excess_mw * self._transition_shrinkage,
            )
            if bias != 0.0:
                biases[hour] = round(float(bias), 1)

        return biases

    def _business_type_transition_prior_bias_by_hour(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        last_observed_hour: int | None,
    ) -> dict[int, float]:
        if (
            not self._transition_prior_enabled
            or inference_features is None
            or inference_features.empty
        ):
            return {}
        if (
            last_observed_hour is not None
            and last_observed_hour >= self._transition_prior_force_off_hour
        ):
            return {}

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        biases: dict[int, float] = {}
        for _, row in inference_features.iterrows():
            hour = int(row.get("hour", -1))
            forecast = forecast_by_hour.get(hour)
            if forecast is None:
                continue
            if last_observed_hour is not None and hour <= last_observed_hour:
                continue

            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if mismatch is None or mismatch <= 0:
                continue
            if (
                self._transition_prior_target_non_business_only
                and is_non_business_day != 1.0
            ):
                continue

            lag_24h = self._finite_float(row.get("lag_24h"))
            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
            if lag_24h is None or recent_mean is None:
                continue
            lag_overheat_mw = lag_24h - recent_mean
            if lag_overheat_mw <= self._transition_prior_lag_overheat_threshold_mw:
                continue

            allowed_forecast_mw = (
                recent_mean + self._transition_prior_base_allowed_excess_mw
            )
            excess_mw = forecast.forecast_mw - allowed_forecast_mw
            if excess_mw <= 0.0:
                continue

            bias = -min(
                self._transition_prior_max_abs_bias_mw,
                excess_mw * self._transition_prior_shrinkage,
            )
            if bias != 0.0:
                biases[hour] = round(float(bias), 1)

        return biases

    def _positive_residual_multiplier_by_hour(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        last_observed_hour: int | None,
    ) -> dict[int, float]:
        if (
            not self._transition_positive_mitigation_enabled
            or inference_features is None
            or inference_features.empty
            or last_observed_hour is None
            or last_observed_hour >= self._transition_min_observed_hour
        ):
            return {}

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        multipliers: dict[int, float] = {}
        for _, row in inference_features.iterrows():
            hour = int(row.get("hour", -1))
            forecast = forecast_by_hour.get(hour)
            if forecast is None or hour <= last_observed_hour:
                continue

            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if mismatch is None or mismatch <= 0:
                continue
            if (
                self._transition_prior_target_non_business_only
                and is_non_business_day != 1.0
            ):
                continue

            lag_24h = self._finite_float(row.get("lag_24h"))
            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
            if lag_24h is None or recent_mean is None:
                continue

            lag_overheat_mw = lag_24h - recent_mean
            if lag_overheat_mw <= self._transition_prior_lag_overheat_threshold_mw:
                continue
            if hour not in self._transition_positive_mitigation_hours:
                continue

            allowed_forecast_mw = (
                recent_mean + self._transition_prior_base_allowed_excess_mw
            )
            if forecast.forecast_mw <= allowed_forecast_mw:
                continue

            multipliers[hour] = self._transition_positive_mitigation_multiplier

        return multipliers

    def _apply_shape_guard(
        self,
        forecasts: list[HourlyForecast],
        last_observed_hour: int | None,
        observed_drop_relaxation_active: bool,
    ) -> tuple[list[HourlyForecast], bool]:
        if (
            not self._shape_guard_enabled
            or last_observed_hour is None
            or last_observed_hour < self._shape_guard_min_reference_hour
            or self._shape_guard_max_drop_mw <= 0.0
            or (observed_drop_relaxation_active and self._observed_drop_skip_shape_guard)
        ):
            return forecasts, False

        guarded: list[HourlyForecast] = []
        changed = False
        previous: HourlyForecast | None = None
        for forecast in forecasts:
            forecast_ts = pd.Timestamp(forecast.ts)
            forecast_hour = forecast_ts.hour
            guarded_forecast = forecast
            if previous is not None:
                previous_ts = pd.Timestamp(previous.ts)
                is_consecutive_same_day = (
                    forecast_ts.date() == previous_ts.date()
                    and forecast_hour == previous_ts.hour + 1
                )
                if is_consecutive_same_day and forecast_hour in self._shape_guard_hours:
                    min_forecast_mw = previous.forecast_mw - self._shape_guard_max_drop_mw
                    if forecast.forecast_mw < min_forecast_mw:
                        guarded_forecast = self._shift_forecast(
                            forecast,
                            min_forecast_mw - forecast.forecast_mw,
                        )
                        changed = True

            guarded.append(guarded_forecast)
            previous = guarded_forecast

        return guarded, changed

    def _apply_ramp_guard(
        self,
        forecasts: list[HourlyForecast],
        last_observed_hour: int | None,
        last_observed_mw: float | None,
        observed_drop_relaxation_active: bool,
    ) -> tuple[list[HourlyForecast], bool]:
        if (
            not self._ramp_guard_enabled
            or last_observed_hour is None
            or last_observed_mw is None
            or last_observed_hour < self._ramp_guard_min_reference_hour
        ):
            return forecasts, False

        guarded: list[HourlyForecast] = []
        changed = False
        for forecast in forecasts:
            forecast_hour = pd.Timestamp(forecast.ts).hour
            lead_hours = forecast_hour - last_observed_hour
            if lead_hours <= 0 or lead_hours > self._ramp_guard_max_lead_hours:
                guarded.append(forecast)
                continue

            max_forecast_mw = last_observed_mw + self._ramp_guard_cap_for_lead(lead_hours)
            min_forecast_mw = last_observed_mw - self._ramp_guard_drop_cap_for_lead(
                lead_hours,
                observed_drop_relaxation_active,
            )
            if min_forecast_mw <= forecast.forecast_mw <= max_forecast_mw:
                guarded.append(forecast)
                continue

            target_mw = min(max(forecast.forecast_mw, min_forecast_mw), max_forecast_mw)

            guarded.append(self._shift_forecast(forecast, target_mw - forecast.forecast_mw))
            changed = True

        return guarded, changed

    def apply(
        self,
        forecasts: list[HourlyForecast],
        actual_series: list[dict],
        previous_actual_series: list[dict] | None = None,
        previous_forecasts: list[HourlyForecast] | None = None,
        inference_features: pd.DataFrame | None = None,
    ) -> IntradayCorrectionResult:
        if not self._enabled or not forecasts:
            return IntradayCorrectionResult(forecasts, False, 0, None, 0.0)

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        residuals_by_hour: list[_ResidualPoint] = []
        actual_mw_by_hour: dict[int, float] = {}
        fallback_residuals_ignored = 0

        for point in actual_series:
            actual_mw = point.get("actualMw")
            if actual_mw is None or not point.get("ts"):
                continue
            if point.get("actualSource") == _TEPCO_FORECAST_FALLBACK_SOURCE:
                fallback_residuals_ignored += 1
                continue
            point_ts = pd.Timestamp(point["ts"])
            hour = point_ts.hour
            forecast = forecast_by_hour.get(hour)
            if forecast is None:
                continue
            actual_mw_by_hour[hour] = float(actual_mw)
            residual = float(actual_mw) - float(forecast.forecast_mw)
            residuals_by_hour.append(_ResidualPoint(
                hour,
                residual,
                self._residual_weight(point_ts, residual),
                point_ts,
            ))

        residuals_by_hour.sort(key=lambda item: item.hour)
        last_observed_hour = residuals_by_hour[-1].hour if residuals_by_hour else None
        last_observed_mw = (
            actual_mw_by_hour.get(last_observed_hour)
            if last_observed_hour is not None
            else None
        )
        recent_residuals = residuals_by_hour[-self._lookback_hours:]
        source_confidence = self._source_confidence(
            actual_series,
            len(residuals_by_hour),
            fallback_residuals_ignored,
        )
        applied_reasons: list[str] = []
        if fallback_residuals_ignored:
            applied_reasons.append("fallback_residuals_ignored")

        observed_drop_relaxation_active = self._is_observed_drop_relaxation_active(
            actual_mw_by_hour,
            last_observed_hour,
        )
        if len(recent_residuals) < self._min_observed_hours:
            calibrated_forecasts, applied_day_bias_mw = self._apply_hourly_bias(
                forecasts,
                self._day_level_bias_by_hour(
                    forecasts,
                    inference_features,
                    len(residuals_by_hour),
                ),
                last_observed_hour,
            )
            if applied_day_bias_mw != 0.0:
                applied_reasons.append("lag24_overheat_with_cooler_day")

            carryover_adjustment_mw = 0.0
            carryover_source_hour: int | None = None
            first_forecast_ts = min(pd.Timestamp(forecast.ts) for forecast in forecasts)
            previous_residual = self._latest_previous_observed_residual(
                previous_actual_series or [],
                previous_forecasts or [],
                first_forecast_ts,
            )
            if previous_residual is not None:
                carryover_adjustment_mw, carryover_source_hour, _ = previous_residual
                if carryover_adjustment_mw != 0.0:
                    carry_bias_by_hour = {
                        pd.Timestamp(forecast.ts).hour: carryover_adjustment_mw
                        for forecast in calibrated_forecasts
                    }
                    calibrated_forecasts, _ = self._apply_hourly_bias(
                        calibrated_forecasts,
                        carry_bias_by_hour,
                        last_observed_hour,
                    )
                    applied_reasons.append("day_boundary_residual_carryover")

            transition_prior_bias_by_hour = (
                self._business_type_transition_prior_bias_by_hour(
                    calibrated_forecasts,
                    inference_features,
                    last_observed_hour,
                )
            )
            calibrated_forecasts, business_type_transition_prior_bias_mw = (
                self._apply_hourly_bias(
                    calibrated_forecasts,
                    transition_prior_bias_by_hour,
                    last_observed_hour,
                )
            )
            business_type_transition_prior_applied = bool(
                business_type_transition_prior_bias_mw != 0.0
            )
            if business_type_transition_prior_applied:
                applied_reasons.append("business_type_transition_prior_lag_overheat")

            shape_guarded_forecasts, shape_guard_applied = self._apply_shape_guard(
                calibrated_forecasts,
                last_observed_hour,
                observed_drop_relaxation_active,
            )
            ramp_guarded_forecasts, ramp_guard_applied = self._apply_ramp_guard(
                shape_guarded_forecasts,
                last_observed_hour,
                last_observed_mw,
                observed_drop_relaxation_active,
            )
            return IntradayCorrectionResult(
                ramp_guarded_forecasts,
                bool(
                    ramp_guard_applied
                    or shape_guard_applied
                    or applied_day_bias_mw != 0.0
                    or carryover_adjustment_mw != 0.0
                    or business_type_transition_prior_bias_mw != 0.0
                ),
                len(residuals_by_hour),
                last_observed_hour,
                0.0,
                ramp_guard_applied,
                False,
                shape_guard_applied,
                observed_drop_relaxation_active,
                False,
                fallback_residuals_ignored,
                round(carryover_adjustment_mw, 1),
                carryover_source_hour,
                round(applied_day_bias_mw, 1),
                round(business_type_transition_prior_bias_mw, 1),
                business_type_transition_prior_applied,
                0.0,
                False,
                source_confidence,
                tuple(applied_reasons),
            )

        max_forecast_hour = max(forecast_by_hour)
        if last_observed_hour >= max_forecast_hour:
            return IntradayCorrectionResult(
                forecasts,
                False,
                len(residuals_by_hour),
                last_observed_hour,
                0.0,
                False,
                False,
                False,
                False,
                False,
                fallback_residuals_ignored,
                0.0,
                None,
                0.0,
                0.0,
                False,
                0.0,
                False,
                source_confidence,
                tuple(applied_reasons),
            )

        recent_weights = np.array([point.weight for point in recent_residuals], dtype=float)
        recent_residual_values = np.array(
            [point.residual_mw for point in recent_residuals],
            dtype=float,
        )
        if float(recent_weights.sum()) <= 0.0:
            base_adjustment_mw = float(np.mean(recent_residual_values))
        else:
            base_adjustment_mw = float(
                np.average(recent_residual_values, weights=recent_weights)
            )
        midday_residual_deweighted = bool(np.any(recent_weights < 1.0))
        base_adjustment_mw *= self._shrinkage
        negative_adjustment_damped = (
            self._negative_damping_enabled
            and base_adjustment_mw < 0.0
            and last_observed_hour >= self._negative_damping_min_reference_hour
        )
        if negative_adjustment_damped:
            base_adjustment_mw *= self._negative_damping_multiplier
            applied_reasons.append("negative_residual_damping")
        base_adjustment_mw = float(np.clip(
            base_adjustment_mw,
            -self._max_abs_adjustment_mw,
            self._max_abs_adjustment_mw,
        ))
        if base_adjustment_mw != 0.0:
            applied_reasons.append("intraday_observed_residual")

        transition_bias_by_hour = self._business_type_transition_bias_by_hour(
            forecasts,
            inference_features,
            last_observed_hour,
            recent_residuals,
        )
        transition_guarded_forecasts, business_type_transition_bias_mw = (
            self._apply_hourly_bias(
                forecasts,
                transition_bias_by_hour,
                last_observed_hour,
            )
        )
        business_type_transition_applied = bool(business_type_transition_bias_mw != 0.0)
        if business_type_transition_applied:
            applied_reasons.append("business_type_transition_lag_overheat")

        transition_prior_bias_by_hour = (
            self._business_type_transition_prior_bias_by_hour(
                transition_guarded_forecasts,
                inference_features,
                last_observed_hour,
            )
        )
        transition_prior_guarded_forecasts, business_type_transition_prior_bias_mw = (
            self._apply_hourly_bias(
                transition_guarded_forecasts,
                transition_prior_bias_by_hour,
                last_observed_hour,
            )
        )
        business_type_transition_prior_applied = bool(
            business_type_transition_prior_bias_mw != 0.0
        )
        if business_type_transition_prior_applied:
            applied_reasons.append("business_type_transition_prior_lag_overheat")

        positive_residual_multiplier_by_hour = (
            self._positive_residual_multiplier_by_hour(
                transition_prior_guarded_forecasts,
                inference_features,
                last_observed_hour,
            )
        )
        positive_residual_mitigation_applied = False
        positive_residual_mitigated_values: list[float] = []

        adjusted_forecasts: list[HourlyForecast] = []
        for forecast in transition_prior_guarded_forecasts:
            forecast_hour = pd.Timestamp(forecast.ts).hour
            if forecast_hour <= last_observed_hour:
                adjusted_forecasts.append(forecast)
                continue

            lead_hours = forecast_hour - last_observed_hour
            decayed_adjustment_mw = round(
                base_adjustment_mw * (self._decay_per_hour ** (lead_hours - 1)),
                1,
            )
            if decayed_adjustment_mw > 0.0:
                positive_multiplier = positive_residual_multiplier_by_hour.get(
                    forecast_hour,
                )
                if positive_multiplier is not None:
                    mitigated_adjustment_mw = round(
                        decayed_adjustment_mw * positive_multiplier,
                        1,
                    )
                    if mitigated_adjustment_mw < decayed_adjustment_mw:
                        positive_residual_mitigation_applied = True
                        positive_residual_mitigated_values.append(
                            decayed_adjustment_mw - mitigated_adjustment_mw,
                        )
                        decayed_adjustment_mw = mitigated_adjustment_mw
            adjusted_forecasts.append(HourlyForecast(
                ts=forecast.ts,
                forecast_mw=round(forecast.forecast_mw + decayed_adjustment_mw, 1),
                p95_lower_mw=round(forecast.p95_lower_mw + decayed_adjustment_mw, 1),
                p95_upper_mw=round(forecast.p95_upper_mw + decayed_adjustment_mw, 1),
                p99_lower_mw=round(forecast.p99_lower_mw + decayed_adjustment_mw, 1),
                p99_upper_mw=round(forecast.p99_upper_mw + decayed_adjustment_mw, 1),
            ))
        if positive_residual_mitigation_applied:
            applied_reasons.append("positive_residual_mitigation")

        adjusted_forecasts, shape_guard_applied = self._apply_shape_guard(
            adjusted_forecasts,
            last_observed_hour,
            observed_drop_relaxation_active,
        )

        adjusted_forecasts, ramp_guard_applied = self._apply_ramp_guard(
            adjusted_forecasts,
            last_observed_hour,
            last_observed_mw,
            observed_drop_relaxation_active,
        )

        return IntradayCorrectionResult(
            adjusted_forecasts,
            True,
            len(residuals_by_hour),
            last_observed_hour,
            round(base_adjustment_mw, 1),
            ramp_guard_applied,
            negative_adjustment_damped,
            shape_guard_applied,
            observed_drop_relaxation_active,
            midday_residual_deweighted,
            fallback_residuals_ignored,
            0.0,
            None,
            0.0,
            round(business_type_transition_prior_bias_mw, 1),
            business_type_transition_prior_applied,
            round(business_type_transition_bias_mw, 1),
            business_type_transition_applied,
            source_confidence,
            tuple(applied_reasons),
            positive_residual_mitigation_applied,
            round(max(positive_residual_mitigated_values or [0.0]), 1),
        )
