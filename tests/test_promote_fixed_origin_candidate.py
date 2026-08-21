from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from python.eval import promote_fixed_origin_candidate as promotion
from python.eval.model_validation import artifact_sha256
from python.forecast.lgbm_model import LGBMForecaster


@dataclass
class _Point:
    ts: pd.Timestamp
    forecast_mw: float = 30_000.0
    p95_lower_mw: float = 28_000.0
    p95_upper_mw: float = 32_000.0
    p99_lower_mw: float = 27_000.0
    p99_upper_mw: float = 33_000.0


class _FakeForecaster:
    def __init__(self, config: dict, interval_version: str) -> None:
        self.config = config
        self.interval_version = interval_version

    def is_compatible(self) -> bool:
        return True

    def predict(self, target: date, _cache: pd.DataFrame) -> list[_Point]:
        start = pd.Timestamp(target, tz="Asia/Tokyo")
        return [_Point(start + pd.Timedelta(hours=hour)) for hour in range(24)]


def _evidence(
    candidate: Path,
    interval_version: str,
    champion_sha256: str = "champion-sha",
) -> tuple[dict, dict, dict, dict]:
    common = {
        "gate": {
            "passed": True,
            "mode": "strict_mae_recovery",
            "maeImprovementPct": 25.0,
        },
        "candidateArtifact": {
            "sha256": artifact_sha256(candidate),
            "intervalVersion": interval_version,
        },
        "baselineArtifact": {
            "mode": "exact_deployed_champion",
            "sha256": champion_sha256,
            "intervalVersion": "v11",
        },
        "validationPeriod": {
            "start": "2026-08-01",
            "end": "2026-08-20",
            "days": 20,
        },
        "baseline": {"overall": {"maeMw": 1500.0}},
        "candidate": {"overall": {"maeMw": 1400.0}},
    }
    development = {
        **common,
        "phase": "development",
        "trainingCutoffExclusive": "2026-07-01",
        "methodology": {"originLeadDays": 0},
    }
    holdout = {
        **common,
        "phase": "holdout",
        "trainingCutoffExclusive": "2026-08-01",
        "methodology": {"originLeadDays": 0},
        "dailyRawResiduals": [{
            "date": "2026-08-20",
            "isNonBusinessDay": False,
            "meanResidualMw": -240.0,
            "originGeneratedAt": "2026-08-20T00:10:00+09:00",
        }],
    }
    day_ahead_development = {
        **development,
        "methodology": {"originLeadDays": 1},
    }
    day_ahead_holdout = {
        **holdout,
        "methodology": {"originLeadDays": 1},
    }
    return development, holdout, day_ahead_development, day_ahead_holdout


def test_validate_evidence_rejects_a_different_artifact(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.pkl"
    candidate.write_bytes(b"candidate")
    model = _FakeForecaster({}, LGBMForecaster.INTERVAL_VERSION)
    development, holdout, day_ahead_development, day_ahead_holdout = _evidence(
        candidate,
        model.interval_version,
    )
    holdout["candidateArtifact"]["sha256"] = "not-the-candidate"

    with pytest.raises(ValueError, match="exact candidate artifact"):
        promotion._validate_evidence(
            candidate,
            model,
            "champion-sha",
            development,
            holdout,
            day_ahead_development,
            day_ahead_holdout,
        )


def test_validate_evidence_requires_day_ahead_origin(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.pkl"
    candidate.write_bytes(b"candidate")
    model = _FakeForecaster({}, LGBMForecaster.INTERVAL_VERSION)
    development, holdout, day_ahead_development, day_ahead_holdout = _evidence(
        candidate,
        model.interval_version,
    )
    day_ahead_holdout["methodology"]["originLeadDays"] = 0

    with pytest.raises(ValueError, match="wrong forecast origin"):
        promotion._validate_evidence(
            candidate,
            model,
            "champion-sha",
            development,
            holdout,
            day_ahead_development,
            day_ahead_holdout,
        )


def test_promote_preserves_rollback_and_seeds_calibration_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_dir = tmp_path / "public"
    out_dir.mkdir()
    champion_path = out_dir / ".lgbm_model.pkl"
    candidate_path = tmp_path / "candidate.pkl"
    champion_path.write_bytes(b"champion-v11")
    candidate_path.write_bytes(b"candidate-v14-r2")
    config = {
        "forecast": {
            "model_contract": "v14-r2-source-robust-day-ahead",
            "same_regime_day_level_calibration": {
                "state_path": "metrics/same_regime_day_level_calibration.json",
            },
        },
        "model_promotion": {
            "max_mean_prediction_drift_mw": 900,
            "max_hour_prediction_drift_mw": 2500,
        },
    }
    champion = _FakeForecaster(config, "v11")
    candidate = _FakeForecaster(config, LGBMForecaster.INTERVAL_VERSION)
    development, holdout, day_ahead_development, day_ahead_holdout = _evidence(
        candidate_path,
        candidate.interval_version,
        artifact_sha256(champion_path),
    )

    monkeypatch.setattr(
        promotion.LGBMForecaster,
        "load",
        lambda path: candidate if Path(path) == candidate_path else champion,
    )
    monkeypatch.setattr(
        promotion,
        "prediction_drift_report",
        lambda *_args, **_kwargs: {
            "valid": True,
            "meanAbsDeltaMw": 100.0,
            "maxAbsDeltaMw": 300.0,
        },
    )
    monkeypatch.setattr(
        promotion,
        "hourly_estimator_fingerprints",
        lambda _model: {"model_q50": "fingerprint"},
    )

    report = promotion.promote(
        candidate_path=candidate_path,
        out_dir=out_dir,
        cache=pd.DataFrame({"ts": []}),
        config=config,
        same_day_development=development,
        same_day_holdout=holdout,
        day_ahead_development=day_ahead_development,
        day_ahead_holdout=day_ahead_holdout,
        target_date=date(2026, 8, 21),
        approve=True,
        allow_large_drift=False,
    )

    assert champion_path.read_bytes() == b"candidate-v14-r2"
    assert (out_dir / ".lgbm_model.rollback.pkl").read_bytes() == b"champion-v11"
    state = promotion._read_json(
        out_dir / "metrics" / "same_regime_day_level_calibration.json"
    )
    assert state["artifactSha256"] == artifact_sha256(candidate_path)
    assert state["entries"][0]["meanResidualMw"] == -240.0
    assert report["status"] == "recovery_promoted"
    assert report["validation"]["dayAheadHoldoutGate"]["passed"] is True
    assert report["rollback"]["sourceChampionSha256"] == artifact_sha256(
        out_dir / ".lgbm_model.rollback.pkl"
    )
