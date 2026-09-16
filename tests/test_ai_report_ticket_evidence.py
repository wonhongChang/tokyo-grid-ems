import pytest

from python.eval.ai_daily_report import (
    _recommended_ticket_for_event,
    _ticket_recommendations_from_fact_packet,
)


@pytest.mark.parametrize("hour", [6, 12, 15, 17, 19])
def test_recalculation_gap_does_not_create_model_tuning_ticket(hour):
    event = {
        "id": f"freeze_gap_h{hour}",
        "hour": hour,
        "eventType": "published_recalculated_gap",
        "freezeGapMw": 863.7,
        "publishedForecastMw": 29455.1,
        "actualMw": 29460.0,
    }
    assert _recommended_ticket_for_event(event) is None
    event["id"] = "renamed-gap"
    assert _recommended_ticket_for_event(event) is None
    event.pop("eventType")
    event["id"] = f"freeze_gap_h{hour}"
    assert _recommended_ticket_for_event(event) is None


@pytest.mark.parametrize("hour", [6, 12, 17])
def test_real_demand_miss_with_supported_shape_remains_eligible(hour):
    ticket = _recommended_ticket_for_event({
        "id": f"top_miss_h{hour}", "hour": hour,
        "eventType": "large_absolute_error", "modelErrorDirection": "overprediction",
        "modelErrorMw": 1089.3,
    }, {"sameDayActualSlopeMw": -800, "postCalibrationForecastDeltaMw": 900})
    assert ticket is not None
    assert ticket["eventId"] == f"top_miss_h{hour}"


@pytest.mark.parametrize("language", ["en", "ko", "ja"])
def test_ticket_links_use_surviving_hypothesis_ids_and_reject_cached_gap(language):
    packet = {"recommendationTicketCandidates": [
        {"eventId": "top_miss_h6", "target": "intraday_correction.business_type_transition"},
        {"eventId": "freeze_gap_h17", "target": "intraday_correction.evening_decline_continuity_guard"},
        {"eventId": "dropped_event", "target": "lag_24h"},
    ]}
    hypotheses = [
        {"id": "analysis.morning", "sourceEventIds": ["top_miss_h6"],
         "relatedFeatures": ["lag_24h"]},
        {"id": "analysis.morning.detail", "sourceEventIds": ["top_miss_h6"],
         "relatedFeatures": ["lag_24h"]},
        {"id": "serving.published_forecast_freeze", "sourceEventIds": ["freeze_gap_h17"],
         "relatedFeatures": ["serving.published_forecast_freeze"]},
    ]
    result = _ticket_recommendations_from_fact_packet(language, packet, hypotheses)
    assert len(result) == 1
    assert result[0]["linkedHypotheses"] == ["analysis.morning", "analysis.morning.detail"]
    assert result[0]["autoApply"] is False
    assert "event.top_miss_h6" not in result[0]["linkedHypotheses"]
    assert _ticket_recommendations_from_fact_packet(language, packet, []) == []


def test_gap_only_hypothesis_cannot_authorize_a_model_ticket():
    result = _ticket_recommendations_from_fact_packet("en", {
        "recommendationTicketCandidates": [
            {"eventId": "renamed-gap", "target": "lag_24h"},
        ]}, [
        {"id": "serving.published_forecast_freeze", "sourceEventIds": ["renamed-gap"],
         "relatedFeatures": ["serving.published_forecast_freeze"]},
    ])
    assert result == []
