"""Tests for deterministic fallback AI daily operation reports."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from python.eval.ai_daily_report import (
    PROJECT_OPENAI_API_KEY_ENV,
    _build_openai_fact_packet,
    _merge_openai_analysis,
    _openai_analysis_schema,
    _validate_localized_analysis,
    build_ai_daily_report,
    build_ai_daily_reports,
    build_ai_daily_reports_multilingual,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_operation_fixture(tmp_path: Path, date_iso: str = "2026-05-23") -> None:
    _write_json(tmp_path / "reports" / "daily" / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "reports": [{"date": date_iso, "availability": "ok"}],
    })
    _write_json(tmp_path / "reports" / "daily" / f"{date_iso}.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "generatedAt": "2026-05-24T08:20:00+09:00",
        "date": date_iso,
        "availability": "ok",
        "model": {"name": "lgbm_quantile_q50", "family": "lgbm_quantile_q50"},
        "summary": {
            "comparableHours": 24,
            "modelMaeMw": 535.2,
            "tepcoMaeMw": 279.0,
            "modelWapePct": 2.23,
            "tepcoWapePct": 1.16,
            "modelRmseMw": 732.9,
            "tepcoRmseMw": 382.4,
            "modelMaxErrorMw": 2008.3,
            "tepcoMaxErrorMw": 1110.0,
            "modelMaxErrorHour": 8,
            "tepcoMaxErrorHour": 8,
            "maeGapMw": 256.2,
            "wapeGapPct": 1.07,
            "verdict": "tepco_better",
            "modelAdvantageHours": 3,
            "tepcoAdvantageHours": 21,
            "equalHours": 0,
            "modelAdvantageRate": 0.125,
        },
        "topMisses": [
            {
                "hour": 8,
                "actualMw": 23_000.0,
                "modelForecastMw": 25_008.3,
                "tepcoForecastMw": 23_600.0,
                "modelErrorMw": 2008.3,
                "tepcoErrorMw": 600.0,
                "modelAbsErrorMw": 2008.3,
                "tepcoAbsErrorMw": 600.0,
            }
        ],
        "insights": [
            {
                "code": "morning_ramp_overestimated",
                "severity": "warning",
                "title": "Morning demand was lower than the model expected.",
                "evidence": {"band": "06-10", "modelBiasMw": 1000.0},
            }
        ],
    })
    _write_json(tmp_path / "actual" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "actualMw": 20_000.0,
                "actualSource": "observed",
                "tepcoForecastMw": 20_100.0,
            }
            for hour in range(24)
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "forecastMw": 20_500.0 + hour * 10,
            }
            for hour in range(24)
        ],
    })


def test_ai_daily_report_builds_korean_fallback_without_calibration(tmp_path):
    _write_operation_fixture(tmp_path)

    report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    assert report["availability"] == "ok"
    assert report["language"] == "ko"
    assert report["generator"] == {
        "provider": "fallback",
        "model": None,
        "promptVersion": "fallback_rules_v1",
        "schemaVersion": "1.0.0",
    }
    assert report["inputRefs"]["operationalCalibration"] is None
    assert report["inputRefs"]["operationalCalibrationHistory"] is None
    assert report["dataQuality"]["observedHours"] == 24
    assert report["dataQuality"]["calibrationSnapshotCount"] == 0
    assert report["executiveSummary"]["modelVerdict"] == "tepco_better"
    assert report["rootCauseHypotheses"][0]["evidenceStatus"] == "partial"
    assert report["featureRecommendations"][0]["autoApply"] is False
    assert any("operational-calibration" in item for item in report["limitations"])


def test_ai_daily_report_builds_english_and_japanese_fallbacks(tmp_path):
    _write_operation_fixture(tmp_path)

    en_report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        language="en",
        use_openai=False,
    )
    ja_report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        language="ja",
        use_openai=False,
    )

    assert en_report["language"] == "en"
    assert "TEPCO" in en_report["executiveSummary"]["headline"]
    assert "comparable hours" in en_report["executiveSummary"]["summary"]
    assert en_report["rootCauseHypotheses"][0]["title"] == "The morning ramp may have been overestimated."
    assert en_report["featureRecommendations"][0]["autoApply"] is False

    assert ja_report["language"] == "ja"
    assert "TEPCO" in ja_report["executiveSummary"]["headline"]
    assert "比較可能時間" in ja_report["executiveSummary"]["summary"]
    assert ja_report["rootCauseHypotheses"][0]["title"] == "朝ramp帯で需要を高く見た可能性があります。"
    assert ja_report["featureRecommendations"][0]["autoApply"] is False


def test_ai_daily_report_marks_calibration_evidence_confirmed(tmp_path):
    date_iso = "2026-05-23"
    _write_operation_fixture(tmp_path, date_iso)
    _write_json(
        tmp_path / "reports" / "internal" / "operational-calibration" / f"{date_iso}.json",
        {
            "schemaVersion": "1.0.0",
            "date": date_iso,
            "correction": {
                "businessTypeTransitionPriorApplied": True,
                "businessTypeTransitionPriorBiasMw": -420.0,
                "negResidualRecoveryDampingApplied": True,
                "negResidualRecoveryDampingFactor": 0.4,
            },
        },
    )

    report = build_ai_daily_report(
        tmp_path,
        date_iso,
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    confirmed = [
        hypothesis for hypothesis in report["rootCauseHypotheses"]
        if hypothesis["evidenceStatus"] == "confirmed"
    ]
    assert confirmed
    assert report["inputRefs"]["operationalCalibration"] == (
        "reports/internal/operational-calibration/2026-05-23.json"
    )


def test_ai_daily_report_uses_calibration_snapshot_history(tmp_path):
    date_iso = "2026-05-23"
    _write_operation_fixture(tmp_path, date_iso)
    _write_json(
        tmp_path
        / "reports"
        / "internal"
        / "operational-calibration"
        / "snapshots"
        / date_iso
        / "index.json",
        {
            "schemaVersion": "1.0.0",
            "date": date_iso,
            "snapshots": [
                {
                    "generatedAt": "2026-05-23T07:20:00+09:00",
                    "applied": True,
                    "appliedRegimeReason": ["business_type_transition_prior_lag_overheat"],
                },
                {
                    "generatedAt": "2026-05-23T09:20:00+09:00",
                    "applied": True,
                    "appliedRegimeReason": ["negative_residual_recovery_damping_triggered"],
                },
            ],
        },
    )

    report = build_ai_daily_report(
        tmp_path,
        date_iso,
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    assert report["inputRefs"]["operationalCalibrationHistory"] == (
        "reports/internal/operational-calibration/snapshots/2026-05-23/index.json"
    )
    assert report["dataQuality"]["calibrationSnapshotCount"] == 2
    assert any(
        hypothesis["evidenceStatus"] == "confirmed"
        and "스냅샷" in hypothesis["title"]
        for hypothesis in report["rootCauseHypotheses"]
    )


def test_ai_report_fact_packet_separates_final_and_intraday_coverage(tmp_path):
    date_iso = "2026-05-23"
    _write_operation_fixture(tmp_path, date_iso)
    _write_json(
        tmp_path / "reports" / "internal" / "operational-calibration" / f"{date_iso}.json",
        {
            "schemaVersion": "1.0.0",
            "date": date_iso,
            "generatedAt": "2026-05-23T22:39:00+09:00",
            "correction": {
                "applied": True,
                "observedHours": 22,
                "lastObservedHour": 21,
                "sourceConfidence": {
                    "level": "observed",
                    "usableObservedHours": 22,
                    "missingHours": 2,
                },
            },
        },
    )
    report = build_ai_daily_report(
        tmp_path,
        date_iso,
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    fact_packet = _build_openai_fact_packet(tmp_path, {"ko": report})

    assert fact_packet["dataQuality"]["observedHours"] == 24
    assert fact_packet["coverageContext"]["finalActualCoverage"] == {
        "scope": "final_daily_actuals_for_performance",
        "comparableHours": 24,
        "observedHours": 24,
        "fallbackActualHours": 0,
    }
    assert fact_packet["coverageContext"]["intradayCalibrationCoverage"] == {
        "scope": "retained_intraday_calibration_snapshot_not_final_actual_csv",
        "observedHours": 22,
        "missingHours": 2,
        "lastObservedHour": 21,
        "sourceConfidence": "observed",
    }


def test_ai_report_fact_packet_marks_signed_error_direction(tmp_path):
    _write_operation_fixture(tmp_path)
    report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    fact_packet = _build_openai_fact_packet(tmp_path, {"ko": report})

    assert fact_packet["errorSignConvention"]["modelErrorMw"] == (
        "modelForecastMw - actualMw"
    )
    assert fact_packet["errorSignConvention"]["positive"] == (
        "overprediction_forecast_above_actual"
    )
    top_miss = fact_packet["operationFacts"]["topMisses"][0]
    assert top_miss["modelErrorDirection"] == "overprediction"
    assert top_miss["tepcoErrorDirection"] == "overprediction"
    focused = next(row for row in fact_packet["focusedRows"] if row["hour"] == 8)
    assert focused["modelErrorDirection"] == "overprediction"


def test_ai_daily_report_clarifies_intraday_snapshot_coverage_note(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path)
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")

    def fake_openai_analysis(context, api_key, model):
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "TEPCO가 더 낮은 오차를 보였습니다.",
                "summary": "확정 실측 기준으로 비교했습니다.",
                "modelVerdict": "tepco_better",
                "confidence": "high",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h1",
                    "severity": "warning",
                    "confidence": "medium",
                    "evidenceStatus": "partial",
                    "title": "낮 시간대 오차가 컸습니다.",
                    "explanation": "모델의 낮 시간대 오차가 TEPCO보다 컸습니다.",
                    "evidence": [
                        {
                            "source": "timeBands",
                            "metric": "daytime modelMaeMw",
                            "value": 500,
                            "unit": "MW",
                            "hour": None,
                            "timeBand": "11-15",
                        }
                    ],
                    "relatedHours": [11, 12],
                    "relatedTimeBands": ["11-15"],
                    "relatedFeatures": ["lag_24h"],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r1",
                    "priority": "medium",
                    "type": "evaluation",
                    "target": "timeband_replay",
                    "suggestion": "낮 시간대 replay를 확인합니다.",
                    "expectedEffect": "반복되는 오차인지 확인합니다.",
                    "risk": "단일 날짜에 과적합할 수 있습니다.",
                    "validationPlan": "최근 2주 replay로 검증합니다.",
                    "linkedHypotheses": ["h1"],
                    "autoApply": False,
                }
            ],
            "operatorNotes": [
                "성능 메트릭에 대한 전체 시간 커버리지는 완전하였고, 보정은 2시간 누락된 스냅샷 논리에 기반하여 22개의 관찰 시간에 의존하였습니다."
            ],
            "limitations": ["요약된 운영 증거와 보정 스냅샷을 사용했습니다."],
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_openai_analysis,
    )

    report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=True,
    )

    assert report["operatorNotes"] == [
        "성능 평가는 확정 CSV의 24시간 실측을 기준으로 했고, intraday 보정 스냅샷은 확정 전 운영 이력으로만 참고했습니다."
    ]


def test_ai_daily_report_can_merge_openai_narrative(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path)
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")
    monkeypatch.delenv("OPENAI_DAILY_REPORT_MODEL", raising=False)

    def fake_openai_analysis(context, api_key, model):
        assert api_key == "test-key"
        assert "fallbackReport" not in context
        assert "fallbackNarrativeByLanguage" not in context["factPacket"]
        assert "fingerprint" not in context["factPacket"]
        assert context["factPacket"]["performance"]["modelMaeMw"] == 535.2
        assert "summary" not in context["factPacket"]["operationFacts"]
        assert "insights" not in context["factPacket"]["operationFacts"]
        snapshot = context["factPacket"]["inputSnapshot"]
        assert "fingerprint" not in snapshot
        assert all(
            "path" not in source and "fingerprint" not in source
            for source in snapshot["sources"].values()
        )
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "OpenAI 분석 헤드라인",
                "summary": "입력 JSON 근거만 사용한 분석입니다.",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h-openai",
                    "severity": "warning",
                    "confidence": "high",
                    "evidenceStatus": "not_observed",
                    "title": "중간 실행 이력은 확인되지 않았습니다.",
                    "explanation": "스냅샷이 없어 단정하지 않습니다.",
                    "evidence": [],
                    "relatedHours": [8],
                    "relatedTimeBands": [],
                    "relatedFeatures": ["lag_24h"],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r-openai",
                    "priority": "high",
                    "type": "feature_engineering",
                    "target": "lag_24h",
                    "suggestion": "lag 영향도를 검토합니다.",
                    "expectedEffect": "WAPE 개선 후보입니다.",
                    "risk": "단일 날짜 과적합 위험이 있습니다.",
                    "validationPlan": "replay로 검증합니다.",
                    "proposedReplayCommand": "python run_replay.py --date 2026-05-23 --compare baseline",
                    "commandStatus": "proposed_not_implemented",
                    "linkedHypotheses": ["h-openai"],
                    "autoApply": True,
                }
            ],
            "operatorNotes": ["OpenAI provider 테스트"],
            "limitations": ["not_observed는 low confidence로 강제됩니다."],
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_openai_analysis,
    )

    report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=True,
    )

    assert report["generator"]["provider"] == "openai"
    assert report["generator"]["model"] == "gpt-4o-mini"
    assert "diagnosticContext" in report
    assert report["performance"]["modelMaeMw"] == 535.2
    assert report["executiveSummary"]["headline"] == "TEPCO 예측의 일간 오차가 모델보다 작았습니다."
    openai_hypothesis = next(
        item for item in report["rootCauseHypotheses"]
        if item["id"] == "h-openai"
    )
    assert openai_hypothesis["confidence"] == "low"
    assert report["featureRecommendations"][0]["autoApply"] is False
    assert report["featureRecommendations"][0]["proposedReplayCommand"].startswith(
        "python run_replay.py"
    )
    assert report["featureRecommendations"][0]["commandStatus"] == "proposed_not_implemented"


def test_openai_merge_repairs_metric_terms_and_invalid_recommendation_links():
    fallback_report = {
        "language": "ko",
        "contentLanguage": "ko",
        "generator": {
            "provider": "fallback",
            "model": None,
            "promptVersion": "fallback_rules_v1",
            "schemaVersion": "1.0.0",
        },
        "dataQuality": {
            "observedHours": 24,
            "fallbackActualHours": 0,
            "limitations": [],
        },
        "diagnosticContext": {
            "freezeImpact": {
                "largestGaps": [{"hour": 14, "freezeGapMw": -2058.9}],
            },
        },
        "executiveSummary": {
            "severity": "warning",
            "headline": "fallback",
            "summary": "fallback",
            "modelVerdict": "tepco_better",
            "confidence": "medium",
        },
        "performance": {
            "comparableHours": 24,
            "modelMaeMw": 675.2,
            "tepcoMaeMw": 278.3,
            "modelWapePct": 2.61,
            "tepcoWapePct": 1.07,
            "modelAdvantageHours": 4,
            "tepcoAdvantageHours": 20,
            "verdict": "tepco_better",
        },
        "rootCauseHypotheses": [],
        "featureRecommendations": [],
        "operatorNotes": [],
        "limitations": [],
    }
    analysis = {
        "executiveSummary": {
            "severity": "critical",
            "headline": "TEPCO가 낮 시간대에 모델을 크게 초과 달성했습니다",
            "summary": "TEPCO의 일일 MAPE는 1.07%로 모델의 2.61%보다 우수했습니다.",
            "modelVerdict": "tepco_better",
            "confidence": "high",
        },
        "rootCauseHypotheses": [
            {
                "id": "hp2",
                "severity": "warning",
                "confidence": "medium",
                "evidenceStatus": "partial",
                "title": "Freeze policy left a serving gap.",
                "explanation": "The published line differed from the recalculated line.",
                "evidence": [
                    {
                        "source": "freezeImpact",
                        "metric": "largestGaps",
                        "value": -2058.9,
                        "unit": "MW",
                        "hour": 14,
                        "timeBand": "daytime",
                    }
                ],
                "relatedHours": [14],
                "relatedTimeBands": ["daytime"],
                "relatedFeatures": ["serving.published_forecast_freeze"],
                "counterEvidence": [],
            }
        ],
        "featureRecommendations": [
            {
                "id": "fr1",
                "priority": "high",
                "type": "calibration",
                "target": "intraday_correction.negative_residual_recovery_damping",
                "suggestion": "Backtest the damping factor.",
                "expectedEffect": "Reduce peak risk.",
                "risk": "Could overfit one day.",
                "validationPlan": "Replay comparable days.",
                "linkedHypotheses": ["hp1"],
                "autoApply": True,
            },
            {
                "id": "fr2",
                "priority": "medium",
                "type": "evaluation",
                "target": "intraday_correction.day_boundary_carryover",
                "suggestion": "Replay freeze-gap refresh candidates.",
                "expectedEffect": "Reduce visible serving drift.",
                "risk": "The public line may look less stable.",
                "validationPlan": "Compare published and recalculated gaps.",
                "linkedHypotheses": ["hp2"],
                "autoApply": True,
            },
        ],
        "operatorNotes": [],
        "limitations": [],
    }

    report = _merge_openai_analysis(fallback_report, analysis, "gpt-4o-mini")

    assert "MAPE" not in report["executiveSummary"]["summary"]
    assert "WAPE" in report["executiveSummary"]["summary"]
    assert report["executiveSummary"]["headline"] == (
        "TEPCO 예측의 일간 오차가 모델보다 작았습니다."
    )
    assert [item["id"] for item in report["featureRecommendations"]] == ["r1"]
    assert report["featureRecommendations"][0]["target"] == (
        "serving.published_forecast_freeze"
    )
    assert report["featureRecommendations"][0]["linkedHypotheses"] == [
        "serving.published_forecast_freeze"
    ]
    assert report["featureRecommendations"][0]["autoApply"] is False


def test_ai_daily_report_rejects_openai_signed_error_contradiction(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path)
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")

    def fake_openai_analysis(context, api_key, model):
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "Signed error contradiction test",
                "summary": "The deterministic metrics are retained.",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h-bad-sign",
                    "severity": "warning",
                    "confidence": "high",
                    "evidenceStatus": "partial",
                    "title": "Daytime underprediction despite a positive bias",
                    "explanation": (
                        "The model underprediction should not be accepted when "
                        "modelBiasMw is positive."
                    ),
                    "evidence": [
                        {
                            "source": "reports/internal/daily-diagnostics",
                            "metric": "modelBiasMw",
                            "value": 1000.0,
                            "unit": "MW",
                            "hour": None,
                            "timeBand": "daytime",
                        }
                    ],
                    "relatedHours": [],
                    "relatedTimeBands": ["daytime"],
                    "relatedFeatures": ["lag_24h"],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r1",
                    "priority": "medium",
                    "type": "feature_engineering",
                    "target": "lag_24h",
                    "suggestion": "Backtest lag inertia thresholds.",
                    "expectedEffect": "Reduce directional bias.",
                    "risk": "A single-day pattern may be overfit.",
                    "validationPlan": "Replay recent high-error days.",
                    "proposedReplayCommand": None,
                    "commandStatus": None,
                    "linkedHypotheses": ["h-bad-sign"],
                    "autoApply": False,
                }
            ],
            "operatorNotes": [],
            "limitations": [],
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_openai_analysis,
    )

    report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        language="en",
        use_openai=True,
    )

    assert report["rootCauseHypotheses"][0]["title"] == (
        "The morning ramp may have been overestimated."
    )
    assert report["rootCauseHypotheses"][0]["title"] != (
        "Daytime underprediction despite a positive bias"
    )


def test_openai_analysis_schema_requires_nullable_recommendation_fields():
    schema = _openai_analysis_schema()
    recommendation_schema = schema["properties"]["featureRecommendations"]["items"]

    assert "proposedReplayCommand" in recommendation_schema["properties"]
    assert "commandStatus" in recommendation_schema["properties"]
    assert "proposedReplayCommand" in recommendation_schema["required"]
    assert "commandStatus" in recommendation_schema["required"]


def test_openai_merge_normalizes_empty_command_and_mw_unit(tmp_path):
    _write_operation_fixture(tmp_path)
    fallback = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    report = _merge_openai_analysis(
        fallback,
        {
            "executiveSummary": {
                "severity": "warning",
                "headline": "TEPCO had lower daily error in daytime hours.",
                "summary": "The model miss was concentrated in the daytime band.",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h1",
                    "severity": "warning",
                    "confidence": "medium",
                    "evidenceStatus": "partial",
                    "title": "Daytime forecast bias remained visible.",
                    "explanation": "The largest miss was in the daytime band.",
                    "evidence": [
                        {
                            "source": "topMisses",
                            "metric": "modelAbsErrorMw",
                            "value": 1000,
                            "unit": "Mw",
                            "hour": 12,
                            "timeBand": "daytime",
                        }
                    ],
                    "relatedHours": [12],
                    "relatedTimeBands": ["daytime"],
                    "relatedFeatures": ["serving.published_forecast_freeze"],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r1",
                    "priority": "medium",
                    "type": "evaluation",
                    "target": "serving.published_forecast_freeze",
                    "suggestion": "Compare published and recalculated forecast gaps.",
                    "expectedEffect": "This separates raw model error from serving freeze effects.",
                    "risk": "Single-day analysis may overstate the serving effect.",
                    "validationPlan": "Replay recent business days with freeze impact reporting.",
                    "proposedReplayCommand": "",
                    "commandStatus": "proposed_not_implemented",
                    "linkedHypotheses": ["h1"],
                    "autoApply": False,
                }
            ],
            "operatorNotes": [],
            "limitations": [],
        },
        "gpt-4o-mini",
    )

    assert report["rootCauseHypotheses"][0]["evidence"][0]["unit"] == "MW"
    assert "proposedReplayCommand" not in report["featureRecommendations"][0]
    assert "commandStatus" not in report["featureRecommendations"][0]


def test_openai_fact_packet_adds_focused_rows_and_control_context(monkeypatch, tmp_path):
    date_iso = "2026-05-23"
    _write_operation_fixture(tmp_path, date_iso)
    _write_json(tmp_path / "reports" / "daily" / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "reports": [
            {"date": "2026-05-21", "availability": "ok"},
            {"date": "2026-05-22", "availability": "ok"},
            {"date": date_iso, "availability": "ok"},
        ],
    })
    for historical_date in ("2026-05-21", "2026-05-22"):
        _write_operation_fixture(tmp_path, historical_date)
        payload = json.loads(
            (tmp_path / "reports" / "daily" / f"{historical_date}.json").read_text(
                encoding="utf-8"
            )
        )
        payload["timeBands"] = [
            {
                "code": "daytime",
                "label": "11-15",
                "hours": 5,
                "modelMaeMw": 640.0,
                "tepcoMaeMw": 350.0,
                "modelBiasMw": -620.0,
                "verdict": "tepco_better",
            }
        ]
        _write_json(tmp_path / "reports" / "daily" / f"{historical_date}.json", payload)
    current_payload = json.loads(
        (tmp_path / "reports" / "daily" / f"{date_iso}.json").read_text(
            encoding="utf-8"
        )
    )
    current_payload["timeBands"] = [
        {
            "code": "daytime",
            "label": "11-15",
            "hours": 5,
            "modelMaeMw": 620.0,
            "tepcoMaeMw": 360.0,
            "modelBiasMw": -540.0,
            "verdict": "tepco_better",
        }
    ]
    _write_json(tmp_path / "reports" / "daily" / f"{date_iso}.json", current_payload)
    _write_json(tmp_path / "reports" / "daily" / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "reports": [
            {"date": "2026-05-21", "availability": "ok"},
            {"date": "2026-05-22", "availability": "ok"},
            {"date": date_iso, "availability": "ok"},
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T{hour:02d}:00:00+09:00",
                "forecastMw": 33_923.0 if hour == 15 else 30_000.0 + hour,
                "p95LowerMw": 0.0,
                "p95UpperMw": 50_000.0,
                "p99LowerMw": 0.0,
                "p99UpperMw": 55_000.0,
            }
            for hour in range(24)
        ],
    })
    _write_json(
        tmp_path / "reports" / "internal" / "operational-calibration" / f"{date_iso}.json",
        {
            "schemaVersion": "1.0.0",
            "date": date_iso,
            "correction": {
                "applied": True,
                "observedHours": 15,
                "lastObservedHour": 14,
                "baseAdjustmentMw": 662.0,
                "positiveResidualSlopeDampingApplied": True,
                "positiveResidualSlopeDampingFactor": 0.4,
                "positiveResidualSlopeDampingMaxMw": 596.0,
                "appliedRegimeReason": [
                    "positive_residual_slope_damping_triggered",
                ],
                "residualCarryoverByHour": [
                    {
                        "hour": 15,
                        "leadHours": 1,
                        "prePositiveDampingAdjustmentMw": 662.0,
                        "positiveResidualSlopeDampingFactor": 0.4,
                        "finalAdjustmentMw": 264.8,
                    }
                ],
            },
            "hourlyDiagnostics": [
                {
                    "hour": 15,
                    "ts": f"{date_iso}T15:00:00+09:00",
                    "actualMw": 32_400.0,
                    "actualSource": "observed",
                    "tepcoForecastMw": 32_800.0,
                    "forecastMwByStage": {
                        "raw_lgbm": 33_000.0,
                        "analog_adjusted": 33_100.0,
                        "post_holiday_guarded": 33_049.2,
                        "midday_guarded": 33_049.2,
                        "pre_calibration": 33_049.2,
                    },
                    "preCalibrationForecastMw": 33_049.2,
                    "postCalibrationForecastMw": 33_314.0,
                    "calibrationDeltaMw": 264.8,
                    "actualVsPostCalibrationResidualMw": -914.0,
                    "residualCarryover": {
                        "hour": 15,
                        "leadHours": 1,
                        "prePositiveDampingAdjustmentMw": 662.0,
                        "positiveResidualSlopeDampingFactor": 0.4,
                        "finalAdjustmentMw": 264.8,
                    },
                }
            ],
        },
    )
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")

    def fake_openai_analysis(context, api_key, model):
        fact_packet = context["factPacket"]
        focused_rows = fact_packet["focusedRows"]
        focused_by_hour = {row["hour"]: row for row in focused_rows}
        assert len(focused_rows) <= 12
        assert focused_by_hour[15]["publishedVsLatestRecalculatedGapMw"] == 609.0
        assert fact_packet["freezeContext"]["largestGaps"][0]["freezeGapMw"] == 609.0
        assert fact_packet["freezeImpact"]["largestGaps"][0]["freezeGapMw"] == 609.0
        damping = fact_packet["controlContext"]["positiveResidualSlopeDamping"]
        assert damping["applied"] is True
        assert damping["factor"] == 0.4
        assert damping["affectedHours"] == [15]
        diagnosis = fact_packet["controllerDiagnosis"]
        assert diagnosis["baseAdjustmentMw"] == 662.0
        assert diagnosis["direction"] == "upward"
        assert diagnosis["capHitLikely"] is False
        assert diagnosis["residualTrend"]["latestResidualMw"] == -914.0
        stage_row = fact_packet["stageAttribution"]["largestStageShifts"][0]
        assert stage_row["hour"] == 15
        assert stage_row["largestStageDelta"] == {
            "stage": "published",
            "delta_mw": 609.0,
            "delta_from": "post_calibration",
        }
        assert stage_row["stageImpactSummary"][0] == {
            "stage": "raw_lgbm",
            "label": "raw lgbm",
            "value_mw": 33000.0,
            "delta_mw": 0.0,
        }
        assert fact_packet["bandQuality"]["p95CoverageHours"] == 24
        rolling = fact_packet["rollingPatternContext"]
        assert rolling["lookbackDays"] == 3
        assert rolling["recentTrendVerdict"] == "daytime_underprediction_repeated"
        assert rolling["sameBandRepeatedMisses"][0]["band"] == "daytime"
        assert rolling["sameBandRepeatedMisses"][0]["sameDirectionMissDays"] == 3
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "Focused rows were used.",
                "summary": "The analysis used compact focused rows and calibration context.",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [],
            "featureRecommendations": [],
            "operatorNotes": [],
            "limitations": [],
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_openai_analysis,
    )

    report = build_ai_daily_report(
        tmp_path,
        date_iso,
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=True,
    )

    assert report["generator"]["provider"] == "openai"
    assert report["executiveSummary"]["headline"] == "TEPCO 예측의 일간 오차가 모델보다 작았습니다."


def test_ai_daily_report_rejects_empty_openai_sections(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path)
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")

    def fake_openai_analysis(context, api_key, model):
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "OpenAI headline",
                "summary": "OpenAI summary",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h-bad",
                    "severity": "info",
                    "confidence": "high",
                    "evidenceStatus": "partial",
                    "title": "Root-cause hypothesis",
                    "explanation": "",
                    "evidence": [],
                    "relatedHours": [],
                    "relatedTimeBands": [],
                    "relatedFeatures": [],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r-bad",
                    "priority": "medium",
                    "type": "feature_engineering",
                    "target": "review_candidate",
                    "suggestion": "",
                    "expectedEffect": "",
                    "risk": "",
                    "validationPlan": "",
                    "linkedHypotheses": [],
                    "autoApply": False,
                }
            ],
            "operatorNotes": [],
            "limitations": [],
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_openai_analysis,
    )

    report = build_ai_daily_report(
        tmp_path,
        "2026-05-23",
        generated_at="2026-05-24T08:20:00+09:00",
        language="en",
        use_openai=True,
    )

    assert report["generator"]["provider"] == "openai"
    assert report["rootCauseHypotheses"][0]["title"] == "The morning ramp may have been overestimated."
    assert report["rootCauseHypotheses"][0]["explanation"]
    assert report["featureRecommendations"][0]["target"] == "lag_24h"
    assert report["featureRecommendations"][0]["suggestion"]


def test_ai_daily_report_reuses_existing_report_when_skip_existing(monkeypatch, tmp_path):
    date_iso = "2026-05-23"
    _write_operation_fixture(tmp_path, date_iso)
    report_dir = tmp_path / "reports" / "ai" / "daily" / "ko"
    existing_report = {
        "schemaVersion": "1.0.0",
        "reportType": "ai_daily_operation_report",
        "timezone": "Asia/Tokyo",
        "date": date_iso,
        "generatedAt": "2026-05-24T07:20:00+09:00",
        "availability": "ok",
        "language": "ko",
        "generator": {
            "provider": "fallback",
            "model": None,
            "promptVersion": "fallback_rules_v1",
            "schemaVersion": "1.0.0",
        },
        "inputRefs": {},
        "dataQuality": {
            "comparableHours": 24,
            "observedHours": 24,
            "fallbackActualHours": 0,
            "limitations": [],
        },
        "executiveSummary": {
            "severity": "info",
            "headline": "기존 리포트",
            "summary": "이미 생성된 리포트입니다.",
            "modelVerdict": "model_better",
            "confidence": "high",
        },
        "performance": {"modelMaeMw": 1.0, "tepcoMaeMw": 2.0},
        "rootCauseHypotheses": [],
        "featureRecommendations": [],
        "operatorNotes": [],
        "limitations": [],
    }
    _write_json(report_dir / f"{date_iso}.json", existing_report)
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")

    def fail_openai_call(*args, **kwargs):
        raise AssertionError("OpenAI should not be called for existing reports")

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fail_openai_call,
    )

    index, reports = build_ai_daily_reports(
        tmp_path,
        generated_at="2026-05-24T09:20:00+09:00",
        existing_report_dir=report_dir,
        skip_existing=True,
        use_openai=False,
    )

    assert index["latest"]["headline"] == "기존 리포트"
    assert reports == [existing_report]


def test_ai_daily_reports_caps_openai_to_latest_korean_report(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path, "2026-05-22")
    _write_operation_fixture(tmp_path, "2026-05-23")
    _write_json(tmp_path / "reports" / "daily" / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "reports": [
            {"date": "2026-05-22", "availability": "ok"},
            {"date": "2026-05-23", "availability": "ok"},
        ],
    })
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")
    calls = []

    def fake_openai_analysis(context, api_key, model):
        calls.append(context["factPacket"]["date"])
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": f"OpenAI {context['factPacket']['date']}",
                "summary": "최신 날짜만 OpenAI로 생성합니다.",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [],
            "featureRecommendations": [],
            "operatorNotes": [],
            "limitations": [],
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_openai_analysis,
    )
    budget = {"remaining": 1, "used": 0}

    index, reports = build_ai_daily_reports(
        tmp_path,
        generated_at="2026-05-24T09:20:00+09:00",
        max_days=2,
        language="ko",
        openai_budget=budget,
        openai_locales={"ko"},
    )

    assert calls == ["2026-05-23"]
    assert budget == {"remaining": 0, "used": 1}
    assert [report["generator"]["provider"] for report in reports] == [
        "fallback",
        "openai",
    ]
    assert index["latest"]["headline"] == "TEPCO 예측의 일간 오차가 모델보다 작았습니다."


def test_ai_daily_reports_multilingual_uses_master_and_localization_calls(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path, "2026-05-23")
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")
    calls = []

    def fake_master_analysis(context, api_key, model):
        fact_packet = context["factPacket"]
        operation_facts = fact_packet["operationFacts"]
        snapshot = fact_packet["inputSnapshot"]
        calls.append({
            "stage": "master",
            "language": context["language"],
            "date": fact_packet["date"],
            "has_top_misses": bool(operation_facts["topMisses"]),
            "has_fallback_report": "fallbackReport" in context,
            "has_fallback_narrative": "fallbackNarrativeByLanguage" in fact_packet,
            "has_operation_summary": "summary" in operation_facts,
            "has_insights": "insights" in operation_facts,
            "has_snapshot_fingerprint": "fingerprint" in snapshot,
            "source_has_path_or_fingerprint": any(
                "path" in source or "fingerprint" in source
                for source in snapshot["sources"].values()
            ),
        })
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "English master headline",
                "summary": "English master summary",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h-transition",
                    "severity": "warning",
                    "confidence": "medium",
                    "evidenceStatus": "partial",
                    "title": "Weekday lag likely lifted the morning ramp.",
                    "explanation": "The model overestimated the morning ramp while lag_24h was elevated.",
                    "evidence": [
                        {
                            "source": "operationReport",
                            "metric": "modelMaxErrorMw",
                            "value": 2008.3,
                            "unit": "MW",
                            "hour": 8,
                            "timeBand": "morning_ramp",
                        }
                    ],
                    "relatedHours": [8],
                    "relatedTimeBands": ["morning_ramp"],
                    "relatedFeatures": ["intraday_correction.business_type_transition_prior"],
                    "counterEvidence": ["Only the final run is available."],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r-transition",
                    "priority": "medium",
                    "type": "calibration",
                    "target": "intraday_correction.business_type_transition_prior",
                    "suggestion": "Replay transition days and tune the lag-overheat threshold.",
                    "expectedEffect": "Morning overestimation should shrink without changing raw forecasts.",
                    "risk": "Too much shrinkage can underpredict real weekend activity.",
                    "validationPlan": "Run recent transition-day replay and compare WAPE/RMSE.",
                    "linkedHypotheses": ["h-transition"],
                    "autoApply": False,
                }
            ],
            "operatorNotes": ["English note"],
            "limitations": ["English limitation"],
        }

    def fake_localization_analysis(context, api_key, model, languages):
        calls.append({
            "stage": "localization",
            "languages": list(languages),
            "model": model,
            "has_master_report": "masterReport" in context,
            "has_fact_packet": "factPacket" in context,
        })
        return {
            "reports": {
                "ko": {
                    "executiveSummary": {
                        "severity": "info",
                        "headline": "한국어 현지화 헤드라인",
                        "summary": "한국어 현지화 요약",
                        "modelVerdict": "model_better",
                        "confidence": "high",
                    },
                    "rootCauseHypotheses": [
                        {
                            "id": "h-transition",
                            "severity": "info",
                            "confidence": "high",
                            "evidenceStatus": "confirmed",
                            "title": "평일 lag가 오전 ramp를 들어 올렸을 가능성이 있습니다.",
                            "explanation": "모델은 오전 ramp를 과대예측했고 lag_24h가 높았습니다.",
                            "evidence": [],
                            "relatedHours": [],
                            "relatedTimeBands": [],
                            "relatedFeatures": [],
                            "counterEvidence": ["최종 실행분만 확인할 수 있습니다."],
                        }
                    ],
                    "featureRecommendations": [
                        {
                            "id": "r-transition",
                            "priority": "high",
                            "type": "feature_engineering",
                            "target": "changed_target",
                            "suggestion": "전환일 replay로 lag 과열 임계값을 튜닝합니다.",
                            "expectedEffect": "raw forecast를 바꾸지 않고 오전 과대예측을 줄입니다.",
                            "risk": "강도가 과하면 실제 주말 활동을 과소예측할 수 있습니다.",
                            "validationPlan": "전환일 replay에서 WAPE/RMSE를 비교합니다.",
                            "linkedHypotheses": [],
                            "autoApply": True,
                        }
                    ],
                    "operatorNotes": ["비즈니스 유형 전환과 잔여 감쇠를 확인합니다."],
                    "limitations": ["중간의 행복한 실행은 스냅샷으로 재구성되었습니다."],
                },
                "ja": {
                    "executiveSummary": {
                        "severity": "warning",
                        "headline": "日本語ローカライズ見出し",
                        "summary": "日本語ローカライズ要約",
                        "modelVerdict": "tepco_better",
                        "confidence": "medium",
                    },
                    "rootCauseHypotheses": [
                        {
                            "id": "h-transition",
                            "severity": "warning",
                            "confidence": "medium",
                            "evidenceStatus": "partial",
                            "title": "平日lagが朝のrampを押し上げた可能性があります。",
                            "explanation": "モデルは朝のrampを過大予測し、lag_24hが高い状態でした。",
                            "evidence": [],
                            "relatedHours": [],
                            "relatedTimeBands": [],
                            "relatedFeatures": [],
                            "counterEvidence": ["最終実行のみ確認できます。"],
                        }
                    ],
                    "featureRecommendations": [
                        {
                            "id": "r-transition",
                            "priority": "medium",
                            "type": "calibration",
                            "target": "intraday_correction.business_type_transition_prior",
                            "suggestion": "遷移日のreplayでlag過熱しきい値を調整します。",
                            "expectedEffect": "raw forecastを変えずに朝の過大予測を抑えます。",
                            "risk": "抑制が強すぎると実需要を過小予測します。",
                            "validationPlan": "遷移日replayでWAPE/RMSEを比較します。",
                            "linkedHypotheses": ["h-transition"],
                            "autoApply": False,
                        }
                    ],
                    "operatorNotes": ["朝のランプアップと残余ダンピングを確認します。"],
                    "limitations": ["日本語制約"],
                },
            }
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_master_analysis,
    )
    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_localization_analysis",
        fake_localization_analysis,
    )

    indexes, reports_by_language, budget = build_ai_daily_reports_multilingual(
        tmp_path,
        generated_at="2026-05-24T09:20:00+09:00",
        languages=("ko", "en", "ja"),
        openai_budget={"remaining": 2, "used": 0},
        openai_locales={"ko", "en", "ja"},
    )

    assert calls == [
        {
            "stage": "master",
            "language": "en",
            "date": "2026-05-23",
            "has_top_misses": True,
            "has_fallback_report": False,
            "has_fallback_narrative": False,
            "has_operation_summary": False,
            "has_insights": False,
            "has_snapshot_fingerprint": False,
            "source_has_path_or_fingerprint": False,
        },
        {
            "stage": "localization",
            "languages": ["ko", "ja"],
            "model": "gpt-4o-mini",
            "has_master_report": True,
            "has_fact_packet": False,
        },
    ]
    assert budget == {"remaining": 0, "used": 2}
    assert reports_by_language["ko"][0]["generator"]["provider"] == "openai"
    assert reports_by_language["ko"][0]["contentLanguage"] == "ko"
    assert reports_by_language["ko"][0]["generator"]["localizationModel"] == "gpt-4o-mini"
    assert reports_by_language["ko"][0]["generator"]["localizationStatus"] == "ok"
    assert reports_by_language["en"][0]["executiveSummary"]["headline"] == (
        "TEPCO had lower daily error than the model."
    )
    assert reports_by_language["ko"][0]["executiveSummary"]["headline"] == (
        "TEPCO 예측의 일간 오차가 모델보다 작았습니다."
    )
    assert reports_by_language["ko"][0]["executiveSummary"]["modelVerdict"] == "tepco_better"
    assert reports_by_language["ko"][0]["rootCauseHypotheses"][0]["evidenceStatus"] == "partial"
    assert reports_by_language["ko"][0]["featureRecommendations"][0]["target"] == (
        "intraday_correction.business_type_transition_prior"
    )
    assert reports_by_language["ko"][0]["featureRecommendations"][0]["autoApply"] is False
    assert reports_by_language["ko"][0]["operatorNotes"] == [
        "영업일 구분 전환과 잔차 감쇠를 확인합니다."
    ]
    assert reports_by_language["ko"][0]["limitations"] == [
        "중간에 덮어쓴 intraday 실행 내역은 스냅샷으로 재구성되었습니다."
    ]
    assert reports_by_language["ja"][0]["language"] == "ja"
    assert reports_by_language["ja"][0]["operatorNotes"] == [
        "朝のランプアップと残差ダンピングを確認します。"
    ]
    assert indexes["ko"]["latest"]["date"] == "2026-05-23"
    assert "inputSnapshot" in reports_by_language["ko"][0]


def test_ai_daily_reports_multilingual_retries_latest_existing_fallback(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path, "2026-05-23")
    report_root = tmp_path / "reports" / "ai" / "daily"
    for language in ("ko", "en", "ja"):
        fallback_report = build_ai_daily_report(
            tmp_path,
            "2026-05-23",
            generated_at="2026-05-24T08:20:00+09:00",
            language=language,
            use_openai=False,
        )
        _write_json(report_root / language / "2026-05-23.json", fallback_report)

    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")
    calls = []

    def fake_master_localization_chain(
        public_dir,
        date_iso,
        generated_at,
        fallback_reports,
        target_languages,
        api_key,
        model,
        localization_model,
        budget,
    ):
        calls.append({
            "date": date_iso,
            "target_languages": list(target_languages),
        })
        budget["remaining"] = max(0, budget["remaining"] - 2)
        budget["used"] += 2
        merged = {}
        for language, report in fallback_reports.items():
            merged_report = json.loads(json.dumps(report))
            merged_report["generator"] = {
                "provider": "openai",
                "model": model,
                "promptVersion": "openai_ops_report_v3",
                "schemaVersion": "1.0.0",
            }
            merged_report["executiveSummary"]["headline"] = f"OpenAI {language}"
            merged[language] = merged_report
        return merged

    monkeypatch.setattr(
        "python.eval.ai_daily_report._run_openai_master_localization_chain",
        fake_master_localization_chain,
    )

    indexes, reports_by_language, budget = build_ai_daily_reports_multilingual(
        tmp_path,
        generated_at="2026-05-24T09:20:00+09:00",
        languages=("ko", "en", "ja"),
        existing_report_root=report_root,
        skip_existing=True,
        openai_budget={"remaining": 2, "used": 0},
        openai_locales={"ko", "en", "ja"},
    )

    assert calls == [{
        "date": "2026-05-23",
        "target_languages": ["ko", "en", "ja"],
    }]
    assert budget == {"remaining": 0, "used": 2}
    assert reports_by_language["ko"][0]["generator"]["provider"] == "openai"
    assert reports_by_language["en"][0]["generator"]["provider"] == "openai"
    assert reports_by_language["ja"][0]["generator"]["provider"] == "openai"
    assert indexes["ko"]["latest"]["headline"] == "OpenAI ko"


def test_ai_daily_reports_multilingual_falls_back_to_english_when_localization_fails(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path, "2026-05-23")
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")

    def fake_master_analysis(context, api_key, model):
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "English master headline",
                "summary": "English master summary",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h-master",
                    "severity": "warning",
                    "confidence": "medium",
                    "evidenceStatus": "partial",
                    "title": "English master hypothesis",
                    "explanation": "The model missed the morning ramp.",
                    "evidence": [
                        {
                            "source": "operationReport",
                            "metric": "modelMaxErrorMw",
                            "value": 2008.3,
                            "unit": "MW",
                            "hour": 8,
                            "timeBand": "morning_ramp",
                        }
                    ],
                    "relatedHours": [8],
                    "relatedTimeBands": ["morning_ramp"],
                    "relatedFeatures": ["intraday_correction.business_type_transition_prior"],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r-master",
                    "priority": "medium",
                    "type": "calibration",
                    "target": "intraday_correction.business_type_transition_prior",
                    "suggestion": "Tune the transition prior by replaying similar days.",
                    "expectedEffect": "Morning MAE should improve.",
                    "risk": "Too much damping can underpredict real demand.",
                    "validationPlan": "Replay recent transition days and compare WAPE.",
                    "linkedHypotheses": ["h-master"],
                    "autoApply": False,
                }
            ],
            "operatorNotes": ["English operator note"],
            "limitations": ["English limitation"],
        }

    def fail_localization(*args, **kwargs):
        raise ValueError("localization schema failed")

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_master_analysis,
    )
    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_localization_analysis",
        fail_localization,
    )

    _, reports_by_language, budget = build_ai_daily_reports_multilingual(
        tmp_path,
        generated_at="2026-05-24T09:20:00+09:00",
        languages=("ko", "en", "ja"),
        openai_budget={"remaining": 2, "used": 0},
        openai_locales={"ko", "en", "ja"},
    )

    assert budget == {"remaining": 0, "used": 2}
    assert reports_by_language["en"][0]["contentLanguage"] == "en"
    assert reports_by_language["ko"][0]["language"] == "ko"
    assert reports_by_language["ko"][0]["contentLanguage"] == "en"
    assert reports_by_language["ko"][0]["executiveSummary"]["headline"] == (
        "TEPCO 예측의 일간 오차가 모델보다 작았습니다."
    )
    assert reports_by_language["ko"][0]["generator"]["localizationModel"] == "gpt-4o-mini"
    assert reports_by_language["ko"][0]["generator"]["localizationStatus"] == "fallback_en"
    assert reports_by_language["ko"][0]["generator"]["localizationFallback"] == "en"
    assert "Localization failed" in reports_by_language["ko"][0]["operatorNotes"][0]
    assert reports_by_language["ja"][0]["contentLanguage"] == "en"


def test_ai_daily_reports_multilingual_retries_invalid_localization_once(monkeypatch, tmp_path):
    _write_operation_fixture(tmp_path, "2026-05-23")
    monkeypatch.setenv(PROJECT_OPENAI_API_KEY_ENV, "test-key")
    localization_calls = []

    def fake_master_analysis(context, api_key, model):
        return {
            "executiveSummary": {
                "severity": "warning",
                "headline": "English master headline",
                "summary": "English master summary",
                "modelVerdict": "tepco_better",
                "confidence": "medium",
            },
            "rootCauseHypotheses": [
                {
                    "id": "h-master",
                    "severity": "warning",
                    "confidence": "medium",
                    "evidenceStatus": "partial",
                    "title": "English master hypothesis",
                    "explanation": "The model missed the evening shape.",
                    "evidence": [],
                    "relatedHours": [18],
                    "relatedTimeBands": ["evening"],
                    "relatedFeatures": ["intraday_correction.positive_residual_slope_damping"],
                    "counterEvidence": [],
                }
            ],
            "featureRecommendations": [
                {
                    "id": "r-master",
                    "priority": "medium",
                    "type": "calibration",
                    "target": "intraday_correction.positive_residual_slope_damping",
                    "suggestion": "Tune the evening damping trigger.",
                    "expectedEffect": "Evening overshoot should shrink.",
                    "risk": "Too much damping can underpredict a real rebound.",
                    "validationPlan": "Replay recent evening misses.",
                    "linkedHypotheses": ["h-master"],
                    "autoApply": False,
                }
            ],
            "operatorNotes": ["English operator note"],
            "limitations": ["English limitation"],
        }

    def fake_localization_analysis(context, api_key, model, languages):
        localization_calls.append(list(languages))
        if len(localization_calls) == 1:
            return {
                "reports": {
                    "ko": {
                        "executiveSummary": {
                            "headline": "TEPCO陛 24偃曖 綠掖 陛棟フ",
                            "summary": "賅筐 濰薄 衛除擎 8衛除 絮薄瞳戲煎",
                        }
                    },
                    "ja": {
                        "executiveSummary": {
                            "headline": "TEPCO肢24肥楑昳呇窆羌蒢忺",
                            "summary": "徉室恨肥跂屪蒢忺肢8蒢忺竺",
                        }
                    },
                }
            }
        return {
            "reports": {
                "ko": {
                    "executiveSummary": {
                        "headline": "TEPCO가 저녁 형태에서 더 안정적이었습니다",
                        "summary": "모델은 18시 주변에서 과대예측을 보였고 보정 가드 재검토가 필요합니다.",
                    },
                    "rootCauseHypotheses": [
                        {
                            "id": "h-master",
                            "title": "저녁 형태 오차가 관측되었습니다.",
                            "explanation": "모델은 저녁 반등을 크게 보았습니다.",
                        }
                    ],
                    "featureRecommendations": [
                        {
                            "id": "r-master",
                            "suggestion": "저녁 감쇠 트리거를 재생 검증합니다.",
                            "expectedEffect": "과대예측이 줄어듭니다.",
                            "risk": "진짜 반등을 낮게 볼 수 있습니다.",
                            "validationPlan": "최근 저녁 오차를 replay합니다.",
                        }
                    ],
                    "operatorNotes": ["한국어 현지화 재시도 성공"],
                    "limitations": ["요약 지표 기준입니다."],
                },
                "ja": {
                    "executiveSummary": {
                        "headline": "TEPCOは夕方の形状でより安定していました",
                        "summary": "モデルは18時付近で過大予測となり、補正ガードの再確認が必要です。",
                    },
                    "rootCauseHypotheses": [
                        {
                            "id": "h-master",
                            "title": "夕方の形状誤差が観測されました。",
                            "explanation": "モデルは夕方の反発を大きく見積もりました。",
                        }
                    ],
                    "featureRecommendations": [
                        {
                            "id": "r-master",
                            "suggestion": "夕方の減衰トリガーを再生検証します。",
                            "expectedEffect": "過大予測を抑えます。",
                            "risk": "本当の反発を低く見る可能性があります。",
                            "validationPlan": "直近の夕方誤差をreplayします。",
                        }
                    ],
                    "operatorNotes": ["日本語ローカライズ再試行成功"],
                    "limitations": ["要約指標に基づきます。"],
                },
            }
        }

    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_analysis",
        fake_master_analysis,
    )
    monkeypatch.setattr(
        "python.eval.ai_daily_report._call_openai_localization_analysis",
        fake_localization_analysis,
    )

    _, reports_by_language, budget = build_ai_daily_reports_multilingual(
        tmp_path,
        generated_at="2026-05-24T09:20:00+09:00",
        languages=("ko", "en", "ja"),
        openai_budget={"remaining": 3, "used": 0},
        openai_locales={"ko", "en", "ja"},
    )

    assert localization_calls == [["ko", "ja"], ["ko", "ja"]]
    assert budget == {"remaining": 0, "used": 3}
    assert reports_by_language["ko"][0]["contentLanguage"] == "ko"
    assert reports_by_language["ko"][0]["generator"]["localizationStatus"] == "ok"
    assert reports_by_language["ko"][0]["executiveSummary"]["headline"] == (
        "TEPCO 예측의 일간 오차가 모델보다 작았습니다."
    )
    assert reports_by_language["ja"][0]["contentLanguage"] == "ja"
    assert reports_by_language["ja"][0]["generator"]["localizationStatus"] == "ok"


def test_localized_analysis_rejects_cjk_corrupted_korean_payload():
    payload = {
        "executiveSummary": {
            "headline": "TEPCO陛 24偃曖 綠掖 陛棟フ 衛除 醞 16偃縑憮",
            "summary": "賅筐 濰薄 衛除擎 8衛除 絮薄瞳戲煎 TEPCO 濰薄 衛除擎 16薄戲煎",
        },
        "rootCauseHypotheses": [],
        "featureRecommendations": [],
    }

    with pytest.raises(ValueError, match="Korean localization"):
        _validate_localized_analysis("ko", payload)


def test_localized_analysis_rejects_cjk_corrupted_japanese_payload():
    payload = {
        "executiveSummary": {
            "headline": "TEPCO肢24肥楑昳呇窆羌蒢忺肥爬祀16蒢忺",
            "summary": "徉室恨肥跂屪蒢忺肢8蒢忺竺 TEPCO肥跂屪蒢忺肢16蒢忺竺",
        },
        "rootCauseHypotheses": [],
        "featureRecommendations": [],
    }

    with pytest.raises(ValueError, match="Japanese localization"):
        _validate_localized_analysis("ja", payload)


def test_ai_daily_report_index_points_to_latest(tmp_path):
    _write_operation_fixture(tmp_path, "2026-05-22")
    _write_operation_fixture(tmp_path, "2026-05-23")
    _write_json(tmp_path / "reports" / "daily" / "index.json", {
        "schemaVersion": "1.0.0",
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "reports": [
            {"date": "2026-05-22", "availability": "ok"},
            {"date": "2026-05-23", "availability": "ok"},
        ],
    })

    index, reports = build_ai_daily_reports(
        tmp_path,
        generated_at="2026-05-24T08:20:00+09:00",
        use_openai=False,
    )

    assert index["availability"] == "ok"
    assert index["latest"]["date"] == "2026-05-23"
    assert [report["date"] for report in reports] == ["2026-05-22", "2026-05-23"]
