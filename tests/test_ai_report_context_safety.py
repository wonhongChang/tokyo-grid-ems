"""Do not manufacture operational causes from the target hour."""
import re

import pytest

from python.eval.ai_daily_report import (
    _event_hypotheses_from_fact_packet,
    _event_hypothesis_copy_override,
    _recommended_ticket_for_event,
    _recommendation_copy_override,
)


def test_morning_ticket_does_not_presume_business_transition():
    ticket = _recommended_ticket_for_event({
        "id": "top_miss_h8", "hour": 8,
        "eventType": "large_absolute_error", "modelErrorMw": -1814.2,
    })
    assert ticket["target"] == "lag_24h_hourly_delta"
    assert "proposedReplayCommand" not in ticket


@pytest.mark.parametrize("hour", [8, 12, 17])
def test_report_regeneration_is_never_offered_as_model_replay(hour):
    ticket = _recommended_ticket_for_event(
        {"id": f"top_miss_h{hour}", "hour": hour, "modelErrorMw": 1200},
        {"sameDayActualSlopeMw": -800, "postCalibrationForecastDeltaMw": 900},
    )
    assert "proposedReplayCommand" not in ticket


@pytest.mark.parametrize("error,slope,delta", [
    (2336.7, -240, 100),  # September 15: an error does not prove a sharp decline.
    (1633.5, -50, 100),
    (-1200, -800, 900),
    (1200, -800, -100),
    (1200, None, 900),
    (1200, -800, None),
])
def test_evening_cap_candidate_requires_signed_shape_evidence(error, slope, delta):
    assert _recommended_ticket_for_event(
        {"id": "top_miss_h17", "hour": 17, "modelErrorMw": error},
        {"sameDayActualSlopeMw": slope, "postCalibrationForecastDeltaMw": delta},
    ) is None


def test_supported_evening_shape_still_has_a_review_candidate():
    ticket = _recommended_ticket_for_event(
        {"id": "top_miss_h17", "hour": 17, "modelErrorMw": 1500},
        {"sameDayActualSlopeMw": -800, "postCalibrationForecastDeltaMw": 900},
    )
    assert ticket["target"] == "intraday_correction.evening_decline_continuity_guard"


@pytest.mark.parametrize("language,pattern", [("ko", "[가-힣]"), ("ja", "[ぁ-んァ-ン]")])
def test_repaired_event_and_ticket_details_keep_report_language(language, pattern):
    packet = {"eventEvidenceBundles": [{
        "eventId": "top_miss_h8", "hour": 8, "timeBand": "morning_ramp",
        "focusedEvidence": {"modelErrorMw": -1814.2, "publishedForecastMw": 32265.8, "actualMw": 34080},
        "morningEvidence": {"lag24BusinessTypeMismatch": 0},
    }]}
    hypothesis = _event_hypotheses_from_fact_packet(language, packet)[0]
    assert "intraday_correction.business_type_transition" not in hypothesis["relatedFeatures"]
    assert any(e["metric"] == "lag24BusinessTypeMismatch" and e["value"] == 0 for e in hypothesis["evidence"])
    for key in ["title", "explanation", "mechanism", "nextCheck"]:
        assert re.search(pattern, hypothesis[key])
    copy = _recommendation_copy_override(language, "intraday_correction.evening_decline_continuity_guard")
    for key in ["suggestion", "expectedEffect", "risk", "validationPlan"]:
        assert re.search(pattern, copy[key])


@pytest.mark.parametrize("mismatch", [None, 0, 1])
@pytest.mark.parametrize("language", ["en", "ko", "ja"])
def test_transition_copy_needs_explicit_mismatch_evidence(mismatch, language):
    hypothesis = {
        "relatedFeatures": ["intraday_correction.business_type_transition"],
        "evidence": [{"source": "eventEvidenceBundles", "metric": "modelErrorMw", "value": -1500, "hour": 8}],
    }
    if mismatch is not None:
        hypothesis["evidence"].append({"source": "eventEvidenceBundles", "metric": "lag24BusinessTypeMismatch", "value": mismatch, "hour": 8})
    result = _event_hypothesis_copy_override(language, hypothesis)
    assert (result is not None) == (mismatch == 1)
