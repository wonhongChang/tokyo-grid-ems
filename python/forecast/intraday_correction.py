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
    neg_residual_recovery_damping_applied: bool = False
    neg_residual_recovery_damping_factor: float = 1.0
    positive_residual_slope_damping_applied: bool = False
    positive_residual_slope_damping_factor: float = 1.0
    positive_residual_slope_damping_max_mw: float = 0.0
    morning_positive_residual_carryover_damping_applied: bool = False
    morning_positive_residual_carryover_damping_factor: float = 1.0
    morning_positive_residual_carryover_damping_max_mw: float = 0.0
    residual_adjustments_by_hour: tuple[dict, ...] = ()
    morning_ramp_continuity_guard_applied: bool = False
    morning_ramp_continuity_max_restore_mw: float = 0.0
    morning_warm_lag_overreaction_guard_applied: bool = False
    morning_warm_lag_overreaction_max_reduction_mw: float = 0.0
    evening_decline_continuity_guard_applied: bool = False
    evening_decline_continuity_max_reduction_mw: float = 0.0
    negative_residual_continuity_floor_applied: bool = False
    negative_residual_continuity_floor_max_restore_mw: float = 0.0
    negative_residual_near_term_floor_applied: bool = False
    negative_residual_near_term_floor_max_restore_mw: float = 0.0
    morning_observed_anchor_cap_applied: bool = False
    morning_observed_anchor_cap_max_reduction_mw: float = 0.0

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
            "negResidualRecoveryDampingApplied": (
                self.neg_residual_recovery_damping_applied
            ),
            "negResidualRecoveryDampingFactor": round(
                float(self.neg_residual_recovery_damping_factor),
                3,
            ),
            "positiveResidualSlopeDampingApplied": (
                self.positive_residual_slope_damping_applied
            ),
            "positiveResidualSlopeDampingFactor": round(
                float(self.positive_residual_slope_damping_factor),
                3,
            ),
            "positiveResidualSlopeDampingMaxMw": round(
                float(self.positive_residual_slope_damping_max_mw),
                1,
            ),
            "morningPositiveResidualCarryoverDampingApplied": (
                self.morning_positive_residual_carryover_damping_applied
            ),
            "morningPositiveResidualCarryoverDampingFactor": round(
                float(self.morning_positive_residual_carryover_damping_factor),
                3,
            ),
            "morningPositiveResidualCarryoverDampingMaxMw": round(
                float(self.morning_positive_residual_carryover_damping_max_mw),
                1,
            ),
            "morningRampContinuityGuardApplied": (
                self.morning_ramp_continuity_guard_applied
            ),
            "morningRampContinuityMaxRestoreMw": round(
                float(self.morning_ramp_continuity_max_restore_mw),
                1,
            ),
            "morningWarmLagOverreactionGuardApplied": (
                self.morning_warm_lag_overreaction_guard_applied
            ),
            "morningWarmLagOverreactionMaxReductionMw": round(
                float(self.morning_warm_lag_overreaction_max_reduction_mw),
                1,
            ),
            "morningObservedAnchorCapApplied": (
                self.morning_observed_anchor_cap_applied
            ),
            "morningObservedAnchorCapMaxReductionMw": round(
                float(self.morning_observed_anchor_cap_max_reduction_mw),
                1,
            ),
            "eveningDeclineContinuityGuardApplied": (
                self.evening_decline_continuity_guard_applied
            ),
            "eveningDeclineContinuityMaxReductionMw": round(
                float(self.evening_decline_continuity_max_reduction_mw),
                1,
            ),
            "negativeResidualContinuityFloorApplied": (
                self.negative_residual_continuity_floor_applied
            ),
            "negativeResidualContinuityFloorMaxRestoreMw": round(
                float(self.negative_residual_continuity_floor_max_restore_mw),
                1,
            ),
            "negativeResidualNearTermFloorApplied": (
                self.negative_residual_near_term_floor_applied
            ),
            "negativeResidualNearTermFloorMaxRestoreMw": round(
                float(self.negative_residual_near_term_floor_max_restore_mw),
                1,
            ),
            "residualCarryoverByHour": list(self.residual_adjustments_by_hour),
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
        recovery_damping_config = correction_config.get(
            "negative_residual_recovery_damping",
            {},
        )
        self._recovery_damping_enabled = bool(
            recovery_damping_config.get("enabled", True)
        )
        self._recovery_slope_base_mw = float(
            recovery_damping_config.get("recovery_slope_base_mw", 1_000.0)
        )
        self._recovery_anchor_tolerance_mw = float(
            recovery_damping_config.get("anchor_proximity_tolerance_mw", 1_200.0)
        )
        self._recovery_damping_factor_default = min(
            max(float(recovery_damping_config.get("damping_factor_default", 0.4)), 0.0),
            1.0,
        )
        self._recovery_damping_factor_strong = min(
            max(float(recovery_damping_config.get("damping_factor_strong", 0.2)), 0.0),
            1.0,
        )
        self._recovery_strong_mean_slope_mw = float(
            recovery_damping_config.get("strong_recovery_mean_slope_mw", 500.0)
        )
        negative_floor_config = correction_config.get(
            "negative_residual_continuity_floor",
            {},
        )
        self._negative_floor_enabled = bool(
            negative_floor_config.get("enabled", True)
        )
        self._negative_floor_non_business_day_only = bool(
            negative_floor_config.get("non_business_day_only", True)
        )
        self._negative_floor_target_hours = {
            int(hour)
            for hour in negative_floor_config.get(
                "target_hours",
                [10, 11, 12, 13, 14, 15, 16, 17],
            )
        }
        self._negative_floor_min_reference_hour = int(
            negative_floor_config.get("min_reference_hour", 10)
        )
        self._negative_floor_max_lead_hours = max(
            int(negative_floor_config.get("max_lead_hours", 2)),
            1,
        )
        self._negative_floor_latest_slope_min_mw = float(
            negative_floor_config.get("latest_slope_min_mw", -300.0)
        )
        self._negative_floor_mean_slope_min_mw = float(
            negative_floor_config.get("mean_slope_min_mw", -300.0)
        )
        self._negative_floor_slack_mw = max(
            float(negative_floor_config.get("floor_slack_mw", 500.0)),
            0.0,
        )
        self._negative_floor_slope_fraction = max(
            float(negative_floor_config.get("floor_slope_fraction", 0.25)),
            0.0,
        )
        self._negative_floor_max_slope_mw = max(
            float(negative_floor_config.get("max_floor_slope_mw", 300.0)),
            0.0,
        )
        self._negative_floor_max_restore_mw = max(
            float(negative_floor_config.get("max_restore_mw", 900.0)),
            0.0,
        )
        self._negative_floor_min_restore_mw = max(
            float(negative_floor_config.get("min_restore_mw", 100.0)),
            0.0,
        )
        near_term_floor_config = correction_config.get(
            "negative_residual_near_term_floor",
            {},
        )
        self._near_negative_floor_enabled = bool(
            near_term_floor_config.get("enabled", True)
        )
        self._near_negative_floor_target_hours = {
            int(hour)
            for hour in near_term_floor_config.get(
                "target_hours",
                [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
            )
        }
        self._near_negative_floor_min_reference_hour = int(
            near_term_floor_config.get("min_reference_hour", 10)
        )
        self._near_negative_floor_max_lead_hours = max(
            int(near_term_floor_config.get("max_lead_hours", 2)),
            1,
        )
        self._near_negative_floor_min_adjustment_mw = max(
            float(near_term_floor_config.get("min_adjustment_mw", 500.0)),
            0.0,
        )
        self._near_negative_floor_actual_slack_mw = max(
            float(near_term_floor_config.get("actual_reference_slack_mw", 500.0)),
            0.0,
        )
        self._near_negative_floor_anchor_slack_mw = max(
            float(near_term_floor_config.get("anchor_slack_mw", 1_200.0)),
            0.0,
        )
        self._near_negative_floor_drop_fraction = max(
            float(near_term_floor_config.get("drop_slope_allowance_fraction", 0.25)),
            0.0,
        )
        self._near_negative_floor_max_drop_allowance_mw = max(
            float(near_term_floor_config.get("max_drop_slope_allowance_mw", 400.0)),
            0.0,
        )
        self._near_negative_floor_max_restore_mw = max(
            float(near_term_floor_config.get("max_restore_mw", 700.0)),
            0.0,
        )
        self._near_negative_floor_min_restore_mw = max(
            float(near_term_floor_config.get("min_restore_mw", 100.0)),
            0.0,
        )
        positive_slope_config = correction_config.get(
            "positive_residual_slope_damping",
            {},
        )
        self._positive_slope_damping_enabled = bool(
            positive_slope_config.get("enabled", True)
        )
        self._positive_slope_min_reference_hour = int(
            positive_slope_config.get("min_reference_hour", 12)
        )
        self._positive_slope_max_lead_hours = max(
            int(positive_slope_config.get("max_lead_hours", 3)),
            1,
        )
        self._positive_slope_min_base_adjustment_mw = float(
            positive_slope_config.get("min_base_adjustment_mw", 300.0)
        )
        self._positive_slope_min_residual_mw = float(
            positive_slope_config.get("min_positive_residual_mw", 300.0)
        )
        self._positive_slope_residual_improvement_mw = float(
            positive_slope_config.get("min_residual_improvement_mw", 300.0)
        )
        self._positive_slope_deceleration_mw = float(
            positive_slope_config.get("min_slope_deceleration_mw", 500.0)
        )
        self._positive_slope_drop_threshold_mw = float(
            positive_slope_config.get("drop_slope_threshold_mw", 300.0)
        )
        self._positive_slope_latest_slope_max_mw = float(
            positive_slope_config.get("latest_slope_max_mw", 400.0)
        )
        self._positive_slope_anchor_tolerance_mw = float(
            positive_slope_config.get("anchor_proximity_tolerance_mw", 1_200.0)
        )
        self._positive_slope_peak_excess_allowance_mw = float(
            positive_slope_config.get("peak_excess_allowance_mw", 300.0)
        )
        self._positive_slope_damping_factor = min(
            max(float(positive_slope_config.get("damping_factor", 0.4)), 0.0),
            1.0,
        )
        morning_positive_config = correction_config.get(
            "morning_positive_residual_carryover_damping",
            {},
        )
        self._morning_positive_damping_enabled = bool(
            morning_positive_config.get("enabled", False)
        )
        self._morning_positive_business_day_only = bool(
            morning_positive_config.get("business_day_only", True)
        )
        self._morning_positive_target_hours = {
            int(hour)
            for hour in morning_positive_config.get(
                "target_hours",
                [10, 11, 12, 13],
            )
        }
        self._morning_positive_min_reference_hour = int(
            morning_positive_config.get("min_reference_hour", 7)
        )
        self._morning_positive_max_reference_hour = int(
            morning_positive_config.get("max_reference_hour", 10)
        )
        self._morning_positive_min_lead_hours = max(
            int(morning_positive_config.get("min_lead_hours", 2)),
            1,
        )
        self._morning_positive_max_lead_hours = max(
            int(morning_positive_config.get("max_lead_hours", 4)),
            self._morning_positive_min_lead_hours,
        )
        self._morning_positive_min_base_adjustment_mw = max(
            float(morning_positive_config.get("min_base_adjustment_mw", 300.0)),
            0.0,
        )
        self._morning_positive_min_recent_ramp_slope_mw = max(
            float(morning_positive_config.get("min_recent_ramp_slope_mw", 1_000.0)),
            0.0,
        )
        self._morning_positive_weak_support_delta_mw = float(
            morning_positive_config.get("weak_support_delta_mw", 1_000.0)
        )
        self._morning_positive_damping_factor = min(
            max(float(morning_positive_config.get("damping_factor", 0.4)), 0.0),
            1.0,
        )
        self._morning_positive_min_damped_mw = max(
            float(morning_positive_config.get("min_damped_mw", 100.0)),
            0.0,
        )
        morning_ramp_config = correction_config.get(
            "morning_ramp_continuity_guard",
            {},
        )
        self._morning_ramp_continuity_enabled = bool(
            morning_ramp_config.get("enabled", False)
        )
        self._morning_ramp_business_day_only = bool(
            morning_ramp_config.get("business_day_only", True)
        )
        self._morning_ramp_target_hours = {
            int(hour)
            for hour in morning_ramp_config.get("target_hours", [6, 7, 8, 9, 10, 11])
        }
        self._morning_ramp_min_reference_hour = int(
            morning_ramp_config.get("min_reference_hour", 7)
        )
        self._morning_ramp_max_lead_hours = max(
            int(morning_ramp_config.get("max_lead_hours", 2)),
            1,
        )
        self._morning_ramp_min_slope_mw = float(
            morning_ramp_config.get("min_recent_slope_mw", 1_000.0)
        )
        self._morning_ramp_min_mean_slope_mw = float(
            morning_ramp_config.get("min_mean_slope_mw", 1_000.0)
        )
        self._morning_ramp_floor_slope_fraction = max(
            float(morning_ramp_config.get("floor_slope_fraction", 0.25)),
            0.0,
        )
        self._morning_ramp_max_floor_delta_mw = max(
            float(morning_ramp_config.get("max_floor_delta_mw", 900.0)),
            0.0,
        )
        self._morning_ramp_max_restore_mw = max(
            float(morning_ramp_config.get("max_restore_mw", 700.0)),
            0.0,
        )
        self._morning_ramp_min_restore_mw = max(
            float(morning_ramp_config.get("min_restore_mw", 100.0)),
            0.0,
        )
        morning_warm_config = correction_config.get(
            "morning_warm_lag_overreaction_guard",
            {},
        )
        self._morning_warm_enabled = bool(
            morning_warm_config.get("enabled", False)
        )
        self._morning_warm_business_day_only = bool(
            morning_warm_config.get("business_day_only", True)
        )
        self._morning_warm_target_hours = {
            int(hour)
            for hour in morning_warm_config.get("target_hours", [8, 9, 10, 11])
        }
        self._morning_warm_min_reference_hour = int(
            morning_warm_config.get("min_reference_hour", 6)
        )
        self._morning_warm_max_reference_hour = int(
            morning_warm_config.get("max_reference_hour", 10)
        )
        self._morning_warm_max_lead_hours = max(
            int(morning_warm_config.get("max_lead_hours", 2)),
            1,
        )
        self._morning_warm_min_base_adjustment_mw = max(
            float(morning_warm_config.get("min_base_adjustment_mw", 500.0)),
            0.0,
        )
        self._morning_warm_min_temp_delta_24h_c = float(
            morning_warm_config.get("min_temp_delta_24h_c", 2.0)
        )
        self._morning_warm_min_cooling_delta_24h_c = float(
            morning_warm_config.get("min_cooling_delta_24h_c", 0.8)
        )
        self._morning_warm_slope_slack_mw = max(
            float(morning_warm_config.get("slope_slack_mw", 300.0)),
            0.0,
        )
        self._morning_warm_min_projected_slope_mw = max(
            float(morning_warm_config.get("min_projected_slope_mw", 400.0)),
            0.0,
        )
        self._morning_warm_max_projected_slope_mw = max(
            float(morning_warm_config.get("max_projected_slope_mw", 1_800.0)),
            0.0,
        )
        self._morning_warm_cap_buffer_mw = max(
            float(morning_warm_config.get("cap_buffer_mw", 0.0)),
            0.0,
        )
        self._morning_warm_shrinkage = min(
            max(float(morning_warm_config.get("shrinkage", 0.75)), 0.0),
            1.0,
        )
        self._morning_warm_max_reduction_mw = max(
            float(morning_warm_config.get("max_reduction_mw", 800.0)),
            0.0,
        )
        self._morning_warm_min_reduction_mw = max(
            float(morning_warm_config.get("min_reduction_mw", 100.0)),
            0.0,
        )
        morning_anchor_config = correction_config.get(
            "morning_observed_anchor_cap",
            {},
        )
        self._morning_anchor_cap_enabled = bool(
            morning_anchor_config.get("enabled", False)
        )
        self._morning_anchor_business_day_only = bool(
            morning_anchor_config.get("business_day_only", True)
        )
        self._morning_anchor_target_hours = {
            int(hour)
            for hour in morning_anchor_config.get(
                "target_hours",
                [10, 11, 12, 13],
            )
        }
        self._morning_anchor_min_reference_hour = int(
            morning_anchor_config.get("min_reference_hour", 8)
        )
        self._morning_anchor_max_reference_hour = int(
            morning_anchor_config.get("max_reference_hour", 12)
        )
        self._morning_anchor_max_lead_hours = max(
            int(morning_anchor_config.get("max_lead_hours", 4)),
            1,
        )
        self._morning_anchor_min_overforecast_mw = max(
            float(morning_anchor_config.get("min_latest_overforecast_mw", 200.0)),
            0.0,
        )
        self._morning_anchor_cap_buffer_mw = max(
            float(morning_anchor_config.get("cap_buffer_mw", 250.0)),
            0.0,
        )
        self._morning_anchor_shrinkage = min(
            max(float(morning_anchor_config.get("shrinkage", 0.75)), 0.0),
            1.0,
        )
        self._morning_anchor_max_reduction_mw = max(
            float(morning_anchor_config.get("max_reduction_mw", 800.0)),
            0.0,
        )
        self._morning_anchor_min_reduction_mw = max(
            float(morning_anchor_config.get("min_reduction_mw", 100.0)),
            0.0,
        )
        evening_decline_config = correction_config.get(
            "evening_decline_continuity_guard",
            {},
        )
        self._evening_decline_enabled = bool(
            evening_decline_config.get("enabled", False)
        )
        self._evening_decline_business_day_only = bool(
            evening_decline_config.get("business_day_only", False)
        )
        self._evening_decline_target_hours = {
            int(hour)
            for hour in evening_decline_config.get("target_hours", [16, 17, 18, 19, 20])
        }
        self._evening_decline_min_reference_hour = int(
            evening_decline_config.get("min_reference_hour", 16)
        )
        self._evening_decline_max_lead_hours = max(
            int(evening_decline_config.get("max_lead_hours", 2)),
            1,
        )
        self._evening_decline_latest_slope_max_mw = float(
            evening_decline_config.get("latest_slope_max_mw", -500.0)
        )
        self._evening_decline_mean_slope_max_mw = float(
            evening_decline_config.get("mean_slope_max_mw", -300.0)
        )
        self._evening_decline_max_supporting_delta_mw = float(
            evening_decline_config.get("max_supporting_delta_mw", 200.0)
        )
        self._evening_decline_min_forecast_rebound_mw = float(
            evening_decline_config.get("min_forecast_rebound_mw", 800.0)
        )
        self._evening_decline_max_rebound_mw = float(
            evening_decline_config.get("max_rebound_mw", 600.0)
        )
        self._evening_decline_actual_reference_slack_mw = max(
            float(evening_decline_config.get("actual_reference_slack_mw", 300.0)),
            0.0,
        )
        self._evening_decline_weather_allowance_mw_per_c = max(
            float(evening_decline_config.get("weather_allowance_mw_per_c", 120.0)),
            0.0,
        )
        self._evening_decline_hot_temp_c = float(
            evening_decline_config.get("hot_temp_c", 30.0)
        )
        self._evening_decline_max_weather_allowance_mw = max(
            float(evening_decline_config.get("max_weather_allowance_mw", 400.0)),
            0.0,
        )
        self._evening_decline_max_reduction_mw = max(
            float(evening_decline_config.get("max_reduction_mw", 900.0)),
            0.0,
        )
        self._evening_decline_min_reduction_mw = max(
            float(evening_decline_config.get("min_reduction_mw", 100.0)),
            0.0,
        )
        self._evening_decline_level_overhang_enabled = bool(
            evening_decline_config.get("level_overhang_enabled", True)
        )
        self._evening_decline_min_level_overhang_mw = max(
            float(evening_decline_config.get("min_level_overhang_mw", 500.0)),
            0.0,
        )
        self._evening_decline_level_overhang_shrinkage = min(
            max(
                float(evening_decline_config.get("level_overhang_shrinkage", 0.75)),
                0.0,
            ),
            1.0,
        )
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

    def _feature_row_for_hour(
        self,
        inference_features: pd.DataFrame | None,
        hour: int,
    ) -> pd.Series | None:
        if inference_features is None or inference_features.empty:
            return None
        if "hour" not in inference_features.columns:
            return None
        hour_values = pd.to_numeric(inference_features["hour"], errors="coerce")
        rows = inference_features[hour_values == hour]
        if rows.empty:
            return None
        return rows.iloc[0]

    def _negative_residual_recovery_damping_factor(
        self,
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        residuals_by_hour: list[_ResidualPoint],
        last_observed_hour: int | None,
        base_adjustment_mw: float,
    ) -> float:
        if (
            not self._recovery_damping_enabled
            or base_adjustment_mw >= 0.0
            or last_observed_hour is None
            or len(residuals_by_hour) < 3
        ):
            return 1.0

        required_hours = [
            last_observed_hour - 2,
            last_observed_hour - 1,
            last_observed_hour,
        ]
        if any(hour not in actual_mw_by_hour for hour in required_hours):
            return 1.0

        actual_values = [actual_mw_by_hour[hour] for hour in required_hours]
        recent_slopes = [
            actual_values[1] - actual_values[0],
            actual_values[2] - actual_values[1],
        ]
        mean_slope = float(np.mean(recent_slopes))
        if mean_slope <= 0.0 or max(recent_slopes) < self._recovery_slope_base_mw:
            return 1.0

        row = self._feature_row_for_hour(inference_features, last_observed_hour)
        if row is None:
            return 1.0
        is_non_business_day = self._finite_float(row.get("is_non_business_day"))
        mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
        if is_non_business_day != 1.0 or mismatch is None or mismatch <= 0.0:
            return 1.0

        recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
        lag_24h = self._finite_float(row.get("lag_24h"))
        if recent_mean is None or lag_24h is None:
            return 1.0
        if lag_24h <= recent_mean:
            return 1.0

        last_actual_mw = actual_mw_by_hour[last_observed_hour]
        if last_actual_mw < recent_mean - self._recovery_anchor_tolerance_mw:
            return 1.0

        recent_residuals = sorted(residuals_by_hour, key=lambda point: point.hour)[-3:]
        if any(point.residual_mw >= 0.0 for point in recent_residuals):
            return 1.0
        residual_values = [point.residual_mw for point in recent_residuals]
        residual_strictly_improving = (
            residual_values[0] < residual_values[1] < residual_values[2]
        )
        if not residual_strictly_improving:
            return 1.0

        strong_recovery = (
            mean_slope >= self._recovery_strong_mean_slope_mw
            and last_actual_mw >= recent_mean
        )
        if strong_recovery:
            return min(
                self._recovery_damping_factor_default,
                self._recovery_damping_factor_strong,
            )
        return self._recovery_damping_factor_default

    def _positive_residual_slope_damping_context(
        self,
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        residuals_by_hour: list[_ResidualPoint],
        last_observed_hour: int | None,
        base_adjustment_mw: float,
    ) -> dict | None:
        if (
            not self._positive_slope_damping_enabled
            or base_adjustment_mw <= self._positive_slope_min_base_adjustment_mw
            or last_observed_hour is None
            or last_observed_hour < self._positive_slope_min_reference_hour
            or len(residuals_by_hour) < 3
        ):
            return None

        required_hours = [
            last_observed_hour - 2,
            last_observed_hour - 1,
            last_observed_hour,
        ]
        if any(hour not in actual_mw_by_hour for hour in required_hours):
            return None

        actual_values = [actual_mw_by_hour[hour] for hour in required_hours]
        previous_slope_mw = actual_values[1] - actual_values[0]
        latest_slope_mw = actual_values[2] - actual_values[1]
        slope_deceleration_mw = previous_slope_mw - latest_slope_mw
        slope_is_falling = latest_slope_mw <= -self._positive_slope_drop_threshold_mw
        slope_is_decelerating = (
            slope_deceleration_mw >= self._positive_slope_deceleration_mw
            and latest_slope_mw <= self._positive_slope_latest_slope_max_mw
        )
        if not (slope_is_falling or slope_is_decelerating):
            return None

        recent_residuals = sorted(residuals_by_hour, key=lambda point: point.hour)[-3:]
        residual_values = [point.residual_mw for point in recent_residuals]
        if any(value < self._positive_slope_min_residual_mw for value in residual_values):
            return None
        latest_improvement_mw = residual_values[-2] - residual_values[-1]
        if latest_improvement_mw < self._positive_slope_residual_improvement_mw:
            return None

        row = self._feature_row_for_hour(inference_features, last_observed_hour)
        recent_mean = None
        if row is not None:
            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))

        last_actual_mw = actual_mw_by_hour[last_observed_hour]
        if recent_mean is not None:
            if last_actual_mw < recent_mean - self._positive_slope_anchor_tolerance_mw:
                return None
            reference_level_mw = max(last_actual_mw, recent_mean)
        else:
            reference_level_mw = last_actual_mw

        return {
            "factor": self._positive_slope_damping_factor,
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(last_actual_mw, 1),
            "referenceLevelMw": round(reference_level_mw, 1),
            "previousSlopeMw": round(previous_slope_mw, 1),
            "latestSlopeMw": round(latest_slope_mw, 1),
            "slopeDecelerationMw": round(slope_deceleration_mw, 1),
            "latestResidualImprovementMw": round(latest_improvement_mw, 1),
        }

    def _morning_positive_residual_carryover_context(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
        base_adjustment_mw: float,
    ) -> dict | None:
        if (
            not self._morning_positive_damping_enabled
            or base_adjustment_mw < self._morning_positive_min_base_adjustment_mw
            or last_observed_hour is None
            or last_observed_hour < self._morning_positive_min_reference_hour
            or last_observed_hour > self._morning_positive_max_reference_hour
            or last_observed_hour not in actual_mw_by_hour
        ):
            return None

        if self._morning_positive_business_day_only:
            row = self._feature_row_for_hour(inference_features, last_observed_hour)
            if row is not None:
                is_non_business_day = self._finite_float(row.get("is_non_business_day"))
                if is_non_business_day == 1.0:
                    return None
            elif forecasts:
                forecast_ts = pd.Timestamp(forecasts[0].ts)
                if _is_nonworking_day(forecast_ts):
                    return None

        slope_hours = [
            last_observed_hour - 2,
            last_observed_hour - 1,
            last_observed_hour,
        ]
        if any(hour not in actual_mw_by_hour for hour in slope_hours):
            return None

        actual_values = [actual_mw_by_hour[hour] for hour in slope_hours]
        recent_slopes = [
            actual_values[1] - actual_values[0],
            actual_values[2] - actual_values[1],
        ]
        if max(recent_slopes) < self._morning_positive_min_recent_ramp_slope_mw:
            return None

        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "previousSlopeMw": round(float(recent_slopes[0]), 1),
            "latestSlopeMw": round(float(recent_slopes[1]), 1),
            "meanSlopeMw": round(float(np.mean(recent_slopes)), 1),
            "factor": self._morning_positive_damping_factor,
        }

    def _morning_positive_residual_carryover_damping(
        self,
        context: dict | None,
        inference_features: pd.DataFrame | None,
        forecast_hour: int,
        lead_hours: int,
        decayed_adjustment_mw: float,
    ) -> dict | None:
        if (
            context is None
            or forecast_hour not in self._morning_positive_target_hours
            or lead_hours < self._morning_positive_min_lead_hours
            or lead_hours > self._morning_positive_max_lead_hours
            or decayed_adjustment_mw <= 0.0
        ):
            return None

        row = self._feature_row_for_hour(inference_features, forecast_hour)
        if row is None:
            return None
        if self._morning_positive_business_day_only:
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day == 1.0:
                return None

        lag_delta_mw = self._finite_float(row.get("lag_24h_hourly_delta"))
        same_business_delta_mw = self._finite_float(
            row.get("recent_same_business_type_delta_mean")
        )
        support_candidates = [
            value
            for value in (lag_delta_mw, same_business_delta_mw)
            if value is not None
        ]
        if not support_candidates:
            return None
        support_delta_mw = max(support_candidates)
        if support_delta_mw > self._morning_positive_weak_support_delta_mw:
            return None

        damped_adjustment_mw = round(
            decayed_adjustment_mw * self._morning_positive_damping_factor,
            1,
        )
        damped_mw = decayed_adjustment_mw - damped_adjustment_mw
        if damped_mw < self._morning_positive_min_damped_mw:
            return None

        return {
            "factor": self._morning_positive_damping_factor,
            "dampedAdjustmentMw": damped_adjustment_mw,
            "dampedMw": round(float(damped_mw), 1),
            "supportDeltaMw": round(float(support_delta_mw), 1),
            "lag24DeltaMw": (
                round(float(lag_delta_mw), 1)
                if lag_delta_mw is not None
                else None
            ),
            "recentSameBusinessTypeDeltaMw": (
                round(float(same_business_delta_mw), 1)
                if same_business_delta_mw is not None
                else None
            ),
        }

    def _morning_ramp_continuity_context(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
        base_adjustment_mw: float,
    ) -> dict | None:
        if (
            not self._morning_ramp_continuity_enabled
            or base_adjustment_mw >= 0.0
            or last_observed_hour is None
            or last_observed_hour < self._morning_ramp_min_reference_hour
            or self._morning_ramp_max_restore_mw <= 0.0
        ):
            return None

        required_hours = [
            last_observed_hour - 2,
            last_observed_hour - 1,
            last_observed_hour,
        ]
        if any(hour not in actual_mw_by_hour for hour in required_hours):
            return None

        if self._morning_ramp_business_day_only:
            row = self._feature_row_for_hour(inference_features, last_observed_hour)
            if row is not None:
                is_non_business_day = self._finite_float(row.get("is_non_business_day"))
                if is_non_business_day == 1.0:
                    return None
            elif forecasts:
                forecast_ts = pd.Timestamp(forecasts[0].ts)
                if _is_nonworking_day(forecast_ts):
                    return None

        actual_values = [actual_mw_by_hour[hour] for hour in required_hours]
        recent_slopes = [
            actual_values[1] - actual_values[0],
            actual_values[2] - actual_values[1],
        ]
        if min(recent_slopes) < self._morning_ramp_min_slope_mw:
            return None
        mean_slope = float(np.mean(recent_slopes))
        if mean_slope < self._morning_ramp_min_mean_slope_mw:
            return None

        floor_delta_mw = mean_slope * self._morning_ramp_floor_slope_fraction
        if self._morning_ramp_max_floor_delta_mw > 0.0:
            floor_delta_mw = min(
                floor_delta_mw,
                self._morning_ramp_max_floor_delta_mw,
            )
        if floor_delta_mw <= 0.0:
            return None

        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "previousSlopeMw": round(recent_slopes[0], 1),
            "latestSlopeMw": round(recent_slopes[1], 1),
            "meanSlopeMw": round(mean_slope, 1),
            "floorDeltaMw": round(float(floor_delta_mw), 1),
        }

    def _morning_warm_lag_overreaction_context(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
        base_adjustment_mw: float,
    ) -> dict | None:
        if (
            not self._morning_warm_enabled
            or base_adjustment_mw > -self._morning_warm_min_base_adjustment_mw
            or last_observed_hour is None
            or last_observed_hour < self._morning_warm_min_reference_hour
            or last_observed_hour > self._morning_warm_max_reference_hour
            or last_observed_hour not in actual_mw_by_hour
            or self._morning_warm_max_reduction_mw <= 0.0
        ):
            return None

        if self._morning_warm_business_day_only:
            row = self._feature_row_for_hour(inference_features, last_observed_hour)
            if row is not None:
                is_non_business_day = self._finite_float(row.get("is_non_business_day"))
                if is_non_business_day == 1.0:
                    return None
            elif forecasts:
                forecast_ts = pd.Timestamp(forecasts[0].ts)
                if _is_nonworking_day(forecast_ts):
                    return None

        previous_hour = last_observed_hour - 1
        latest_slope_mw = 0.0
        if previous_hour in actual_mw_by_hour:
            latest_slope_mw = (
                actual_mw_by_hour[last_observed_hour]
                - actual_mw_by_hour[previous_hour]
            )

        projected_slope_mw = latest_slope_mw + self._morning_warm_slope_slack_mw
        projected_slope_mw = float(np.clip(
            projected_slope_mw,
            self._morning_warm_min_projected_slope_mw,
            self._morning_warm_max_projected_slope_mw,
        ))
        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "latestSlopeMw": round(float(latest_slope_mw), 1),
            "projectedSlopeMw": round(float(projected_slope_mw), 1),
        }

    def _morning_warm_lag_overreaction_reduction(
        self,
        context: dict | None,
        inference_features: pd.DataFrame | None,
        forecast_hour: int,
        lead_hours: int,
        final_before_guard_mw: float,
    ) -> dict | None:
        if (
            context is None
            or forecast_hour not in self._morning_warm_target_hours
            or lead_hours <= 0
            or lead_hours > self._morning_warm_max_lead_hours
        ):
            return None

        row = self._feature_row_for_hour(inference_features, forecast_hour)
        if row is None:
            return None
        if self._morning_warm_business_day_only:
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day == 1.0:
                return None

        temp_delta_24h = self._finite_float(row.get("temp_delta_24h")) or 0.0
        cooling_delta_24h = self._finite_float(row.get("cooling_delta_24h")) or 0.0
        warm_signal_active = (
            temp_delta_24h >= self._morning_warm_min_temp_delta_24h_c
            or cooling_delta_24h >= self._morning_warm_min_cooling_delta_24h_c
        )
        if not warm_signal_active:
            return None

        cap_mw = (
            float(context["lastActualMw"])
            + float(context["projectedSlopeMw"]) * lead_hours
            + self._morning_warm_cap_buffer_mw
        )
        overhang_mw = final_before_guard_mw - cap_mw
        if overhang_mw <= 0.0:
            return None

        reduction_mw = min(
            overhang_mw * self._morning_warm_shrinkage,
            self._morning_warm_max_reduction_mw,
        )
        reduction_mw = round(float(reduction_mw), 1)
        if reduction_mw < self._morning_warm_min_reduction_mw:
            return None

        return {
            "capMw": round(float(cap_mw), 1),
            "reductionMw": reduction_mw,
            "tempDelta24hC": round(float(temp_delta_24h), 1),
            "coolingDelta24hC": round(float(cooling_delta_24h), 1),
            "latestSlopeMw": context["latestSlopeMw"],
            "projectedSlopeMw": context["projectedSlopeMw"],
        }

    def _morning_observed_anchor_cap_context(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        residuals_by_hour: list[_ResidualPoint],
        last_observed_hour: int | None,
    ) -> dict | None:
        if (
            not self._morning_anchor_cap_enabled
            or last_observed_hour is None
            or last_observed_hour < self._morning_anchor_min_reference_hour
            or last_observed_hour > self._morning_anchor_max_reference_hour
            or last_observed_hour not in actual_mw_by_hour
            or self._morning_anchor_max_reduction_mw <= 0.0
        ):
            return None

        latest_residual = next(
            (
                float(point.residual_mw)
                for point in reversed(residuals_by_hour)
                if point.hour == last_observed_hour
            ),
            None,
        )
        if (
            latest_residual is None
            or latest_residual > -self._morning_anchor_min_overforecast_mw
        ):
            return None

        if self._morning_anchor_business_day_only:
            row = self._feature_row_for_hour(inference_features, last_observed_hour)
            if row is not None:
                is_non_business_day = self._finite_float(row.get("is_non_business_day"))
                if is_non_business_day == 1.0:
                    return None
            elif forecasts:
                forecast_ts = pd.Timestamp(forecasts[0].ts)
                if _is_nonworking_day(forecast_ts):
                    return None

        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "latestResidualMw": round(latest_residual, 1),
        }

    def _morning_observed_anchor_cap_reduction(
        self,
        context: dict | None,
        inference_features: pd.DataFrame | None,
        forecast_hour: int,
        lead_hours: int,
        final_before_guard_mw: float,
    ) -> dict | None:
        if (
            context is None
            or inference_features is None
            or inference_features.empty
            or forecast_hour not in self._morning_anchor_target_hours
            or lead_hours <= 0
            or lead_hours > self._morning_anchor_max_lead_hours
        ):
            return None

        row = self._feature_row_for_hour(inference_features, forecast_hour)
        if row is None:
            return None
        if self._morning_anchor_business_day_only:
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day == 1.0:
                return None

        last_observed_hour = int(context["lastObservedHour"])
        cumulative_support_mw = 0.0
        for hour in range(last_observed_hour + 1, forecast_hour + 1):
            support_row = self._feature_row_for_hour(inference_features, hour)
            if support_row is None:
                return None
            support_candidates = [
                value
                for value in (
                    self._finite_float(support_row.get("lag_24h_hourly_delta")),
                    self._finite_float(
                        support_row.get("recent_same_business_type_delta_mean")
                    ),
                )
                if value is not None
            ]
            if not support_candidates:
                return None
            cumulative_support_mw += max(support_candidates)

        cap_mw = (
            float(context["lastActualMw"])
            + cumulative_support_mw
            + self._morning_anchor_cap_buffer_mw
        )
        overhang_mw = final_before_guard_mw - cap_mw
        if overhang_mw <= 0.0:
            return None

        reduction_mw = min(
            overhang_mw * self._morning_anchor_shrinkage,
            self._morning_anchor_max_reduction_mw,
        )
        reduction_mw = round(float(reduction_mw), 1)
        if reduction_mw < self._morning_anchor_min_reduction_mw:
            return None

        return {
            "capMw": round(float(cap_mw), 1),
            "reductionMw": reduction_mw,
            "cumulativeSupportMw": round(float(cumulative_support_mw), 1),
            "latestResidualMw": context["latestResidualMw"],
        }

    def _negative_residual_continuity_floor_context(
        self,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
    ) -> dict | None:
        if (
            not self._negative_floor_enabled
            or last_observed_hour is None
            or last_observed_hour < self._negative_floor_min_reference_hour
            or self._negative_floor_max_restore_mw <= 0.0
        ):
            return None

        required_hours = [
            last_observed_hour - 2,
            last_observed_hour - 1,
            last_observed_hour,
        ]
        if any(hour not in actual_mw_by_hour for hour in required_hours):
            return None

        actual_values = [actual_mw_by_hour[hour] for hour in required_hours]
        recent_slopes = [
            actual_values[1] - actual_values[0],
            actual_values[2] - actual_values[1],
        ]
        latest_slope_mw = recent_slopes[-1]
        mean_slope_mw = float(np.mean(recent_slopes))
        if (
            latest_slope_mw < self._negative_floor_latest_slope_min_mw
            or mean_slope_mw < self._negative_floor_mean_slope_min_mw
        ):
            return None

        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "previousSlopeMw": round(recent_slopes[0], 1),
            "latestSlopeMw": round(latest_slope_mw, 1),
            "meanSlopeMw": round(mean_slope_mw, 1),
        }

    def _negative_residual_continuity_floor_restore(
        self,
        context: dict | None,
        inference_features: pd.DataFrame | None,
        forecast_hour: int,
        lead_hours: int,
        final_before_floor_mw: float,
    ) -> dict | None:
        if (
            context is None
            or forecast_hour not in self._negative_floor_target_hours
            or lead_hours <= 0
            or lead_hours > self._negative_floor_max_lead_hours
        ):
            return None

        row = self._feature_row_for_hour(inference_features, forecast_hour)
        if self._negative_floor_non_business_day_only:
            if row is None:
                return None
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day != 1.0:
                return None

        last_actual_mw = float(context["lastActualMw"])
        mean_slope_mw = max(float(context["meanSlopeMw"]), 0.0)
        slope_support_mw = min(
            mean_slope_mw * self._negative_floor_slope_fraction,
            self._negative_floor_max_slope_mw,
        )
        floor_mw = last_actual_mw - self._negative_floor_slack_mw + slope_support_mw
        if final_before_floor_mw >= floor_mw:
            return None

        restore_mw = min(
            floor_mw - final_before_floor_mw,
            self._negative_floor_max_restore_mw,
        )
        restore_mw = round(float(restore_mw), 1)
        if restore_mw < self._negative_floor_min_restore_mw:
            return None

        return {
            "floorMw": round(float(floor_mw), 1),
            "restoreMw": restore_mw,
            "latestSlopeMw": context["latestSlopeMw"],
            "meanSlopeMw": context["meanSlopeMw"],
        }

    def _negative_residual_near_term_floor_context(
        self,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
    ) -> dict | None:
        if (
            not self._near_negative_floor_enabled
            or last_observed_hour is None
            or last_observed_hour < self._near_negative_floor_min_reference_hour
            or self._near_negative_floor_max_restore_mw <= 0.0
            or last_observed_hour not in actual_mw_by_hour
        ):
            return None

        latest_slope_mw = 0.0
        previous_hour = last_observed_hour - 1
        if previous_hour in actual_mw_by_hour:
            latest_slope_mw = (
                actual_mw_by_hour[last_observed_hour]
                - actual_mw_by_hour[previous_hour]
            )

        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "latestSlopeMw": round(float(latest_slope_mw), 1),
        }

    def _negative_residual_near_term_floor_restore(
        self,
        context: dict | None,
        inference_features: pd.DataFrame | None,
        forecast_hour: int,
        lead_hours: int,
        decayed_adjustment_mw: float,
        pre_calibration_mw: float,
        final_before_floor_mw: float,
    ) -> dict | None:
        if (
            context is None
            or decayed_adjustment_mw >= 0.0
            or abs(decayed_adjustment_mw) < self._near_negative_floor_min_adjustment_mw
            or forecast_hour not in self._near_negative_floor_target_hours
            or lead_hours <= 0
            or lead_hours > self._near_negative_floor_max_lead_hours
        ):
            return None

        latest_slope_mw = float(context.get("latestSlopeMw") or 0.0)
        drop_allowance_mw = min(
            max(0.0, -latest_slope_mw) * self._near_negative_floor_drop_fraction,
            self._near_negative_floor_max_drop_allowance_mw,
        )
        floor_candidates = [
            float(context["lastActualMw"])
            - self._near_negative_floor_actual_slack_mw
            - drop_allowance_mw,
        ]

        row = self._feature_row_for_hour(inference_features, forecast_hour)
        if row is not None:
            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
            if recent_mean is not None:
                floor_candidates.append(
                    recent_mean - self._near_negative_floor_anchor_slack_mw
                )

        floor_mw = max(floor_candidates)
        if final_before_floor_mw >= floor_mw:
            return None

        restore_mw = min(
            floor_mw - final_before_floor_mw,
            self._near_negative_floor_max_restore_mw,
            -decayed_adjustment_mw,
        )
        restore_mw = round(float(restore_mw), 1)
        if restore_mw < self._near_negative_floor_min_restore_mw:
            return None

        return {
            "floorMw": round(float(floor_mw), 1),
            "restoreMw": restore_mw,
            "latestSlopeMw": round(float(latest_slope_mw), 1),
            "dropAllowanceMw": round(float(drop_allowance_mw), 1),
            "preCalibrationMw": round(float(pre_calibration_mw), 1),
        }

    def _evening_decline_continuity_context(
        self,
        forecasts: list[HourlyForecast],
        inference_features: pd.DataFrame | None,
        actual_mw_by_hour: dict[int, float],
        last_observed_hour: int | None,
    ) -> dict | None:
        if (
            not self._evening_decline_enabled
            or last_observed_hour is None
            or last_observed_hour < self._evening_decline_min_reference_hour
            or self._evening_decline_max_reduction_mw <= 0.0
        ):
            return None

        required_hours = [
            last_observed_hour - 2,
            last_observed_hour - 1,
            last_observed_hour,
        ]
        if any(hour not in actual_mw_by_hour for hour in required_hours):
            return None

        if self._evening_decline_business_day_only:
            row = self._feature_row_for_hour(inference_features, last_observed_hour)
            if row is not None:
                is_non_business_day = self._finite_float(row.get("is_non_business_day"))
                if is_non_business_day == 1.0:
                    return None
            elif forecasts:
                forecast_ts = pd.Timestamp(forecasts[0].ts)
                if _is_nonworking_day(forecast_ts):
                    return None

        actual_values = [actual_mw_by_hour[hour] for hour in required_hours]
        recent_slopes = [
            actual_values[1] - actual_values[0],
            actual_values[2] - actual_values[1],
        ]
        latest_slope_mw = recent_slopes[-1]
        mean_slope_mw = float(np.mean(recent_slopes))
        if (
            latest_slope_mw > self._evening_decline_latest_slope_max_mw
            or mean_slope_mw > self._evening_decline_mean_slope_max_mw
        ):
            return None

        forecast_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        last_forecast = forecast_by_hour.get(last_observed_hour)
        return {
            "lastObservedHour": last_observed_hour,
            "lastActualMw": round(actual_mw_by_hour[last_observed_hour], 1),
            "lastForecastMw": (
                round(last_forecast.forecast_mw, 1)
                if last_forecast is not None
                else None
            ),
            "previousSlopeMw": round(recent_slopes[0], 1),
            "latestSlopeMw": round(latest_slope_mw, 1),
            "meanSlopeMw": round(mean_slope_mw, 1),
        }

    def _evening_decline_continuity_reduction(
        self,
        context: dict | None,
        inference_features: pd.DataFrame | None,
        forecast_hour: int,
        lead_hours: int,
        previous_final_mw: float | None,
        final_before_guard_mw: float,
    ) -> dict | None:
        if (
            context is None
            or forecast_hour not in self._evening_decline_target_hours
            or lead_hours <= 0
            or lead_hours > self._evening_decline_max_lead_hours
            or previous_final_mw is None
        ):
            return None

        row = self._feature_row_for_hour(inference_features, forecast_hour)
        if row is None:
            return None

        lag_delta_mw = self._finite_float(row.get("lag_24h_hourly_delta"))
        same_business_delta_mw = self._finite_float(
            row.get("recent_same_business_type_delta_mean")
        )
        if lag_delta_mw is None or same_business_delta_mw is None:
            return None
        if (
            lag_delta_mw > self._evening_decline_max_supporting_delta_mw
            or same_business_delta_mw > self._evening_decline_max_supporting_delta_mw
        ):
            return None

        weather_delta_c = max(
            0.0,
            self._finite_float(row.get("temp_delta_1h")) or 0.0,
            self._finite_float(row.get("cooling_delta_1h")) or 0.0,
        )
        temp_c = self._finite_float(row.get("temp_c"))
        hot_excess_c = 0.0
        if temp_c is not None and temp_c > self._evening_decline_hot_temp_c:
            hot_excess_c = temp_c - self._evening_decline_hot_temp_c
        weather_allowance_mw = min(
            (weather_delta_c + hot_excess_c)
            * self._evening_decline_weather_allowance_mw_per_c,
            self._evening_decline_max_weather_allowance_mw,
        )

        forecast_rebound_mw = final_before_guard_mw - previous_final_mw
        last_actual_mw = float(context["lastActualMw"])
        actual_reference_mw = last_actual_mw - self._evening_decline_actual_reference_slack_mw
        recent_same_business_mean_mw = self._finite_float(
            row.get("recent_same_business_type_mean")
        )
        mode = "rebound"
        if forecast_rebound_mw > self._evening_decline_min_forecast_rebound_mw:
            reference_mw = max(previous_final_mw, actual_reference_mw)
            cap_mw = (
                reference_mw
                + self._evening_decline_max_rebound_mw
                + weather_allowance_mw
            )
            overhang_mw = final_before_guard_mw - cap_mw
            reduction_mw = min(overhang_mw, self._evening_decline_max_reduction_mw)
        elif self._evening_decline_level_overhang_enabled:
            reference_candidates = [actual_reference_mw]
            if recent_same_business_mean_mw is not None:
                reference_candidates.append(recent_same_business_mean_mw)
            reference_mw = max(reference_candidates)
            cap_mw = (
                reference_mw
                + self._evening_decline_max_rebound_mw
                + weather_allowance_mw
            )
            overhang_mw = final_before_guard_mw - cap_mw
            if overhang_mw < self._evening_decline_min_level_overhang_mw:
                return None
            reduction_mw = min(
                overhang_mw * self._evening_decline_level_overhang_shrinkage,
                self._evening_decline_max_reduction_mw,
            )
            mode = "level_overhang"
        else:
            return None
        if final_before_guard_mw <= cap_mw:
            return None

        reduction_mw = round(float(reduction_mw), 1)
        if reduction_mw < self._evening_decline_min_reduction_mw:
            return None

        return {
            "mode": mode,
            "capMw": round(float(cap_mw), 1),
            "reductionMw": reduction_mw,
            "forecastReboundMw": round(float(forecast_rebound_mw), 1),
            "weatherAllowanceMw": round(float(weather_allowance_mw), 1),
            "lag24DeltaMw": round(float(lag_delta_mw), 1),
            "recentSameBusinessDeltaMw": round(float(same_business_delta_mw), 1),
        }

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
        recovery_damping_factor = self._negative_residual_recovery_damping_factor(
            inference_features,
            actual_mw_by_hour,
            residuals_by_hour,
            last_observed_hour,
            base_adjustment_mw,
        )
        recovery_damping_applied = recovery_damping_factor < 1.0
        if recovery_damping_applied:
            applied_reasons.append("negative_residual_recovery_damping_triggered")

        positive_slope_context = self._positive_residual_slope_damping_context(
            inference_features,
            actual_mw_by_hour,
            residuals_by_hour,
            last_observed_hour,
            base_adjustment_mw,
        )
        morning_positive_context = (
            self._morning_positive_residual_carryover_context(
                transition_prior_guarded_forecasts,
                inference_features,
                actual_mw_by_hour,
                last_observed_hour,
                base_adjustment_mw,
            )
        )
        morning_ramp_context = self._morning_ramp_continuity_context(
            transition_prior_guarded_forecasts,
            inference_features,
            actual_mw_by_hour,
            last_observed_hour,
            base_adjustment_mw,
        )
        morning_warm_context = self._morning_warm_lag_overreaction_context(
            transition_prior_guarded_forecasts,
            inference_features,
            actual_mw_by_hour,
            last_observed_hour,
            base_adjustment_mw,
        )
        morning_anchor_context = self._morning_observed_anchor_cap_context(
            transition_prior_guarded_forecasts,
            inference_features,
            actual_mw_by_hour,
            residuals_by_hour,
            last_observed_hour,
        )
        negative_floor_context = self._negative_residual_continuity_floor_context(
            actual_mw_by_hour,
            last_observed_hour,
        )
        near_negative_floor_context = self._negative_residual_near_term_floor_context(
            actual_mw_by_hour,
            last_observed_hour,
        )
        evening_decline_context = self._evening_decline_continuity_context(
            transition_prior_guarded_forecasts,
            inference_features,
            actual_mw_by_hour,
            last_observed_hour,
        )
        morning_ramp_guard_applied = False
        morning_ramp_restored_values: list[float] = []
        morning_warm_guard_applied = False
        morning_warm_reduced_values: list[float] = []
        morning_anchor_cap_applied = False
        morning_anchor_cap_reduced_values: list[float] = []
        evening_decline_guard_applied = False
        evening_decline_reduced_values: list[float] = []
        negative_floor_applied = False
        negative_floor_restored_values: list[float] = []
        near_negative_floor_applied = False
        near_negative_floor_restored_values: list[float] = []
        positive_slope_damping_applied = False
        positive_slope_damped_values: list[float] = []
        morning_positive_damping_applied = False
        morning_positive_damped_values: list[float] = []
        morning_positive_damping_factor_values: list[float] = []
        residual_adjustment_logs: list[dict] = []
        adjusted_forecasts: list[HourlyForecast] = []
        for forecast in transition_prior_guarded_forecasts:
            forecast_hour = pd.Timestamp(forecast.ts).hour
            if forecast_hour <= last_observed_hour:
                adjusted_forecasts.append(forecast)
                continue

            lead_hours = forecast_hour - last_observed_hour
            adjustment_base_mw = (
                base_adjustment_mw * recovery_damping_factor
                if base_adjustment_mw < 0.0
                else base_adjustment_mw
            )
            decay_multiplier = self._decay_per_hour ** (lead_hours - 1)
            decayed_adjustment_mw = round(adjustment_base_mw * decay_multiplier, 1)
            pre_positive_damping_adjustment_mw = decayed_adjustment_mw
            pre_morning_ramp_adjustment_mw = decayed_adjustment_mw
            positive_mitigation_factor = 1.0
            positive_slope_damping_factor = 1.0
            morning_positive_damping_factor = 1.0
            morning_positive_damped_mw = 0.0
            morning_positive_support_delta_mw = None
            morning_positive_lag24_delta_mw = None
            morning_positive_recent_delta_mw = None
            morning_ramp_restore_mw = 0.0
            morning_ramp_floor_mw = None
            negative_floor_restore_mw = 0.0
            negative_floor_mw = None
            near_negative_floor_restore_mw = 0.0
            near_negative_floor_mw = None
            near_negative_floor_drop_allowance_mw = None
            morning_warm_cap_mw = None
            morning_warm_reduction_mw = 0.0
            morning_warm_temp_delta_24h_c = None
            morning_warm_cooling_delta_24h_c = None
            morning_warm_latest_slope_mw = None
            morning_warm_projected_slope_mw = None
            morning_anchor_cap_mw = None
            morning_anchor_reduction_mw = 0.0
            morning_anchor_cumulative_support_mw = None
            morning_anchor_latest_residual_mw = None
            pre_evening_decline_adjustment_mw = decayed_adjustment_mw
            evening_decline_cap_mw = None
            evening_decline_reduction_mw = 0.0
            evening_decline_forecast_rebound_mw = None
            evening_decline_weather_allowance_mw = None
            evening_decline_mode = None
            if decayed_adjustment_mw > 0.0:
                positive_multiplier = positive_residual_multiplier_by_hour.get(
                    forecast_hour,
                )
                if positive_multiplier is not None:
                    positive_mitigation_factor = positive_multiplier
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
                if (
                    positive_slope_context is not None
                    and lead_hours <= self._positive_slope_max_lead_hours
                    and forecast.forecast_mw + decayed_adjustment_mw
                    > positive_slope_context["referenceLevelMw"]
                    + self._positive_slope_peak_excess_allowance_mw
                ):
                    positive_slope_damping_factor = positive_slope_context["factor"]
                    damped_adjustment_mw = round(
                        decayed_adjustment_mw * positive_slope_damping_factor,
                        1,
                    )
                    if damped_adjustment_mw < decayed_adjustment_mw:
                        positive_slope_damping_applied = True
                        positive_slope_damped_values.append(
                            decayed_adjustment_mw - damped_adjustment_mw,
                        )
                        decayed_adjustment_mw = damped_adjustment_mw
                morning_positive_damping = (
                    self._morning_positive_residual_carryover_damping(
                        morning_positive_context,
                        inference_features,
                        forecast_hour,
                        lead_hours,
                        decayed_adjustment_mw,
                    )
                )
                if morning_positive_damping is not None:
                    damped_adjustment_mw = float(
                        morning_positive_damping["dampedAdjustmentMw"]
                    )
                    if damped_adjustment_mw < decayed_adjustment_mw:
                        morning_positive_damping_factor = float(
                            morning_positive_damping["factor"]
                        )
                        morning_positive_damped_mw = float(
                            morning_positive_damping["dampedMw"]
                        )
                        morning_positive_support_delta_mw = (
                            morning_positive_damping["supportDeltaMw"]
                        )
                        morning_positive_lag24_delta_mw = (
                            morning_positive_damping["lag24DeltaMw"]
                        )
                        morning_positive_recent_delta_mw = (
                            morning_positive_damping[
                                "recentSameBusinessTypeDeltaMw"
                            ]
                        )
                        morning_positive_damping_applied = True
                        morning_positive_damped_values.append(
                            morning_positive_damped_mw
                        )
                        morning_positive_damping_factor_values.append(
                            morning_positive_damping_factor
                        )
                        decayed_adjustment_mw = damped_adjustment_mw
            elif morning_ramp_context is not None:
                if (
                    forecast_hour in self._morning_ramp_target_hours
                    and 0 < lead_hours <= self._morning_ramp_max_lead_hours
                ):
                    floor_delta_mw = (
                        float(morning_ramp_context["floorDeltaMw"])
                        * float(lead_hours)
                    )
                    morning_ramp_floor_mw = (
                        float(morning_ramp_context["lastActualMw"])
                        + floor_delta_mw
                    )
                    final_before_guard_mw = forecast.forecast_mw + decayed_adjustment_mw
                    if final_before_guard_mw < morning_ramp_floor_mw:
                        guarded_final_mw = min(
                            max(final_before_guard_mw, morning_ramp_floor_mw),
                            forecast.forecast_mw,
                        )
                        guarded_adjustment_mw = round(
                            guarded_final_mw - forecast.forecast_mw,
                            1,
                        )
                        restore_mw = max(
                            0.0,
                            guarded_adjustment_mw - decayed_adjustment_mw,
                        )
                        restore_mw = min(
                            restore_mw,
                            self._morning_ramp_max_restore_mw,
                            -decayed_adjustment_mw,
                        )
                        restore_mw = round(float(restore_mw), 1)
                        if restore_mw >= self._morning_ramp_min_restore_mw:
                            decayed_adjustment_mw = round(
                                decayed_adjustment_mw + restore_mw,
                                1,
                            )
                            morning_ramp_restore_mw = restore_mw
                            morning_ramp_guard_applied = True
                            morning_ramp_restored_values.append(restore_mw)
            if decayed_adjustment_mw < 0.0:
                final_before_floor_mw = forecast.forecast_mw + decayed_adjustment_mw
                negative_floor_restore = self._negative_residual_continuity_floor_restore(
                    negative_floor_context,
                    inference_features,
                    forecast_hour,
                    lead_hours,
                    final_before_floor_mw,
                )
                if negative_floor_restore is not None:
                    restore_mw = float(negative_floor_restore["restoreMw"])
                    decayed_adjustment_mw = round(
                        decayed_adjustment_mw + restore_mw,
                        1,
                    )
                    negative_floor_restore_mw = restore_mw
                    negative_floor_mw = negative_floor_restore["floorMw"]
                    negative_floor_applied = True
                    negative_floor_restored_values.append(restore_mw)
                final_before_near_floor_mw = forecast.forecast_mw + decayed_adjustment_mw
                near_negative_floor_restore = self._negative_residual_near_term_floor_restore(
                    near_negative_floor_context,
                    inference_features,
                    forecast_hour,
                    lead_hours,
                    decayed_adjustment_mw,
                    forecast.forecast_mw,
                    final_before_near_floor_mw,
                )
                if near_negative_floor_restore is not None:
                    restore_mw = float(near_negative_floor_restore["restoreMw"])
                    decayed_adjustment_mw = round(
                        decayed_adjustment_mw + restore_mw,
                        1,
                    )
                    near_negative_floor_restore_mw = restore_mw
                    near_negative_floor_mw = near_negative_floor_restore["floorMw"]
                    near_negative_floor_drop_allowance_mw = (
                        near_negative_floor_restore["dropAllowanceMw"]
                    )
                    near_negative_floor_applied = True
                    near_negative_floor_restored_values.append(restore_mw)
            final_before_morning_warm_guard_mw = forecast.forecast_mw + decayed_adjustment_mw
            morning_warm_guard = self._morning_warm_lag_overreaction_reduction(
                morning_warm_context,
                inference_features,
                forecast_hour,
                lead_hours,
                final_before_morning_warm_guard_mw,
            )
            if morning_warm_guard is not None:
                morning_warm_reduction_mw = float(
                    morning_warm_guard["reductionMw"]
                )
                decayed_adjustment_mw = round(
                    decayed_adjustment_mw - morning_warm_reduction_mw,
                    1,
                )
                morning_warm_cap_mw = morning_warm_guard["capMw"]
                morning_warm_temp_delta_24h_c = (
                    morning_warm_guard["tempDelta24hC"]
                )
                morning_warm_cooling_delta_24h_c = (
                    morning_warm_guard["coolingDelta24hC"]
                )
                morning_warm_latest_slope_mw = (
                    morning_warm_guard["latestSlopeMw"]
                )
                morning_warm_projected_slope_mw = (
                    morning_warm_guard["projectedSlopeMw"]
                )
                morning_warm_guard_applied = True
                morning_warm_reduced_values.append(morning_warm_reduction_mw)
            final_before_morning_anchor_cap_mw = (
                forecast.forecast_mw + decayed_adjustment_mw
            )
            morning_anchor_cap = self._morning_observed_anchor_cap_reduction(
                morning_anchor_context,
                inference_features,
                forecast_hour,
                lead_hours,
                final_before_morning_anchor_cap_mw,
            )
            if morning_anchor_cap is not None:
                morning_anchor_reduction_mw = float(
                    morning_anchor_cap["reductionMw"]
                )
                decayed_adjustment_mw = round(
                    decayed_adjustment_mw - morning_anchor_reduction_mw,
                    1,
                )
                morning_anchor_cap_mw = morning_anchor_cap["capMw"]
                morning_anchor_cumulative_support_mw = (
                    morning_anchor_cap["cumulativeSupportMw"]
                )
                morning_anchor_latest_residual_mw = (
                    morning_anchor_cap["latestResidualMw"]
                )
                morning_anchor_cap_applied = True
                morning_anchor_cap_reduced_values.append(
                    morning_anchor_reduction_mw
                )
            pre_evening_decline_adjustment_mw = decayed_adjustment_mw
            previous_final_mw = (
                adjusted_forecasts[-1].forecast_mw
                if adjusted_forecasts
                else None
            )
            final_before_evening_guard_mw = forecast.forecast_mw + decayed_adjustment_mw
            evening_decline_guard = self._evening_decline_continuity_reduction(
                evening_decline_context,
                inference_features,
                forecast_hour,
                lead_hours,
                previous_final_mw,
                final_before_evening_guard_mw,
            )
            if evening_decline_guard is not None:
                evening_decline_reduction_mw = float(
                    evening_decline_guard["reductionMw"]
                )
                decayed_adjustment_mw = round(
                    decayed_adjustment_mw - evening_decline_reduction_mw,
                    1,
                )
                evening_decline_cap_mw = evening_decline_guard["capMw"]
                evening_decline_forecast_rebound_mw = (
                    evening_decline_guard["forecastReboundMw"]
                )
                evening_decline_weather_allowance_mw = (
                    evening_decline_guard["weatherAllowanceMw"]
                )
                evening_decline_mode = evening_decline_guard.get("mode")
                evening_decline_guard_applied = True
                evening_decline_reduced_values.append(evening_decline_reduction_mw)
            residual_adjustment_logs.append({
                "hour": forecast_hour,
                "leadHours": lead_hours,
                "baseAdjustmentMw": round(base_adjustment_mw, 1),
                "effectiveBaseAdjustmentMw": round(adjustment_base_mw, 1),
                "decayMultiplier": round(float(decay_multiplier), 4),
                "prePositiveDampingAdjustmentMw": round(
                    pre_positive_damping_adjustment_mw,
                    1,
                ),
                "preMorningRampContinuityAdjustmentMw": round(
                    pre_morning_ramp_adjustment_mw,
                    1,
                ),
                "positiveResidualMitigationFactor": round(
                    float(positive_mitigation_factor),
                    3,
                ),
                "positiveResidualSlopeDampingFactor": round(
                    float(positive_slope_damping_factor),
                    3,
                ),
                "morningPositiveResidualCarryoverDampingFactor": round(
                    float(morning_positive_damping_factor),
                    3,
                ),
                "morningPositiveResidualCarryoverDampedMw": round(
                    morning_positive_damped_mw,
                    1,
                ),
                "morningPositiveResidualCarryoverSupportDeltaMw": (
                    round(float(morning_positive_support_delta_mw), 1)
                    if morning_positive_support_delta_mw is not None
                    else None
                ),
                "morningPositiveResidualCarryoverLag24DeltaMw": (
                    round(float(morning_positive_lag24_delta_mw), 1)
                    if morning_positive_lag24_delta_mw is not None
                    else None
                ),
                "morningPositiveResidualCarryoverRecentDeltaMw": (
                    round(float(morning_positive_recent_delta_mw), 1)
                    if morning_positive_recent_delta_mw is not None
                    else None
                ),
                "morningRampContinuityFloorMw": (
                    round(float(morning_ramp_floor_mw), 1)
                    if morning_ramp_floor_mw is not None
                    else None
                ),
                "morningRampContinuityRestoreMw": round(
                    morning_ramp_restore_mw,
                    1,
                ),
                "negativeResidualContinuityFloorMw": (
                    round(float(negative_floor_mw), 1)
                    if negative_floor_mw is not None
                    else None
                ),
                "negativeResidualContinuityRestoreMw": round(
                    negative_floor_restore_mw,
                    1,
                ),
                "negativeResidualNearTermFloorMw": (
                    round(float(near_negative_floor_mw), 1)
                    if near_negative_floor_mw is not None
                    else None
                ),
                "negativeResidualNearTermRestoreMw": round(
                    near_negative_floor_restore_mw,
                    1,
                ),
                "negativeResidualNearTermDropAllowanceMw": (
                    round(float(near_negative_floor_drop_allowance_mw), 1)
                    if near_negative_floor_drop_allowance_mw is not None
                    else None
                ),
                "morningWarmLagOverreactionCapMw": (
                    round(float(morning_warm_cap_mw), 1)
                    if morning_warm_cap_mw is not None
                    else None
                ),
                "morningWarmLagOverreactionReductionMw": round(
                    morning_warm_reduction_mw,
                    1,
                ),
                "morningWarmLagOverreactionTempDelta24hC": (
                    round(float(morning_warm_temp_delta_24h_c), 1)
                    if morning_warm_temp_delta_24h_c is not None
                    else None
                ),
                "morningWarmLagOverreactionCoolingDelta24hC": (
                    round(float(morning_warm_cooling_delta_24h_c), 1)
                    if morning_warm_cooling_delta_24h_c is not None
                    else None
                ),
                "morningWarmLagOverreactionLatestSlopeMw": (
                    round(float(morning_warm_latest_slope_mw), 1)
                    if morning_warm_latest_slope_mw is not None
                    else None
                ),
                "morningWarmLagOverreactionProjectedSlopeMw": (
                    round(float(morning_warm_projected_slope_mw), 1)
                    if morning_warm_projected_slope_mw is not None
                    else None
                ),
                "morningObservedAnchorCapMw": (
                    round(float(morning_anchor_cap_mw), 1)
                    if morning_anchor_cap_mw is not None
                    else None
                ),
                "morningObservedAnchorCapReductionMw": round(
                    morning_anchor_reduction_mw,
                    1,
                ),
                "morningObservedAnchorCapCumulativeSupportMw": (
                    round(float(morning_anchor_cumulative_support_mw), 1)
                    if morning_anchor_cumulative_support_mw is not None
                    else None
                ),
                "morningObservedAnchorCapLatestResidualMw": (
                    round(float(morning_anchor_latest_residual_mw), 1)
                    if morning_anchor_latest_residual_mw is not None
                    else None
                ),
                "preEveningDeclineContinuityAdjustmentMw": round(
                    pre_evening_decline_adjustment_mw,
                    1,
                ),
                "eveningDeclineContinuityCapMw": (
                    round(float(evening_decline_cap_mw), 1)
                    if evening_decline_cap_mw is not None
                    else None
                ),
                "eveningDeclineContinuityReductionMw": round(
                    evening_decline_reduction_mw,
                    1,
                ),
                "eveningDeclineContinuityForecastReboundMw": (
                    round(float(evening_decline_forecast_rebound_mw), 1)
                    if evening_decline_forecast_rebound_mw is not None
                    else None
                ),
                "eveningDeclineContinuityWeatherAllowanceMw": (
                    round(float(evening_decline_weather_allowance_mw), 1)
                    if evening_decline_weather_allowance_mw is not None
                    else None
                ),
                "eveningDeclineContinuityMode": evening_decline_mode,
                "finalAdjustmentMw": round(decayed_adjustment_mw, 1),
            })
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
        if positive_slope_damping_applied:
            applied_reasons.append("positive_residual_slope_damping_triggered")
        if morning_positive_damping_applied:
            applied_reasons.append("morning_positive_residual_carryover_damping")
        if morning_ramp_guard_applied:
            applied_reasons.append("morning_ramp_continuity_guard")
        if morning_warm_guard_applied:
            applied_reasons.append("morning_warm_lag_overreaction_guard")
        if morning_anchor_cap_applied:
            applied_reasons.append("morning_observed_anchor_cap")
        if negative_floor_applied:
            applied_reasons.append("negative_residual_continuity_floor")
        if near_negative_floor_applied:
            applied_reasons.append("negative_residual_near_term_floor")
        if evening_decline_guard_applied:
            applied_reasons.append("evening_decline_continuity_guard")

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
            recovery_damping_applied,
            round(recovery_damping_factor, 3),
            positive_slope_damping_applied,
            round(
                float(
                    positive_slope_context["factor"]
                    if positive_slope_damping_applied and positive_slope_context
                    else 1.0
                ),
                3,
            ),
            round(max(positive_slope_damped_values or [0.0]), 1),
            morning_positive_damping_applied,
            round(
                min(morning_positive_damping_factor_values or [1.0]),
                3,
            ),
            round(max(morning_positive_damped_values or [0.0]), 1),
            tuple(residual_adjustment_logs),
            morning_ramp_guard_applied,
            round(max(morning_ramp_restored_values or [0.0]), 1),
            morning_warm_guard_applied,
            round(max(morning_warm_reduced_values or [0.0]), 1),
            evening_decline_guard_applied,
            round(max(evening_decline_reduced_values or [0.0]), 1),
            negative_floor_applied,
            round(max(negative_floor_restored_values or [0.0]), 1),
            near_negative_floor_applied,
            round(max(near_negative_floor_restored_values or [0.0]), 1),
            morning_anchor_cap_applied,
            round(max(morning_anchor_cap_reduced_values or [0.0]), 1),
        )
