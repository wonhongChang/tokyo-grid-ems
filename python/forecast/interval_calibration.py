"""Utilities for forecast interval sanity calibration."""
from __future__ import annotations

from typing import Any

_DEFAULT_MIN_P95_HALF_WIDTH_MW = 500.0


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0.0 else None


def calibrate_p95_half_widths(
    half_lo: float,
    half_hi: float,
    config: dict | None = None,
) -> tuple[float, float]:
    """Return calibrated lower/upper p95 half-widths.

    The quantile models are trained independently, so one side can occasionally
    become much wider than the other after a weather-regime shift.  This helper
    keeps the interval ordered, preserves the minimum uncertainty floor, and
    optionally caps extreme one-sided tails using operational config.
    """
    interval_config = (config or {}).get("interval_calibration", {})
    min_half_width = max(
        0.0,
        float(
            interval_config.get(
                "min_p95_half_width_mw",
                _DEFAULT_MIN_P95_HALF_WIDTH_MW,
            )
        ),
    )

    half_lo = max(0.0, float(half_lo))
    half_hi = max(0.0, float(half_hi))

    if interval_config.get("mirror_collapsed_side", False):
        reference_width = max(half_lo, half_hi, min_half_width)
        if half_lo < min_half_width:
            half_lo = reference_width
        if half_hi < min_half_width:
            half_hi = reference_width
    else:
        half_lo = max(half_lo, min_half_width)
        half_hi = max(half_hi, min_half_width)

    max_half_width = _positive_float(
        interval_config.get("max_p95_half_width_mw")
    )
    max_asymmetry_ratio = _positive_float(
        interval_config.get("max_p95_asymmetry_ratio")
    )
    asymmetry_reference = max(
        min_half_width,
        float(interval_config.get("asymmetry_reference_half_width_mw", min_half_width)),
    )

    def _cap_side(width: float, opposite_width: float) -> float:
        cap = max_half_width
        if max_asymmetry_ratio is not None:
            asymmetry_cap = max(opposite_width, asymmetry_reference) * max_asymmetry_ratio
            cap = asymmetry_cap if cap is None else min(cap, asymmetry_cap)
        if cap is not None:
            width = min(width, max(min_half_width, cap))
        return max(width, min_half_width)

    capped_lo = _cap_side(half_lo, half_hi)
    capped_hi = _cap_side(half_hi, half_lo)

    rebalance_ratio = _positive_float(
        interval_config.get("rebalance_p95_asymmetry_ratio")
    )
    if rebalance_ratio is None:
        rebalance_ratio = max_asymmetry_ratio
    if (
        interval_config.get("rebalance_extreme_asymmetry", False)
        and rebalance_ratio is not None
        and rebalance_ratio > 1.0
    ):
        larger = max(capped_lo, capped_hi)
        smaller = min(capped_lo, capped_hi)
        if larger > smaller * rebalance_ratio:
            total_width = capped_lo + capped_hi
            target_smaller = max(
                min_half_width,
                total_width / (rebalance_ratio + 1.0),
            )
            target_larger = max(min_half_width, total_width - target_smaller)
            if target_larger > target_smaller * rebalance_ratio:
                target_larger = target_smaller * rebalance_ratio
            if max_half_width is not None:
                target_larger = min(target_larger, max_half_width)
                target_smaller = min(target_smaller, max_half_width)
            if capped_lo >= capped_hi:
                capped_lo, capped_hi = target_larger, target_smaller
            else:
                capped_lo, capped_hi = target_smaller, target_larger

    return capped_lo, capped_hi
