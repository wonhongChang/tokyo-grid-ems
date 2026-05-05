from __future__ import annotations

from enum import Enum

from python.tepc_parser import TepcoDailyParsed


class QualityStatus(Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


def run_quality_gate(parsed: TepcoDailyParsed) -> QualityStatus:
    """
    FAILED  → data is unusable (missing rows, no actual_mw column, all NaN)
    WARNING → data is usable but degraded (duplicates, non-monotonic timestamps)
    PASSED  → all checks green
    """
    q = parsed.quality
    h = q.get("hourly", {})

    if parsed.hourly.empty:
        return QualityStatus.FAILED
    if not h.get("expected_count_ok", False):
        return QualityStatus.FAILED
    if "actual_mw" not in parsed.hourly.columns:
        return QualityStatus.FAILED
    if parsed.hourly["actual_mw"].isna().all():
        return QualityStatus.FAILED

    if h.get("duplicates", 0) > 0:
        return QualityStatus.WARNING
    if not h.get("monotonic_increasing", True):
        return QualityStatus.WARNING
    freq_mismatch = h.get("freq_mismatch_count")
    if freq_mismatch is not None and freq_mismatch > 4:
        return QualityStatus.WARNING

    return QualityStatus.PASSED
