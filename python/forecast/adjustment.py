"""Post-processing residual correction via analogous past days and time-band guards."""
from __future__ import annotations

import sys
from datetime import date
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
    """Shift LGBM q50/q10/q90 forecasts by per-hour mean residuals from analogous past days.

    Analogous days are selected by: same calendar-month neighbourhood, same weekday
    type (weekday vs non-working), similar consecutive-holiday length, and similar
    7-day temperature anomaly.  Residuals are shrunk and capped before application.
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

            # Temperature anomaly (skip filter when target anomaly is unknown)
            if not np.isnan(target_temp_anomaly_7d) and "temp_c" in cache.columns:
                cutoff = pd.Timestamp(
                    candidate_date.year,
                    candidate_date.month,
                    candidate_date.day,
                    tz=JST,
                )
                past_week = cache[
                    (cache["ts"] < cutoff) &
                    (cache["ts"] >= cutoff - pd.Timedelta(hours=168))
                ]["temp_c"].dropna()
                if len(past_week) >= 24:
                    candidate_day_temps = cache[
                        cache["ts"].dt.date == candidate_date
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
        target_temp_anomaly_7d = float(
            np.nanmean(inference_features["temp_anomaly_7d"].values)
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
    """Prevent AnalogousDayAdjuster from shifting in the wrong direction on post-holiday days.

    Two regimes for the first business day after a long holiday (consec_holiday_len >= 3):
    - Early morning (default 1-6h): actual demand tends to be LOWER than predicted;
      block any positive adjuster shift so it cannot worsen overnight overestimation.
    - Daytime (default 10-18h, only when temp_anomaly_7d >= threshold): actual demand
      tends to be HIGHER than predicted; block any negative adjuster shift so it cannot
      worsen midday underestimation.

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
        if (float(row0["consec_holiday_len"]) < self._min_consec or
                float(row0["days_since_holiday_end"]) > self._max_dsh):
            return adjusted_forecasts

        from python.forecast.baseline import HourlyForecast

        result = []
        for raw_forecast, adjusted_forecast in zip(raw_forecasts, adjusted_forecasts):
            hour = pd.Timestamp(raw_forecast.ts).hour
            shift = adjusted_forecast.forecast_mw - raw_forecast.forecast_mw

            # Early morning guard
            if hour in self._em_hours:
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
                if not np.isnan(temp_anomaly_7d) and temp_anomaly_7d >= self._dt_min_anomaly:
                    # Step 1: blocking determines the base
                    base = (
                        raw_forecast
                        if (self._dt_block_neg and shift < 0)
                        else adjusted_forecast
                    )
                    # Step 2: apply upward offset (independent of block decision)
                    dt_offset = min(self._dt_offset, self._dt_max_offset)
                    if dt_offset == 0.0:
                        result.append(base)
                    else:
                        result.append(HourlyForecast(
                            ts=base.ts,
                            forecast_mw=round(base.forecast_mw + dt_offset, 1),
                            p95_lower_mw=round(base.p95_lower_mw + dt_offset, 1),
                            p95_upper_mw=round(base.p95_upper_mw + dt_offset, 1),
                            p99_lower_mw=round(base.p99_lower_mw + dt_offset, 1),
                            p99_upper_mw=round(base.p99_upper_mw + dt_offset, 1),
                        ))
                    continue

            result.append(adjusted_forecast)

        return result
