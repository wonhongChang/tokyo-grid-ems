"""Post-processing residual correction via analogous past days and time-band guards."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

JST = ZoneInfo("Asia/Tokyo")


def _is_nonworking(d: date) -> bool:
    try:
        import jpholiday
        return d.weekday() >= 5 or bool(jpholiday.is_holiday(d))
    except ImportError:
        return d.weekday() >= 5


class AnalogousDayAdjuster:
    """Shift LGBM q50/q025/q975 forecasts by per-hour mean residuals from analogous past days.

    Analogous days are selected by: same calendar-month neighbourhood, same weekday
    type (weekday vs non-working), similar consecutive-holiday length, and similar
    daytime 7-day temperature anomaly.  Residuals are shrunk and capped before
    application.
    """

    def __init__(self, config: dict) -> None:
        adjustment_config = config.get("adjustment", {})
        self._enabled = bool(adjustment_config.get("enabled", True))
        analog_config = adjustment_config.get("analogous_day", {})
        self._month_window               = int(analog_config.get("month_window", 1))
        self._temp_anomaly_tol           = float(analog_config.get("temp_anomaly_tol", 4.0))
        self._consec_holiday_tol         = int(analog_config.get("consec_holiday_tol", 2))
        self._min_candidates             = int(analog_config.get("min_candidates", 1))
        self._max_candidates             = int(analog_config.get("max_candidates", 5))
        self._same_weekday_required      = bool(analog_config.get("same_weekday_required", False))
        self._weekday_type_required      = bool(analog_config.get("weekday_type_required", True))
        self._shift_shrinkage            = float(analog_config.get("shift_shrinkage", 0.7))
        self._single_candidate_shrinkage = float(analog_config.get("single_candidate_shrinkage", 0.5))
        self._max_abs_shift_mw           = float(analog_config.get("max_abs_shift_mw", 2500.0))
        self._daytime_temp_hours         = set(analog_config.get(
            "daytime_temp_hours", [10, 11, 12, 13, 14, 15, 16, 17]
        ))

    # ------------------------------------------------------------------
    # Candidate search
    # ------------------------------------------------------------------

    def _find_candidates(
        self,
        cache: pd.DataFrame,
        target_date: date,
        target_consecutive_holiday_len: int,
        target_temp_anomaly_7d: float,
        target_is_business_day: bool,
    ) -> list[date]:
        """Return up to max_candidates analogous past dates, most-recent first."""
        from python.forecast.feature_builder import _consec_holiday_len

        actual_rows = cache[cache["actual_mw"].notna()]
        past_dates = sorted(
            candidate_date
            for candidate_date in actual_rows["ts"].dt.date.unique()
            if candidate_date < target_date
        )

        target_month = target_date.month
        candidates: list[date] = []

        for candidate_date in past_dates:
            # Month window (circular across year boundary)
            month_distance = abs(candidate_date.month - target_month)
            if min(month_distance, 12 - month_distance) > self._month_window:
                continue

            # Weekday type
            candidate_is_business_day = not _is_nonworking(candidate_date)
            if (
                self._weekday_type_required
                and candidate_is_business_day != target_is_business_day
            ):
                continue
            if self._same_weekday_required and candidate_date.weekday() != target_date.weekday():
                continue

            # Consecutive holiday length
            candidate_consecutive_holiday_len = _consec_holiday_len(candidate_date)
            if (
                abs(candidate_consecutive_holiday_len - target_consecutive_holiday_len)
                > self._consec_holiday_tol
            ):
                continue

            # Daytime temperature anomaly (skip filter when target anomaly is unknown).
            # This avoids diluting warm afternoon HVAC demand with cool overnight hours.
            if not np.isnan(target_temp_anomaly_7d) and "temp_c" in cache.columns:
                cutoff = pd.Timestamp(
                    candidate_date.year,
                    candidate_date.month,
                    candidate_date.day,
                    tz=JST,
                )
                past_week = cache[
                    (cache["ts"] < cutoff) &
                    (cache["ts"] >= cutoff - pd.Timedelta(hours=168)) &
                    (cache["ts"].dt.hour.isin(self._daytime_temp_hours))
                ]["temp_c"].dropna()
                if len(past_week) >= len(self._daytime_temp_hours):
                    candidate_day_temps = cache[
                        (cache["ts"].dt.date == candidate_date) &
                        (cache["ts"].dt.hour.isin(self._daytime_temp_hours))
                    ]["temp_c"].dropna()
                    if len(candidate_day_temps) == 0:
                        continue
                    candidate_temp_anomaly_7d = (
                        float(candidate_day_temps.mean()) - float(past_week.mean())
                    )
                    if (
                        abs(candidate_temp_anomaly_7d - target_temp_anomaly_7d)
                        > self._temp_anomaly_tol
                    ):
                        continue

            # Need at least 12 actual readings
            if len(actual_rows[actual_rows["ts"].dt.date == candidate_date]) < 12:
                continue

            candidates.append(candidate_date)

        # Most recent first, capped at max_candidates
        return sorted(candidates, reverse=True)[: self._max_candidates]

    # ------------------------------------------------------------------
    # Adjust
    # ------------------------------------------------------------------

    def adjust(
        self,
        forecaster,
        raw_forecasts: list,
        cache: pd.DataFrame,
        target_date: date,
        inference_features: pd.DataFrame,
    ) -> list:
        """Return corrected forecasts (same structure as raw_forecasts).

        Falls through unchanged when adjustment is disabled, forecaster is None,
        raw_forecasts is empty, or too few analogous days are found.
        """
        if not self._enabled or forecaster is None or not raw_forecasts:
            return raw_forecasts

        row0 = inference_features.iloc[0]
        target_consecutive_holiday_len = int(row0["consec_holiday_len"])
        if "daytime_temp_anomaly_7d" in inference_features.columns:
            target_temp_anomaly_7d = float(
                np.nanmean(inference_features["daytime_temp_anomaly_7d"].values)
            )
        else:
            daytime_rows = inference_features[
                inference_features["hour"].isin(self._daytime_temp_hours)
            ]
            target_temp_anomaly_7d = float(
                np.nanmean(daytime_rows["temp_anomaly_7d"].values)
            )
        target_is_business_day = bool(row0["is_non_business_day"] == 0)

        candidates = self._find_candidates(
            cache,
            target_date,
            target_consecutive_holiday_len,
            target_temp_anomaly_7d,
            target_is_business_day,
        )
        if len(candidates) < self._min_candidates:
            return raw_forecasts

        # Compute per-hour residuals (actual − q50 prediction) for each candidate
        hour_residuals: dict[int, list[float]] = {h: [] for h in range(24)}
        actual_rows = cache[cache["actual_mw"].notna()]

        for candidate_date in candidates:
            try:
                candidate_forecasts = forecaster.predict(candidate_date, cache)
            except Exception as e:
                print(
                    f"[WARN] AnalogousDayAdjuster: predict failed for {candidate_date}: {e}",
                    file=sys.stderr,
                )
                continue

            # hour → q50 from candidate forecast
            candidate_forecast_by_hour: dict[int, float] = {
                pd.Timestamp(forecast.ts).hour: forecast.forecast_mw
                for forecast in candidate_forecasts
            }

            # hour → actual_mw from cache
            day_rows = actual_rows[actual_rows["ts"].dt.date == candidate_date]
            for _, row in day_rows.iterrows():
                hour = int(row["ts"].hour)
                if hour in candidate_forecast_by_hour:
                    hour_residuals[hour].append(
                        float(row["actual_mw"]) - candidate_forecast_by_hour[hour]
                    )

        # Choose shrinkage based on how many candidates contributed
        candidate_count = len(candidates)
        shrinkage = (
            self._single_candidate_shrinkage if candidate_count == 1 else self._shift_shrinkage
        )

        hour_shift: dict[int, float] = {}
        for hour in range(24):
            residuals = hour_residuals[hour]
            if not residuals:
                hour_shift[hour] = 0.0
            else:
                raw_shift = float(np.mean(residuals)) * shrinkage
                hour_shift[hour] = float(
                    np.clip(raw_shift, -self._max_abs_shift_mw, self._max_abs_shift_mw)
                )

        # Apply uniform hour-level shift to all quantile bands
        from python.forecast.baseline import HourlyForecast

        corrected = []
        for forecast in raw_forecasts:
            shift = hour_shift.get(pd.Timestamp(forecast.ts).hour, 0.0)
            corrected.append(HourlyForecast(
                ts=forecast.ts,
                forecast_mw=round(forecast.forecast_mw + shift, 1),
                p95_lower_mw=round(forecast.p95_lower_mw + shift, 1),
                p95_upper_mw=round(forecast.p95_upper_mw + shift, 1),
                p99_lower_mw=round(forecast.p99_lower_mw + shift, 1),
                p99_upper_mw=round(forecast.p99_upper_mw + shift, 1),
            ))
        return corrected


# ---------------------------------------------------------------------------
# PostHolidayTimeBandGuard
# ---------------------------------------------------------------------------

class PostHolidayTimeBandGuard:
    """Prevent AnalogousDayAdjuster from shifting in the wrong direction.

    Two regimes for the first business day after a long holiday (consec_holiday_len >= 3):
    - Early morning (default 1-6h): actual demand tends to be LOWER than predicted;
      block any positive adjuster shift so it cannot worsen overnight overestimation.
    - Daytime (default 10-18h, only when temp_anomaly_7d >= threshold): actual demand
      tends to be HIGHER than predicted; block any negative adjuster shift so it cannot
      worsen midday underestimation.
    The daytime guard also applies when the same-hour 168h lag comes from a holiday or
    weekend, because that lag can pull a warm business-afternoon forecast too low.
    It can also apply a smaller ordinary warm-day offset when current temperature is
    high relative to recent/seasonal references, covering hot business days without
    holiday-lag contamination.

    Offset values are 0 by default (block-only).  Set downward_offset_mw /
    upward_offset_mw in config when empirical calibration warrants it.
    """

    def __init__(self, config: dict) -> None:
        adjustment_config = config.get("adjustment", {})
        guard_config = adjustment_config.get("post_holiday_timeband_guard", {})
        self._enabled     = bool(guard_config.get("enabled", True))
        self._min_consec  = int(guard_config.get("min_consec_holiday_len", 3))
        self._max_dsh     = int(guard_config.get("max_days_since_holiday_end", 1))

        early_morning_config = guard_config.get("early_morning", {})
        self._em_hours      = set(early_morning_config.get("hours", [1, 2, 3, 4, 5, 6]))
        self._em_block_pos  = bool(early_morning_config.get("block_positive_shift", True))
        self._em_offset     = float(early_morning_config.get("downward_offset_mw", 0.0))
        self._em_max_offset = float(early_morning_config.get("max_downward_offset_mw", 600.0))

        daytime_config = guard_config.get("daytime", {})
        self._dt_hours = set(
            daytime_config.get("hours", [10, 11, 12, 13, 14, 15, 16, 17, 18])
        )
        self._dt_min_anomaly = float(daytime_config.get("min_temp_anomaly_7d", 2.0))
        self._dt_block_neg   = bool(daytime_config.get("block_negative_shift", True))
        self._dt_offset      = float(daytime_config.get("upward_offset_mw", 0.0))
        self._dt_max_offset  = float(daytime_config.get("max_upward_offset_mw", 900.0))
        self._activate_on_holiday_lag = bool(daytime_config.get("activate_on_holiday_lag", True))
        self._activate_on_warm_day = bool(daytime_config.get("activate_on_warm_day", False))
        self._warm_day_min_anomaly_doy = float(
            daytime_config.get("warm_day_min_temp_anomaly_doy", 1.0)
        )
        self._warm_day_offset = float(daytime_config.get("warm_day_upward_offset_mw", 0.0))
        self._lag24_warm_day_cap_enabled = bool(
            daytime_config.get("lag24_warm_day_cap_enabled", False)
        )
        self._lag24_warm_day_max_increase_mw = float(
            daytime_config.get("lag24_warm_day_max_increase_mw", 2500.0)
        )
        warm_day_decline_config = daytime_config.get("warm_day_decline_damping", {})
        self._warm_day_decline_enabled = bool(
            warm_day_decline_config.get("enabled", True)
        )
        self._warm_day_decline_hours = {
            int(hour)
            for hour in warm_day_decline_config.get("hours", [15, 16, 17, 18, 19])
        }
        self._warm_day_decline_max_same_business_delta_mw = float(
            warm_day_decline_config.get("max_same_business_delta_mw", 0.0)
        )
        self._warm_day_decline_max_lag24_delta_mw = float(
            warm_day_decline_config.get("max_lag24_delta_mw", 500.0)
        )
        self._warm_day_decline_offset_multiplier = min(
            max(
                float(warm_day_decline_config.get("offset_multiplier", 0.0)),
                0.0,
            ),
            1.0,
        )
        self._warm_day_decline_allow_negative_analog_shift = bool(
            warm_day_decline_config.get("allow_negative_analog_shift", True)
        )
        business_return_config = guard_config.get("business_return_anchor_shortfall", {})
        self._business_return_enabled = bool(
            business_return_config.get("enabled", True)
        )
        self._business_return_hours: set[int] = set()
        for hour in business_return_config.get("target_hours", [6, 7, 8, 9, 10, 11]):
            try:
                self._business_return_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._business_return_gap_threshold_mw = float(
            business_return_config.get("gap_threshold_mw", 6_000.0)
        )
        self._business_return_allowance_mw = float(
            business_return_config.get("allowance_mw", 1_000.0)
        )
        self._business_return_max_clipping_mw = float(
            business_return_config.get("max_clipping_mw", 1_000.0)
        )
        self._business_return_min_shape_shortfall_mw = max(
            float(business_return_config.get("min_shape_shortfall_mw", 800.0)),
            0.0,
        )
        raw_shrinkage_map = business_return_config.get(
            "shrinkage_map",
            {6: 0.25, 7: 0.35, 8: 0.45, 9: 0.50, 10: 0.30, 11: 0.20},
        )
        self._business_return_shrinkage_by_hour: dict[int, float] = {}
        shrinkage_items = (
            raw_shrinkage_map.items()
            if hasattr(raw_shrinkage_map, "items")
            else []
        )
        for hour, shrinkage in shrinkage_items:
            try:
                self._business_return_shrinkage_by_hour[int(hour)] = float(shrinkage)
            except (TypeError, ValueError):
                continue
        business_return_excess_config = guard_config.get(
            "business_return_anchor_excess_cap",
            {},
        )
        self._business_return_excess_enabled = bool(
            business_return_excess_config.get("enabled", True)
        )
        self._business_return_excess_hours: set[int] = set()
        for hour in business_return_excess_config.get("target_hours", [8, 9, 10, 11]):
            try:
                self._business_return_excess_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._business_return_excess_gap_threshold_mw = float(
            business_return_excess_config.get("gap_threshold_mw", 1_000.0)
        )
        self._business_return_excess_allowance_mw = float(
            business_return_excess_config.get("allowance_mw", 500.0)
        )
        self._business_return_excess_weather_allowance_mw_per_c = max(
            float(
                business_return_excess_config.get(
                    "weather_allowance_mw_per_c",
                    100.0,
                )
            ),
            0.0,
        )
        self._business_return_excess_max_weather_allowance_mw = max(
            float(
                business_return_excess_config.get(
                    "max_weather_allowance_mw",
                    300.0,
                )
            ),
            0.0,
        )
        self._business_return_excess_shrinkage = min(
            max(float(business_return_excess_config.get("shrinkage", 0.6)), 0.0),
            1.0,
        )
        self._business_return_excess_max_clipping_mw = float(
            business_return_excess_config.get("max_clipping_mw", 900.0)
        )
        self._business_return_excess_shape_supported_hours: set[int] = set()
        for hour in business_return_excess_config.get("shape_supported_hours", [9, 10, 11]):
            try:
                self._business_return_excess_shape_supported_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._business_return_excess_strong_shape_delta_mw = float(
            business_return_excess_config.get("strong_shape_support_delta_mw", 700.0)
        )
        self._business_return_excess_shape_allowance_fraction = max(
            float(
                business_return_excess_config.get(
                    "shape_support_allowance_fraction",
                    0.35,
                )
            ),
            0.0,
        )
        self._business_return_excess_max_shape_allowance_mw = max(
            float(
                business_return_excess_config.get(
                    "max_shape_support_allowance_mw",
                    650.0,
                )
            ),
            0.0,
        )
        self._business_return_excess_supported_shrinkage = min(
            max(
                float(
                    business_return_excess_config.get(
                        "supported_shrinkage",
                        0.25,
                    )
                ),
                0.0,
            ),
            1.0,
        )
        afternoon_analog_config = guard_config.get(
            "business_afternoon_analog_excess_cap",
            {},
        )
        self._business_afternoon_analog_enabled = bool(
            afternoon_analog_config.get("enabled", True)
        )
        self._business_afternoon_analog_hours: set[int] = set()
        for hour in afternoon_analog_config.get("target_hours", [13, 14, 15, 16]):
            try:
                self._business_afternoon_analog_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._business_afternoon_analog_min_shift_mw = max(
            float(afternoon_analog_config.get("min_positive_shift_mw", 600.0)),
            0.0,
        )
        self._business_afternoon_analog_max_support_delta_mw = float(
            afternoon_analog_config.get("max_supporting_delta_mw", 900.0)
        )
        self._business_afternoon_analog_max_allowed_shift_mw = max(
            float(afternoon_analog_config.get("max_allowed_shift_mw", 300.0)),
            0.0,
        )
        self._business_afternoon_analog_min_weather_delta_c = max(
            float(afternoon_analog_config.get("min_weather_delta_c", 0.5)),
            0.0,
        )
        self._business_afternoon_analog_weather_allowance_mw_per_c = max(
            float(
                afternoon_analog_config.get(
                    "weather_allowance_mw_per_c",
                    120.0,
                )
            ),
            0.0,
        )
        self._business_afternoon_analog_max_weather_allowance_mw = max(
            float(
                afternoon_analog_config.get(
                    "max_weather_allowance_mw",
                    300.0,
                )
            ),
            0.0,
        )
        afternoon_downshift_config = guard_config.get(
            "business_afternoon_analog_downshift_guard",
            {},
        )
        self._business_afternoon_downshift_enabled = bool(
            afternoon_downshift_config.get("enabled", True)
        )
        self._business_afternoon_downshift_hours: set[int] = set()
        for hour in afternoon_downshift_config.get("target_hours", [13, 14, 15, 16]):
            try:
                self._business_afternoon_downshift_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._business_afternoon_downshift_min_shift_mw = max(
            float(afternoon_downshift_config.get("min_negative_shift_mw", 600.0)),
            0.0,
        )
        self._business_afternoon_downshift_max_downshift_mw = max(
            float(
                afternoon_downshift_config.get(
                    "max_allowed_downshift_mw",
                    300.0,
                )
            ),
            0.0,
        )
        self._business_afternoon_downshift_min_weather_delta_c = max(
            float(afternoon_downshift_config.get("min_weather_delta_c", 0.5)),
            0.0,
        )
        self._business_afternoon_downshift_min_supporting_delta_mw = float(
            afternoon_downshift_config.get("min_supporting_delta_mw", -700.0)
        )
        self._business_afternoon_downshift_max_raw_anchor_excess_mw = float(
            afternoon_downshift_config.get("max_raw_anchor_excess_mw", 900.0)
        )
        non_business_analog_config = guard_config.get(
            "non_business_analog_downshift_guard",
            {},
        )
        self._non_business_analog_guard_enabled = bool(
            non_business_analog_config.get("enabled", True)
        )
        self._non_business_analog_guard_hours: set[int] = set()
        for hour in non_business_analog_config.get(
            "target_hours",
            [7, 8, 9, 10, 11, 12, 13, 14, 15],
        ):
            try:
                self._non_business_analog_guard_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._non_business_analog_min_downshift_mw = max(
            float(non_business_analog_config.get("min_negative_shift_mw", 1.0)),
            0.0,
        )
        self._non_business_analog_max_downshift_mw = max(
            float(non_business_analog_config.get("max_allowed_downshift_mw", 0.0)),
            0.0,
        )
        self._non_business_analog_min_supporting_delta_mw = float(
            non_business_analog_config.get("min_supporting_delta_mw", 500.0)
        )
        self._non_business_analog_max_raw_anchor_excess_mw = float(
            non_business_analog_config.get("max_raw_anchor_excess_mw", 900.0)
        )
        morning_shape_config = guard_config.get(
            "non_business_morning_shape_floor_guard",
            {},
        )
        self._non_business_morning_shape_enabled = bool(
            morning_shape_config.get("enabled", True)
        )
        self._non_business_morning_shape_hours: set[int] = set()
        for hour in morning_shape_config.get("target_hours", [6, 7]):
            try:
                self._non_business_morning_shape_hours.add(int(hour))
            except (TypeError, ValueError):
                continue
        self._non_business_morning_shape_min_shortfall_mw = max(
            float(morning_shape_config.get("min_shape_shortfall_mw", 700.0)),
            0.0,
        )
        self._non_business_morning_shape_support_slack_mw = max(
            float(morning_shape_config.get("support_slack_mw", 250.0)),
            0.0,
        )
        self._non_business_morning_shape_shrinkage = min(
            max(float(morning_shape_config.get("shrinkage", 0.75)), 0.0),
            1.0,
        )
        self._non_business_morning_shape_max_lift_mw = max(
            float(morning_shape_config.get("max_lift_mw", 800.0)),
            0.0,
        )
        self._non_business_morning_shape_min_lift_mw = max(
            float(morning_shape_config.get("min_lift_mw", 100.0)),
            0.0,
        )

    @staticmethod
    def _shift_forecast(forecast, shift_mw: float):
        from python.forecast.baseline import HourlyForecast

        return HourlyForecast(
            ts=forecast.ts,
            forecast_mw=round(forecast.forecast_mw + shift_mw, 1),
            p95_lower_mw=round(forecast.p95_lower_mw + shift_mw, 1),
            p95_upper_mw=round(forecast.p95_upper_mw + shift_mw, 1),
            p99_lower_mw=round(forecast.p99_lower_mw + shift_mw, 1),
            p99_upper_mw=round(forecast.p99_upper_mw + shift_mw, 1),
        )

    @staticmethod
    def _finite_float(value) -> float | None:
        if value is None or pd.isna(value):
            return None
        parsed = float(value)
        if not np.isfinite(parsed):
            return None
        return parsed

    def _cap_warm_day_lag24_increase(self, forecast, row, active: bool):
        if not (self._lag24_warm_day_cap_enabled and active):
            return forecast
        business_type_mismatch = (
            float(row.get("lag_24h_business_type_mismatch"))
            if pd.notna(row.get("lag_24h_business_type_mismatch"))
            else 0.0
        )
        if business_type_mismatch > 0.0:
            return forecast
        lag_24h = float(row["lag_24h"]) if pd.notna(row.get("lag_24h")) else np.nan
        if np.isnan(lag_24h):
            return forecast
        max_forecast_mw = lag_24h + self._lag24_warm_day_max_increase_mw
        if forecast.forecast_mw <= max_forecast_mw:
            return forecast
        return self._shift_forecast(forecast, max_forecast_mw - forecast.forecast_mw)

    def _warm_day_decline_damping_active(self, hour: int, row) -> bool:
        if not (
            self._warm_day_decline_enabled
            and hour in self._warm_day_decline_hours
        ):
            return False
        same_business_delta = self._finite_float(
            row.get("recent_same_business_type_delta_mean")
        )
        lag24_delta = self._finite_float(row.get("lag_24h_hourly_delta"))
        if same_business_delta is None or lag24_delta is None:
            return False
        return (
            same_business_delta <= self._warm_day_decline_max_same_business_delta_mw
            and lag24_delta <= self._warm_day_decline_max_lag24_delta_mw
        )

    def _business_return_shortfall_may_apply(
        self,
        inference_features: pd.DataFrame,
    ) -> bool:
        if (
            not self._business_return_enabled
            or not self._business_return_hours
            or inference_features is None
            or inference_features.empty
            or "hour" not in inference_features.columns
        ):
            return False

        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is None or int(hour) not in self._business_return_hours:
                continue
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            if is_non_business_day == 0.0 and mismatch is not None and mismatch > 0.0:
                return True
        return False

    def _business_return_shape_shortfall_mw(
        self,
        forecast,
        row,
        forecasts_by_hour: dict[int, object],
    ) -> float | None:
        if self._business_return_min_shape_shortfall_mw <= 0.0:
            return None
        hour = pd.Timestamp(forecast.ts).hour
        previous_forecast = forecasts_by_hour.get(hour - 1)
        if previous_forecast is None:
            return None
        recent_delta_mw = self._finite_float(
            row.get("recent_same_business_type_delta_mean")
        )
        forecast_mw = self._finite_float(forecast.forecast_mw)
        previous_forecast_mw = self._finite_float(previous_forecast.forecast_mw)
        if (
            recent_delta_mw is None
            or forecast_mw is None
            or previous_forecast_mw is None
        ):
            return None
        forecast_delta_mw = forecast_mw - previous_forecast_mw
        return recent_delta_mw - forecast_delta_mw

    def _apply_business_return_anchor_shortfall(
        self,
        forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        if not self._business_return_shortfall_may_apply(inference_features):
            return forecasts

        rows_by_hour = {}
        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is not None:
                rows_by_hour[int(hour)] = row

        forecasts_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        result = []
        changed = False
        for forecast in forecasts:
            hour = pd.Timestamp(forecast.ts).hour
            row = rows_by_hour.get(hour)
            shrinkage = self._business_return_shrinkage_by_hour.get(hour)
            if row is None or shrinkage is None:
                result.append(forecast)
                continue

            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            if is_non_business_day != 0.0 or mismatch is None or mismatch <= 0.0:
                result.append(forecast)
                continue

            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
            lag_24h = self._finite_float(row.get("lag_24h"))
            forecast_mw = self._finite_float(forecast.forecast_mw)
            if recent_mean is None or lag_24h is None or forecast_mw is None:
                result.append(forecast)
                continue

            gap_mw = recent_mean - lag_24h
            if gap_mw < self._business_return_gap_threshold_mw:
                result.append(forecast)
                continue

            shape_shortfall_mw = self._business_return_shape_shortfall_mw(
                forecast,
                row,
                forecasts_by_hour,
            )
            if (
                shape_shortfall_mw is not None
                and shape_shortfall_mw < self._business_return_min_shape_shortfall_mw
            ):
                result.append(forecast)
                continue

            lower_bound_mw = recent_mean - self._business_return_allowance_mw
            if forecast_mw >= lower_bound_mw:
                result.append(forecast)
                continue

            shortfall_mw = lower_bound_mw - forecast_mw
            adjustment_mw = min(
                shortfall_mw * shrinkage,
                self._business_return_max_clipping_mw,
            )
            if adjustment_mw <= 0.0:
                result.append(forecast)
                continue

            result.append(self._shift_forecast(forecast, adjustment_mw))
            changed = True

        return result if changed else forecasts

    def _business_return_excess_may_apply(
        self,
        inference_features: pd.DataFrame,
    ) -> bool:
        if (
            not self._business_return_excess_enabled
            or not self._business_return_excess_hours
            or inference_features is None
            or inference_features.empty
            or "hour" not in inference_features.columns
        ):
            return False

        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is None or int(hour) not in self._business_return_excess_hours:
                continue
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            if is_non_business_day == 0.0 and mismatch is not None and mismatch > 0.0:
                return True
        return False

    def _business_return_weather_allowance_mw(self, row) -> float:
        weather_delta_c = max(
            0.0,
            self._finite_float(row.get("temp_delta_24h")) or 0.0,
            self._finite_float(row.get("cooling_delta_24h")) or 0.0,
            self._finite_float(row.get("temp_anomaly_doy")) or 0.0,
        )
        return min(
            weather_delta_c * self._business_return_excess_weather_allowance_mw_per_c,
            self._business_return_excess_max_weather_allowance_mw,
        )

    def _business_return_shape_support(self, hour: int, row) -> tuple[float, float]:
        if hour not in self._business_return_excess_shape_supported_hours:
            return 0.0, self._business_return_excess_shrinkage

        support_candidates = [
            value
            for value in (
                self._finite_float(row.get("lag_24h_hourly_delta")),
                self._finite_float(row.get("recent_same_business_type_delta_mean")),
            )
            if value is not None
        ]
        if not support_candidates:
            return 0.0, self._business_return_excess_shrinkage

        support_delta_mw = max(support_candidates)
        if support_delta_mw < self._business_return_excess_strong_shape_delta_mw:
            return 0.0, self._business_return_excess_shrinkage

        support_allowance_mw = min(
            support_delta_mw * self._business_return_excess_shape_allowance_fraction,
            self._business_return_excess_max_shape_allowance_mw,
        )
        return support_allowance_mw, self._business_return_excess_supported_shrinkage

    def _apply_business_return_anchor_excess_cap(
        self,
        forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        if not self._business_return_excess_may_apply(inference_features):
            return forecasts

        rows_by_hour = {}
        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is not None:
                rows_by_hour[int(hour)] = row

        result = []
        changed = False
        for forecast in forecasts:
            hour = pd.Timestamp(forecast.ts).hour
            row = rows_by_hour.get(hour)
            if row is None or hour not in self._business_return_excess_hours:
                result.append(forecast)
                continue

            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            mismatch = self._finite_float(row.get("lag_24h_business_type_mismatch"))
            if is_non_business_day != 0.0 or mismatch is None or mismatch <= 0.0:
                result.append(forecast)
                continue

            recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
            lag_24h = self._finite_float(row.get("lag_24h"))
            forecast_mw = self._finite_float(forecast.forecast_mw)
            if recent_mean is None or lag_24h is None or forecast_mw is None:
                result.append(forecast)
                continue

            gap_mw = recent_mean - lag_24h
            if gap_mw < self._business_return_excess_gap_threshold_mw:
                result.append(forecast)
                continue

            upper_bound_mw = (
                recent_mean
                + self._business_return_excess_allowance_mw
                + self._business_return_weather_allowance_mw(row)
            )
            shape_allowance_mw, shrinkage = self._business_return_shape_support(
                hour,
                row,
            )
            upper_bound_mw += shape_allowance_mw
            if forecast_mw <= upper_bound_mw:
                result.append(forecast)
                continue

            excess_mw = forecast_mw - upper_bound_mw
            reduction_mw = min(
                excess_mw * shrinkage,
                self._business_return_excess_max_clipping_mw,
            )
            if reduction_mw <= 0.0:
                result.append(forecast)
                continue

            result.append(self._shift_forecast(forecast, -reduction_mw))
            changed = True

        return result if changed else forecasts

    def _business_afternoon_analog_may_apply(
        self,
        inference_features: pd.DataFrame,
    ) -> bool:
        if (
            not self._business_afternoon_analog_enabled
            or not self._business_afternoon_analog_hours
            or inference_features is None
            or inference_features.empty
            or "hour" not in inference_features.columns
        ):
            return False

        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is None or int(hour) not in self._business_afternoon_analog_hours:
                continue
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if (
                is_non_business_day == 0.0
                and self._business_afternoon_analog_weather_delta_c(row)
                >= self._business_afternoon_analog_min_weather_delta_c
            ):
                return True
        return False

    def _business_afternoon_analog_weather_allowance_mw(self, row) -> float:
        weather_delta_c = max(
            0.0,
            self._finite_float(row.get("temp_delta_24h")) or 0.0,
            self._finite_float(row.get("cooling_delta_24h")) or 0.0,
            self._finite_float(row.get("apparent_cooling_delta_24h")) or 0.0,
        )
        return min(
            weather_delta_c * self._business_afternoon_analog_weather_allowance_mw_per_c,
            self._business_afternoon_analog_max_weather_allowance_mw,
        )

    def _business_afternoon_analog_weather_delta_c(self, row) -> float:
        return max(
            0.0,
            self._finite_float(row.get("temp_delta_24h")) or 0.0,
            self._finite_float(row.get("cooling_delta_24h")) or 0.0,
            self._finite_float(row.get("apparent_cooling_delta_24h")) or 0.0,
        )

    def _apply_business_afternoon_analog_excess_cap(
        self,
        raw_forecasts: list,
        adjusted_forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        if not self._business_afternoon_analog_may_apply(inference_features):
            return adjusted_forecasts

        rows_by_hour = {}
        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is not None:
                rows_by_hour[int(hour)] = row

        result = []
        changed = False
        for raw_forecast, adjusted_forecast in zip(raw_forecasts, adjusted_forecasts):
            hour = pd.Timestamp(raw_forecast.ts).hour
            row = rows_by_hour.get(hour)
            if row is None or hour not in self._business_afternoon_analog_hours:
                result.append(adjusted_forecast)
                continue

            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day != 0.0:
                result.append(adjusted_forecast)
                continue

            shift_mw = adjusted_forecast.forecast_mw - raw_forecast.forecast_mw
            if shift_mw < self._business_afternoon_analog_min_shift_mw:
                result.append(adjusted_forecast)
                continue
            weather_delta_c = self._business_afternoon_analog_weather_delta_c(row)
            if weather_delta_c < self._business_afternoon_analog_min_weather_delta_c:
                result.append(adjusted_forecast)
                continue

            support_candidates = [
                value
                for value in (
                    self._finite_float(row.get("lag_24h_hourly_delta")),
                    self._finite_float(row.get("recent_same_business_type_delta_mean")),
                )
                if value is not None
            ]
            if (
                support_candidates
                and max(support_candidates)
                > self._business_afternoon_analog_max_support_delta_mw
            ):
                result.append(adjusted_forecast)
                continue

            allowed_shift_mw = (
                self._business_afternoon_analog_max_allowed_shift_mw
                + self._business_afternoon_analog_weather_allowance_mw(row)
            )
            if shift_mw <= allowed_shift_mw:
                result.append(adjusted_forecast)
                continue

            result.append(self._shift_forecast(raw_forecast, allowed_shift_mw))
            changed = True

        return result if changed else adjusted_forecasts

    def _business_afternoon_downshift_may_apply(
        self,
        inference_features: pd.DataFrame,
    ) -> bool:
        if (
            not self._business_afternoon_downshift_enabled
            or not self._business_afternoon_downshift_hours
            or inference_features is None
            or inference_features.empty
            or "hour" not in inference_features.columns
        ):
            return False

        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is None or int(hour) not in self._business_afternoon_downshift_hours:
                continue
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if (
                is_non_business_day == 0.0
                and self._business_afternoon_analog_weather_delta_c(row)
                >= self._business_afternoon_downshift_min_weather_delta_c
            ):
                return True
        return False

    def _business_afternoon_downshift_supported(self, row, raw_forecast) -> bool:
        support_candidates = [
            value
            for value in (
                self._finite_float(row.get("lag_24h_hourly_delta")),
                self._finite_float(row.get("recent_same_business_type_delta_mean")),
            )
            if value is not None
        ]
        if (
            support_candidates
            and max(support_candidates)
            < self._business_afternoon_downshift_min_supporting_delta_mw
        ):
            return False

        recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
        raw_mw = self._finite_float(raw_forecast.forecast_mw)
        if recent_mean is None or raw_mw is None:
            return True
        return raw_mw <= (
            recent_mean + self._business_afternoon_downshift_max_raw_anchor_excess_mw
        )

    def _apply_business_afternoon_analog_downshift_guard(
        self,
        raw_forecasts: list,
        adjusted_forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        if not self._business_afternoon_downshift_may_apply(inference_features):
            return adjusted_forecasts

        rows_by_hour = {}
        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is not None:
                rows_by_hour[int(hour)] = row

        result = []
        changed = False
        for raw_forecast, adjusted_forecast in zip(raw_forecasts, adjusted_forecasts):
            hour = pd.Timestamp(raw_forecast.ts).hour
            row = rows_by_hour.get(hour)
            if row is None or hour not in self._business_afternoon_downshift_hours:
                result.append(adjusted_forecast)
                continue

            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day != 0.0:
                result.append(adjusted_forecast)
                continue

            shift_mw = adjusted_forecast.forecast_mw - raw_forecast.forecast_mw
            if shift_mw >= -self._business_afternoon_downshift_min_shift_mw:
                result.append(adjusted_forecast)
                continue
            if self._business_afternoon_analog_weather_delta_c(
                row
            ) < self._business_afternoon_downshift_min_weather_delta_c:
                result.append(adjusted_forecast)
                continue
            if not self._business_afternoon_downshift_supported(row, raw_forecast):
                result.append(adjusted_forecast)
                continue

            guarded_shift_mw = -self._business_afternoon_downshift_max_downshift_mw
            if guarded_shift_mw <= shift_mw:
                result.append(adjusted_forecast)
                continue

            result.append(self._shift_forecast(raw_forecast, guarded_shift_mw))
            changed = True

        return result if changed else adjusted_forecasts

    def _non_business_analog_downshift_may_apply(
        self,
        inference_features: pd.DataFrame,
    ) -> bool:
        if (
            not self._non_business_analog_guard_enabled
            or not self._non_business_analog_guard_hours
            or inference_features is None
            or inference_features.empty
            or "hour" not in inference_features.columns
        ):
            return False

        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is None or int(hour) not in self._non_business_analog_guard_hours:
                continue
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day == 1.0:
                return True
        return False

    def _non_business_morning_shape_floor_may_apply(
        self,
        inference_features: pd.DataFrame,
    ) -> bool:
        if (
            not self._non_business_morning_shape_enabled
            or not self._non_business_morning_shape_hours
            or inference_features is None
            or inference_features.empty
            or "hour" not in inference_features.columns
        ):
            return False

        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is None or int(hour) not in self._non_business_morning_shape_hours:
                continue
            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day == 1.0:
                return True
        return False

    def _non_business_analog_downshift_supported(self, row, raw_forecast) -> bool:
        lag_delta_mw = self._finite_float(row.get("lag_24h_hourly_delta"))
        same_business_delta_mw = self._finite_float(
            row.get("recent_same_business_type_delta_mean")
        )
        support_candidates = [
            value
            for value in (lag_delta_mw, same_business_delta_mw)
            if value is not None
        ]
        if (
            support_candidates
            and max(support_candidates) >= self._non_business_analog_min_supporting_delta_mw
        ):
            return True

        recent_mean = self._finite_float(row.get("recent_same_business_type_mean"))
        raw_mw = self._finite_float(raw_forecast.forecast_mw)
        if recent_mean is None or raw_mw is None:
            return False
        return raw_mw <= recent_mean + self._non_business_analog_max_raw_anchor_excess_mw

    def _apply_non_business_analog_downshift_guard(
        self,
        raw_forecasts: list,
        adjusted_forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        if not self._non_business_analog_downshift_may_apply(inference_features):
            return adjusted_forecasts

        rows_by_hour = {}
        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is not None:
                rows_by_hour[int(hour)] = row

        result = []
        changed = False
        for raw_forecast, adjusted_forecast in zip(raw_forecasts, adjusted_forecasts):
            hour = pd.Timestamp(raw_forecast.ts).hour
            row = rows_by_hour.get(hour)
            if row is None or hour not in self._non_business_analog_guard_hours:
                result.append(adjusted_forecast)
                continue

            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day != 1.0:
                result.append(adjusted_forecast)
                continue

            shift_mw = adjusted_forecast.forecast_mw - raw_forecast.forecast_mw
            if shift_mw >= -self._non_business_analog_min_downshift_mw:
                result.append(adjusted_forecast)
                continue
            if not self._non_business_analog_downshift_supported(row, raw_forecast):
                result.append(adjusted_forecast)
                continue

            guarded_shift_mw = -self._non_business_analog_max_downshift_mw
            if guarded_shift_mw <= shift_mw:
                result.append(adjusted_forecast)
                continue

            result.append(self._shift_forecast(raw_forecast, guarded_shift_mw))
            changed = True

        return result if changed else adjusted_forecasts

    def _apply_non_business_morning_shape_floor_guard(
        self,
        forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        if not self._non_business_morning_shape_floor_may_apply(inference_features):
            return forecasts

        rows_by_hour = {}
        for _, row in inference_features.iterrows():
            hour = self._finite_float(row.get("hour"))
            if hour is not None:
                rows_by_hour[int(hour)] = row

        forecasts_by_hour = {
            pd.Timestamp(forecast.ts).hour: forecast
            for forecast in forecasts
        }
        result = []
        changed = False
        for forecast in forecasts:
            hour = pd.Timestamp(forecast.ts).hour
            row = rows_by_hour.get(hour)
            previous_forecast = forecasts_by_hour.get(hour - 1)
            if (
                row is None
                or previous_forecast is None
                or hour not in self._non_business_morning_shape_hours
            ):
                result.append(forecast)
                continue

            is_non_business_day = self._finite_float(row.get("is_non_business_day"))
            if is_non_business_day != 1.0:
                result.append(forecast)
                continue

            support_candidates = [
                value
                for value in (
                    self._finite_float(row.get("lag_24h_hourly_delta")),
                    self._finite_float(row.get("recent_same_business_type_delta_mean")),
                )
                if value is not None
            ]
            if not support_candidates:
                result.append(forecast)
                continue

            support_delta_mw = max(support_candidates)
            forecast_delta_mw = forecast.forecast_mw - previous_forecast.forecast_mw
            shape_shortfall_mw = support_delta_mw - forecast_delta_mw
            if shape_shortfall_mw < self._non_business_morning_shape_min_shortfall_mw:
                result.append(forecast)
                continue

            floor_mw = (
                previous_forecast.forecast_mw
                + support_delta_mw
                - self._non_business_morning_shape_support_slack_mw
            )
            if forecast.forecast_mw >= floor_mw:
                result.append(forecast)
                continue

            lift_mw = min(
                (floor_mw - forecast.forecast_mw)
                * self._non_business_morning_shape_shrinkage,
                self._non_business_morning_shape_max_lift_mw,
            )
            if lift_mw < self._non_business_morning_shape_min_lift_mw:
                result.append(forecast)
                continue

            result.append(self._shift_forecast(forecast, lift_mw))
            changed = True

        return result if changed else forecasts

    def apply(
        self,
        raw_forecasts: list,
        adjusted_forecasts: list,
        inference_features: pd.DataFrame,
    ) -> list:
        """Return guardrailed forecast list.

        Falls through to adjusted_forecasts when guard is disabled, activation
        conditions are not met (consec or dsh), or per-hour conditions are not met.
        """
        if not self._enabled or not raw_forecasts:
            return adjusted_forecasts

        row0 = inference_features.iloc[0]
        target_date = pd.Timestamp(raw_forecasts[0].ts).date()
        lag_168h_date = target_date - timedelta(days=7)
        target_is_business_day = bool(row0.get("is_non_business_day", 0) == 0)
        post_holiday_active = (
            float(row0["consec_holiday_len"]) >= self._min_consec
            and float(row0["days_since_holiday_end"]) <= self._max_dsh
        )
        lag_holiday_active = (
            self._activate_on_holiday_lag
            and target_is_business_day
            and _is_nonworking(lag_168h_date)
        )
        business_return_shortfall_active = (
            self._business_return_shortfall_may_apply(inference_features)
        )
        business_return_excess_active = (
            self._business_return_excess_may_apply(inference_features)
        )
        non_business_analog_active = self._non_business_analog_downshift_may_apply(
            inference_features
        )
        non_business_morning_shape_active = (
            self._non_business_morning_shape_floor_may_apply(inference_features)
        )
        business_afternoon_analog_active = self._business_afternoon_analog_may_apply(
            inference_features
        )
        business_afternoon_downshift_active = (
            self._business_afternoon_downshift_may_apply(inference_features)
        )
        if not (
            post_holiday_active
            or lag_holiday_active
            or self._activate_on_warm_day
            or business_return_shortfall_active
            or business_return_excess_active
            or non_business_analog_active
            or non_business_morning_shape_active
            or business_afternoon_analog_active
            or business_afternoon_downshift_active
        ):
            return adjusted_forecasts

        from python.forecast.baseline import HourlyForecast

        result = []
        for raw_forecast, adjusted_forecast in zip(raw_forecasts, adjusted_forecasts):
            hour = pd.Timestamp(raw_forecast.ts).hour
            shift = adjusted_forecast.forecast_mw - raw_forecast.forecast_mw

            # Early morning guard
            if post_holiday_active and hour in self._em_hours:
                # Step 1: blocking determines the base
                base = (
                    raw_forecast
                    if (self._em_block_pos and shift > 0)
                    else adjusted_forecast
                )
                # Step 2: apply downward offset (independent of block decision)
                em_offset = min(self._em_offset, self._em_max_offset)
                if em_offset == 0.0:
                    result.append(base)
                else:
                    result.append(HourlyForecast(
                        ts=base.ts,
                        forecast_mw=round(base.forecast_mw - em_offset, 1),
                        p95_lower_mw=round(base.p95_lower_mw - em_offset, 1),
                        p95_upper_mw=round(base.p95_upper_mw - em_offset, 1),
                        p99_lower_mw=round(base.p99_lower_mw - em_offset, 1),
                        p99_upper_mw=round(base.p99_upper_mw - em_offset, 1),
                    ))
                continue

            # Daytime guard
            if hour in self._dt_hours:
                row = inference_features.iloc[hour]
                temp_anomaly_7d = float(row["temp_anomaly_7d"])
                holiday_heat_active = (
                    (post_holiday_active or lag_holiday_active)
                    and not np.isnan(temp_anomaly_7d)
                    and temp_anomaly_7d >= self._dt_min_anomaly
                )
                temp_anomaly_doy = (
                    float(row["temp_anomaly_doy"])
                    if pd.notna(row.get("temp_anomaly_doy"))
                    else np.nan
                )
                warm_day_active = (
                    self._activate_on_warm_day
                    and target_is_business_day
                    and not np.isnan(temp_anomaly_doy)
                    and temp_anomaly_doy >= self._warm_day_min_anomaly_doy
                )

                if holiday_heat_active or warm_day_active:
                    warm_day_decline_active = (
                        warm_day_active
                        and self._warm_day_decline_damping_active(hour, row)
                    )
                    # Step 1: blocking determines the base
                    base = (
                        raw_forecast
                        if (
                            self._dt_block_neg
                            and shift < 0
                            and not (
                                warm_day_decline_active
                                and self._warm_day_decline_allow_negative_analog_shift
                            )
                        )
                        else adjusted_forecast
                    )
                    # Step 2: apply upward offset (independent of block decision)
                    offset_candidates = []
                    if holiday_heat_active:
                        offset_candidates.append(self._dt_offset)
                    if warm_day_active and shift <= 0:
                        warm_day_offset = self._warm_day_offset
                        if warm_day_decline_active:
                            warm_day_offset *= self._warm_day_decline_offset_multiplier
                        offset_candidates.append(warm_day_offset)
                    dt_offset = min(max(offset_candidates or [0.0]), self._dt_max_offset)
                    if dt_offset == 0.0:
                        capped = self._cap_warm_day_lag24_increase(
                            base,
                            row,
                            holiday_heat_active or warm_day_active,
                        )
                        result.append(capped)
                    else:
                        shifted = self._shift_forecast(base, dt_offset)
                        capped = self._cap_warm_day_lag24_increase(
                            shifted,
                            row,
                            holiday_heat_active or warm_day_active,
                        )
                        result.append(capped)
                    continue

            result.append(adjusted_forecast)

        result = self._apply_non_business_analog_downshift_guard(
            raw_forecasts,
            result,
            inference_features,
        )
        result = self._apply_non_business_morning_shape_floor_guard(
            result,
            inference_features,
        )
        result = self._apply_business_return_anchor_shortfall(result, inference_features)
        result = self._apply_business_return_anchor_excess_cap(result, inference_features)
        result = self._apply_business_afternoon_analog_excess_cap(
            raw_forecasts,
            result,
            inference_features,
        )
        return self._apply_business_afternoon_analog_downshift_guard(
            raw_forecasts,
            result,
            inference_features,
        )


# ---------------------------------------------------------------------------
# MiddayTransitionGuard
# ---------------------------------------------------------------------------

class MiddayTransitionGuard:
    """Dampen business-day noon over-elevation when recent shape points downward.

    This guard does not create a fixed lunch dip. It only activates when the
    inference context says that the same hour recently dropped from the previous
    hour, and the current forecast ignores that transition by a meaningful margin.
    """

    def __init__(self, config: dict) -> None:
        guard_config = config.get("adjustment", {}).get("midday_transition_guard", {})
        self._enabled = bool(guard_config.get("enabled", True))
        self._hours = set(guard_config.get("hours", [12]))
        self._min_negative_delta_mw = float(
            guard_config.get("min_negative_delta_mw", 500.0)
        )
        self._min_excess_mw = float(guard_config.get("min_excess_mw", 300.0))
        self._shrinkage = float(guard_config.get("shrinkage", 0.5))
        self._triggered_shrinkage = float(
            guard_config.get("triggered_shrinkage", 0.75)
        )
        self._max_downward_adjustment_mw = float(
            guard_config.get("max_downward_adjustment_mw", 900.0)
        )
        self._triggered_max_downward_adjustment_mw = float(
            guard_config.get(
                "triggered_max_downward_adjustment_mw",
                self._max_downward_adjustment_mw,
            )
        )
        self._same_day_softening_min_latest_hour = int(
            guard_config.get("same_day_softening_min_latest_hour", 10)
        )
        self._same_day_softening_delta_mw = float(
            guard_config.get("same_day_softening_delta_mw", -300.0)
        )
        self._use_recent_quantile_when_softening = bool(
            guard_config.get("use_recent_quantile_when_softening", True)
        )

    @staticmethod
    def _shift_forecast(forecast, shift_mw: float):
        from python.forecast.baseline import HourlyForecast

        return HourlyForecast(
            ts=forecast.ts,
            forecast_mw=round(forecast.forecast_mw + shift_mw, 1),
            p95_lower_mw=round(forecast.p95_lower_mw + shift_mw, 1),
            p95_upper_mw=round(forecast.p95_upper_mw + shift_mw, 1),
            p99_lower_mw=round(forecast.p99_lower_mw + shift_mw, 1),
            p99_upper_mw=round(forecast.p99_upper_mw + shift_mw, 1),
        )

    def _same_day_softening_active(self, row) -> bool:
        latest_hour = row.get("same_day_latest_actual_hour")
        latest_delta = row.get("same_day_latest_hourly_delta")
        recent_delta = row.get("same_day_recent_hourly_delta_mean")
        if pd.isna(latest_hour) or float(latest_hour) < self._same_day_softening_min_latest_hour:
            return False
        for value in [latest_delta, recent_delta]:
            if pd.notna(value) and np.isfinite(float(value)):
                if float(value) <= self._same_day_softening_delta_mw:
                    return True
        return False

    def apply(self, forecasts: list, inference_features: pd.DataFrame) -> list:
        if not self._enabled or not forecasts:
            return forecasts
        if "is_non_business_day" not in inference_features.columns:
            return forecasts
        if bool(inference_features.iloc[0].get("is_non_business_day", 0) != 0):
            return forecasts

        result = list(forecasts)
        features_by_hour = {
            int(row["hour"]): row
            for _, row in inference_features.iterrows()
            if "hour" in row
        }
        for hour in sorted(self._hours):
            if hour <= 0 or hour >= len(result):
                continue
            row = features_by_hour.get(hour)
            if row is None:
                continue

            deltas = []
            for column in [
                "lag_24h_hourly_delta",
                "recent_same_business_type_delta_mean",
            ]:
                value = row.get(column)
                if pd.notna(value) and np.isfinite(float(value)):
                    deltas.append(float(value))

            same_day_softening_active = self._same_day_softening_active(row)
            if self._use_recent_quantile_when_softening and same_day_softening_active:
                value = row.get("recent_same_business_type_delta_q25")
                if pd.notna(value) and np.isfinite(float(value)):
                    deltas.append(float(value))
            negative_deltas = [
                value for value in deltas
                if value <= -self._min_negative_delta_mw
            ]
            if not negative_deltas:
                continue

            expected_delta = (
                float(min(negative_deltas))
                if same_day_softening_active
                else float(np.mean(negative_deltas))
            )
            previous_forecast = result[hour - 1]
            current_forecast = result[hour]
            forecast_delta = current_forecast.forecast_mw - previous_forecast.forecast_mw
            excess = forecast_delta - expected_delta
            if excess < self._min_excess_mw:
                continue

            target_mw = previous_forecast.forecast_mw + expected_delta
            shrinkage = (
                self._triggered_shrinkage
                if same_day_softening_active
                else self._shrinkage
            )
            max_downward_adjustment_mw = (
                self._triggered_max_downward_adjustment_mw
                if same_day_softening_active
                else self._max_downward_adjustment_mw
            )
            raw_shift = (target_mw - current_forecast.forecast_mw) * shrinkage
            if raw_shift >= 0.0:
                continue
            shift = max(raw_shift, -max_downward_adjustment_mw)
            result[hour] = self._shift_forecast(current_forecast, shift)

        return result


# ---------------------------------------------------------------------------
# LocalizedShapeSpikeGuard
# ---------------------------------------------------------------------------

class LocalizedShapeSpikeGuard:
    """Dampen isolated one-hour forecast spikes unsupported by lag/weather shape.

    This guard is intentionally narrow. It does not suppress broad daytime peaks;
    it only looks for a single hour that rises above both neighboring forecast
    hours while lag/recent-business deltas and weather deltas do not support a
    local peak.
    """

    def __init__(self, config: dict) -> None:
        guard_config = config.get("adjustment", {}).get("localized_shape_spike_guard", {})
        self._enabled = bool(guard_config.get("enabled", True))
        self._business_day_only = bool(guard_config.get("business_day_only", True))
        self._hours = {
            int(hour)
            for hour in guard_config.get("hours", [13, 14, 15, 16, 17])
        }
        self._min_neighbor_excess_mw = float(
            guard_config.get("min_neighbor_excess_mw", 600.0)
        )
        self._neighbor_buffer_mw = float(guard_config.get("neighbor_buffer_mw", 450.0))
        self._max_supporting_delta_mw = float(
            guard_config.get("max_supporting_delta_mw", 500.0)
        )
        self._max_weather_delta_c = float(guard_config.get("max_weather_delta_c", 2.0))
        self._max_same_day_slope_mw = float(
            guard_config.get("max_same_day_slope_mw", 900.0)
        )
        self._shrinkage = min(max(float(guard_config.get("shrinkage", 0.75)), 0.0), 1.0)
        self._max_reduction_mw = float(guard_config.get("max_reduction_mw", 700.0))
        self._min_reduction_mw = float(guard_config.get("min_reduction_mw", 100.0))
        morning_config = guard_config.get("morning_spike", {})
        self._morning_spike_enabled = bool(morning_config.get("enabled", False))
        self._morning_spike_hours = {
            int(hour)
            for hour in morning_config.get("hours", [8, 9, 10, 11])
        }
        self._morning_spike_min_neighbor_excess_mw = float(
            morning_config.get("min_neighbor_excess_mw", 1_000.0)
        )
        self._morning_spike_min_forecast_delta_over_support_mw = float(
            morning_config.get("min_forecast_delta_over_support_mw", 1_000.0)
        )
        self._morning_spike_min_next_drop_mw = float(
            morning_config.get("min_next_drop_mw", 800.0)
        )
        self._morning_spike_neighbor_buffer_mw = float(
            morning_config.get("neighbor_buffer_mw", 700.0)
        )
        self._morning_spike_max_weather_delta_c = float(
            morning_config.get("max_weather_delta_c", 3.5)
        )
        self._morning_spike_shrinkage = min(
            max(float(morning_config.get("shrinkage", 0.75)), 0.0),
            1.0,
        )
        self._morning_spike_max_reduction_mw = float(
            morning_config.get("max_reduction_mw", 1_400.0)
        )
        self._morning_spike_min_reduction_mw = float(
            morning_config.get("min_reduction_mw", 150.0)
        )

    @staticmethod
    def _finite_float(value) -> float | None:
        if value is None or pd.isna(value):
            return None
        parsed = float(value)
        if not np.isfinite(parsed):
            return None
        return parsed

    @staticmethod
    def _shift_forecast(forecast, shift_mw: float):
        from python.forecast.baseline import HourlyForecast

        return HourlyForecast(
            ts=forecast.ts,
            forecast_mw=round(forecast.forecast_mw + shift_mw, 1),
            p95_lower_mw=round(forecast.p95_lower_mw + shift_mw, 1),
            p95_upper_mw=round(forecast.p95_upper_mw + shift_mw, 1),
            p99_lower_mw=round(forecast.p99_lower_mw + shift_mw, 1),
            p99_upper_mw=round(forecast.p99_upper_mw + shift_mw, 1),
        )

    def _unsupported_by_context(self, row) -> bool:
        support_values = []
        for column in [
            "lag_24h_hourly_delta",
            "recent_same_business_type_delta_mean",
        ]:
            value = self._finite_float(row.get(column))
            if value is not None:
                support_values.append(value)
        if support_values and max(support_values) > self._max_supporting_delta_mw:
            return False

        weather_values = []
        for column in ["temp_delta_24h", "cooling_delta_24h"]:
            value = self._finite_float(row.get(column))
            if value is not None:
                weather_values.append(value)
        if weather_values and max(weather_values) > self._max_weather_delta_c:
            return False

        same_day_slope = self._finite_float(row.get("same_day_latest_hourly_delta"))
        if same_day_slope is not None and same_day_slope > self._max_same_day_slope_mw:
            return False
        return True

    def _support_delta(self, row) -> float | None:
        support_values = []
        for column in [
            "lag_24h_hourly_delta",
            "recent_same_business_type_delta_mean",
        ]:
            value = self._finite_float(row.get(column))
            if value is not None:
                support_values.append(value)
        if not support_values:
            return None
        return max(support_values)

    def _weather_delta(self, row) -> float | None:
        weather_values = []
        for column in ["temp_delta_24h", "cooling_delta_24h"]:
            value = self._finite_float(row.get(column))
            if value is not None:
                weather_values.append(value)
        if not weather_values:
            return None
        return max(weather_values)

    def _morning_spike_reduction(
        self,
        previous_forecast,
        forecast,
        next_forecast,
        row,
    ) -> float | None:
        if not self._morning_spike_enabled:
            return None

        max_neighbor_mw = max(
            previous_forecast.forecast_mw,
            next_forecast.forecast_mw,
        )
        if (
            forecast.forecast_mw - max_neighbor_mw
            < self._morning_spike_min_neighbor_excess_mw
        ):
            return None

        next_drop_mw = forecast.forecast_mw - next_forecast.forecast_mw
        if next_drop_mw < self._morning_spike_min_next_drop_mw:
            return None

        forecast_delta_mw = forecast.forecast_mw - previous_forecast.forecast_mw
        support_delta_mw = self._support_delta(row)
        if support_delta_mw is None:
            return None
        if (
            forecast_delta_mw - support_delta_mw
            < self._morning_spike_min_forecast_delta_over_support_mw
        ):
            return None

        weather_delta_c = self._weather_delta(row)
        if (
            weather_delta_c is not None
            and weather_delta_c > self._morning_spike_max_weather_delta_c
        ):
            return None

        neighbor_anchor_mw = (
            previous_forecast.forecast_mw + next_forecast.forecast_mw
        ) / 2.0
        cap_mw = neighbor_anchor_mw + self._morning_spike_neighbor_buffer_mw
        if forecast.forecast_mw <= cap_mw:
            return None

        reduction_mw = min(
            (forecast.forecast_mw - cap_mw) * self._morning_spike_shrinkage,
            self._morning_spike_max_reduction_mw,
        )
        if reduction_mw < self._morning_spike_min_reduction_mw:
            return None
        return float(reduction_mw)

    def apply(self, forecasts: list, inference_features: pd.DataFrame) -> list:
        if (
            not self._enabled
            or not forecasts
            or inference_features is None
            or inference_features.empty
        ):
            return forecasts
        if (
            self._business_day_only
            and self._finite_float(inference_features.iloc[0].get("is_non_business_day")) != 0.0
        ):
            return forecasts

        features_by_hour = {
            int(row["hour"]): row
            for _, row in inference_features.iterrows()
            if "hour" in row and pd.notna(row.get("hour"))
        }
        result = list(forecasts)
        changed = False
        for index in range(1, len(result) - 1):
            forecast = result[index]
            hour = pd.Timestamp(forecast.ts).hour
            row = features_by_hour.get(hour)
            if row is None:
                continue

            prev_forecast = result[index - 1]
            next_forecast = result[index + 1]
            if hour in self._morning_spike_hours:
                morning_reduction_mw = self._morning_spike_reduction(
                    prev_forecast,
                    forecast,
                    next_forecast,
                    row,
                )
                if morning_reduction_mw is not None:
                    result[index] = self._shift_forecast(
                        forecast,
                        -morning_reduction_mw,
                    )
                    changed = True
                    continue

            if hour not in self._hours or not self._unsupported_by_context(row):
                continue

            max_neighbor_mw = max(prev_forecast.forecast_mw, next_forecast.forecast_mw)
            if forecast.forecast_mw - max_neighbor_mw < self._min_neighbor_excess_mw:
                continue

            neighbor_anchor_mw = (
                prev_forecast.forecast_mw + next_forecast.forecast_mw
            ) / 2.0
            cap_mw = neighbor_anchor_mw + self._neighbor_buffer_mw
            if forecast.forecast_mw <= cap_mw:
                continue
            reduction_mw = min(
                (forecast.forecast_mw - cap_mw) * self._shrinkage,
                self._max_reduction_mw,
            )
            if reduction_mw < self._min_reduction_mw:
                continue
            result[index] = self._shift_forecast(forecast, -reduction_mw)
            changed = True

        return result if changed else forecasts
