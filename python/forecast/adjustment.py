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

    def _cap_warm_day_lag24_increase(self, forecast, row, active: bool):
        if not (self._lag24_warm_day_cap_enabled and active):
            return forecast
        lag_24h = float(row["lag_24h"]) if pd.notna(row.get("lag_24h")) else np.nan
        if np.isnan(lag_24h):
            return forecast
        max_forecast_mw = lag_24h + self._lag24_warm_day_max_increase_mw
        if forecast.forecast_mw <= max_forecast_mw:
            return forecast
        return self._shift_forecast(forecast, max_forecast_mw - forecast.forecast_mw)

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
        if not (post_holiday_active or lag_holiday_active or self._activate_on_warm_day):
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
                    # Step 1: blocking determines the base
                    base = (
                        raw_forecast
                        if (self._dt_block_neg and shift < 0)
                        else adjusted_forecast
                    )
                    # Step 2: apply upward offset (independent of block decision)
                    offset_candidates = []
                    if holiday_heat_active:
                        offset_candidates.append(self._dt_offset)
                    if warm_day_active and shift <= 0:
                        offset_candidates.append(self._warm_day_offset)
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

        return result


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
