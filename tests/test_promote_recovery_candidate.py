"""Tests for the explicit degraded-Champion recovery promotion path."""
from __future__ import annotations

import pytest

from python.eval.promote_recovery_candidate import (
    _validate_replay_evidence,
    _validate_v13_evidence,
)


def _report(days: int, *, candidate_mae: float = 900.0) -> dict:
    return {
        "validationPeriod": {"days": days},
        "candidate": {
            "overall": {"maeMw": candidate_mae, "wapePct": 2.7},
        },
        "championContract": {
            "overall": {"maeMw": 1000.0, "wapePct": 3.0},
        },
        "recoveryGate": {"passed": days == 28},
    }


def test_recovery_promotion_requires_all_validation_windows() -> None:
    with pytest.raises(ValueError, match="28, 56, and 84-day"):
        _validate_replay_evidence({28: _report(28), 56: _report(56)})


def test_recovery_promotion_accepts_non_regressing_support_windows() -> None:
    _validate_replay_evidence({
        28: _report(28),
        56: _report(56, candidate_mae=950.0),
        84: _report(84, candidate_mae=975.0),
    })


def test_recovery_promotion_rejects_support_window_regression() -> None:
    reports = {
        28: _report(28),
        56: _report(56, candidate_mae=1000.1),
        84: _report(84),
    }

    with pytest.raises(ValueError, match="56d candidate regressed on maeMw"):
        _validate_replay_evidence(reports)


def test_recovery_promotion_requires_primary_recovery_gate() -> None:
    reports = {days: _report(days) for days in (28, 56, 84)}
    reports[28]["recoveryGate"]["passed"] = False

    with pytest.raises(ValueError, match="recovery gate did not pass"):
        _validate_replay_evidence(reports)


def _experiment(*, mae: float = 950.0, wape: float = 2.85) -> dict:
    return {
        "featureSets": {
            "all63": {
                "metrics": {
                    "v13_contract": {
                        "overall": {"maeMw": mae, "wapePct": wape},
                    },
                },
            },
        },
    }


def test_recovery_promotion_accepts_small_gain_over_unpromoted_v13() -> None:
    reports = {days: _report(days, candidate_mae=900.0) for days in (28, 56, 84)}
    experiments = {days: _experiment(mae=940.0) for days in (28, 56, 84)}

    _validate_v13_evidence(reports, experiments)


def test_recovery_promotion_accepts_v13_improvement_across_windows() -> None:
    reports = {days: _report(days, candidate_mae=900.0) for days in (28, 56, 84)}
    experiments = {days: _experiment(mae=960.0) for days in (28, 56, 84)}

    _validate_v13_evidence(reports, experiments)


def test_recovery_promotion_rejects_v13_support_window_regression() -> None:
    reports = {days: _report(days, candidate_mae=900.0) for days in (28, 56, 84)}
    experiments = {days: _experiment(mae=960.0) for days in (28, 56, 84)}
    experiments[56] = _experiment(mae=899.0)

    with pytest.raises(ValueError, match="56d v14 regressed versus v13 on maeMw"):
        _validate_v13_evidence(reports, experiments)
