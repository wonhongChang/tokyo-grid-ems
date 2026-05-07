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
        adj = config.get("adjustment", {})
        self._enabled = bool(adj.get("enabled", True))
        cfg = adj.get("analogous_day", {})
        self._month_window               = int(cfg.get("month_window", 1))
        self._temp_anomaly_tol           = float(cfg.get("temp_anomaly_tol", 4.0))
        self._consec_holiday_tol         = int(cfg.get("consec_holiday_tol", 2))
        self._min_candidates             = int(cfg.get("min_candidates", 1))
        self._max_candidates             = int(cfg.get("max_candidates", 5))
        self._same_weekday_required      = bool(cfg.get("same_weekday_required", False))
        self._weekday_type_required      = bool(cfg.get("weekday_type_required", True))
        self._shift_shrinkage            = float(cfg.get("shift_shrinkage", 0.7))
        self._single_candidate_shrinkage = float(cfg.get("single_candidate_shrinkage", 0.5))
        self._max_abs_shift_mw           = float(cfg.get("max_abs_shift_mw", 2500.0))

    # ------------------------------------------------------------------
    # Candidate search
    # ------------------------------------------------------------------

    def _find_candidates(
        self,
        cache: pd.DataFrame,
        target_date: date,
        target_consec: int,
        target_anomaly: float,
        target_is_weekday: bool,
    ) -> list[date]:
        """Return up to max_candidates analogous past dates, most-recent first."""
        from python.forecast.feature_builder import _consec_holiday_len

        notna = cache[cache["actual_mw"].notna()]
        past_dates = sorted(d for d in notna["ts"].dt.date.unique() if d < target_date)

        target_month = target_date.month
        candidates: list[date] = []

        for d in past_dates:
            # Month window (circular across year boundary)
            diff = abs(d.month - target_month)
            if min(diff, 12 - diff) > self._month_window:
                continue

            # Weekday type
            d_is_weekday = not _is_nonworking(d)
            if self._weekday_type_required and d_is_weekday != target_is_weekday:
                continue
            if self._same_weekday_required and d.weekday() != target_date.weekday():
                continue

            # Consecutive holiday length
            if abs(_consec_holiday_len(d) - target_consec) > self._consec_holiday_tol:
                continue

            # Temperature anomaly (skip filter when target anomaly is unknown)
            if not np.isnan(target_anomaly) and "temp_c" in cache.columns:
                cutoff = pd.Timestamp(d.year, d.month, d.day, tz=JST)
                past_week = cache[
                    (cache["ts"] < cutoff) &
                    (cache["ts"] >= cutoff - pd.Timedelta(hours=168))
                ]["temp_c"].dropna()
                if len(past_week) >= 24:
                    day_temps = cache[cache["ts"].dt.date == d]["temp_c"].dropna()
                    if len(day_temps) == 0:
                        continue
                    cand_anomaly = float(day_temps.mean()) - float(past_week.mean())
                    if abs(cand_anomaly - target_anomaly) > self._temp_anomaly_tol:
                        continue

            # Need at least 12 actual readings
            if len(notna[notna["ts"].dt.date == d]) < 12:
                continue

            candidates.append(d)

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
        target_consec    = int(row0["consec_holiday_len"])
        target_anomaly   = float(np.nanmean(inference_features["temp_anomaly_7d"].values))
        target_is_weekday = bool(row0["is_non_business_day"] == 0)

        candidates = self._find_candidates(
            cache, target_date, target_consec, target_anomaly, target_is_weekday
        )
        if len(candidates) < self._min_candidates:
            return raw_forecasts

        # Compute per-hour residuals (actual − q50 prediction) for each candidate
        hour_residuals: dict[int, list[float]] = {h: [] for h in range(24)}
        notna = cache[cache["actual_mw"].notna()]

        for cand_date in candidates:
            try:
                cand_fc = forecaster.predict(cand_date, cache)
            except Exception as e:
                print(
                    f"[WARN] AnalogousDayAdjuster: predict failed for {cand_date}: {e}",
                    file=sys.stderr,
                )
                continue

            # hour → q50 from candidate forecast
            cand_q50: dict[int, float] = {
                pd.Timestamp(fc.ts).hour: fc.forecast_mw for fc in cand_fc
            }

            # hour → actual_mw from cache
            day_rows = notna[notna["ts"].dt.date == cand_date]
            for _, row in day_rows.iterrows():
                h = int(row["ts"].hour)
                if h in cand_q50:
                    hour_residuals[h].append(float(row["actual_mw"]) - cand_q50[h])

        # Choose shrinkage based on how many candidates contributed
        n_cands = len(candidates)
        shrinkage = (
            self._single_candidate_shrinkage if n_cands == 1 else self._shift_shrinkage
        )

        hour_shift: dict[int, float] = {}
        for h in range(24):
            res = hour_residuals[h]
            if not res:
                hour_shift[h] = 0.0
            else:
                raw_shift = float(np.mean(res)) * shrinkage
                hour_shift[h] = float(
                    np.clip(raw_shift, -self._max_abs_shift_mw, self._max_abs_shift_mw)
                )

        # Apply uniform hour-level shift to all quantile bands
        from python.forecast.baseline import HourlyForecast

        corrected = []
        for fc in raw_forecasts:
            shift = hour_shift.get(pd.Timestamp(fc.ts).hour, 0.0)
            corrected.append(HourlyForecast(
                ts=fc.ts,
                forecast_mw=round(fc.forecast_mw + shift, 1),
                p95_lower_mw=round(fc.p95_lower_mw + shift, 1),
                p95_upper_mw=round(fc.p95_upper_mw + shift, 1),
                p99_lower_mw=round(fc.p99_lower_mw + shift, 1),
                p99_upper_mw=round(fc.p99_upper_mw + shift, 1),
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
        adj = config.get("adjustment", {})
        cfg = adj.get("post_holiday_timeband_guard", {})
        self._enabled     = bool(cfg.get("enabled", True))
        self._min_consec  = int(cfg.get("min_consec_holiday_len", 3))
        self._max_dsh     = int(cfg.get("max_days_since_holiday_end", 1))

        em = cfg.get("early_morning", {})
        self._em_hours         = set(em.get("hours", [1, 2, 3, 4, 5, 6]))
        self._em_block_pos     = bool(em.get("block_positive_shift", True))
        self._em_offset        = float(em.get("downward_offset_mw", 0.0))
        self._em_max_offset    = float(em.get("max_downward_offset_mw", 600.0))

        dt = cfg.get("daytime", {})
        self._dt_hours         = set(dt.get("hours", [10, 11, 12, 13, 14, 15, 16, 17, 18]))
        self._dt_min_anomaly   = float(dt.get("min_temp_anomaly_7d", 2.0))
        self._dt_block_neg     = bool(dt.get("block_negative_shift", True))
        self._dt_offset        = float(dt.get("upward_offset_mw", 0.0))
        self._dt_max_offset    = float(dt.get("max_upward_offset_mw", 900.0))

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
        for raw_fc, adj_fc in zip(raw_forecasts, adjusted_forecasts):
            hour  = pd.Timestamp(raw_fc.ts).hour
            shift = adj_fc.forecast_mw - raw_fc.forecast_mw

            # Early morning guard
            if hour in self._em_hours:
                # Step 1: blocking determines the base
                base = raw_fc if (self._em_block_pos and shift > 0) else adj_fc
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
                temp_anom = float(row["temp_anomaly_7d"])
                if not np.isnan(temp_anom) and temp_anom >= self._dt_min_anomaly:
                    # Step 1: blocking determines the base
                    base = raw_fc if (self._dt_block_neg and shift < 0) else adj_fc
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

            result.append(adj_fc)

        return result
