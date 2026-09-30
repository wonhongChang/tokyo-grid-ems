"""Portable synthetic recovery checks; no retained or private inputs required."""
import json
import math

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from python.eval.review_bundle import core
from tests.test_review_bundle_cli import REPO, build, inputs, invoke, put_input


def test_signed_metrics_preserve_cancellation_and_denominator():
    rows = [dict(actual=1000, forecast=1200), dict(actual=1000, forecast=900)]
    result = core.metrics(rows)
    assert result == dict(n=2, mae=150, rmse=round(math.sqrt(25000), 3),
                          wapePct=15, bias=50, maxAbsError=200)
    assert core.metrics([]) == dict(n=0, mae=None, rmse=None, wapePct=None,
                                    bias=None, maxAbsError=None)
    assert core.metrics([dict(actual=0, forecast=1)])["wapePct"] is None


def test_shape_preserves_order_and_does_not_bridge_gaps():
    rows = [dict(hour=8, actual=1000, forecast=1200),
            dict(hour=9, actual=1100, forecast=1000),
            dict(hour=11, actual=1200, forecast=1100)]
    result = core.shape(rows)
    assert result["signRuns"] == [[8, 8, 1], [9, 9, -1], [11, 11, -1]]
    assert result["transitions"] == [dict(fromHour=8, toHour=9, actualDelta=100,
                                         forecastDelta=-200, deltaError=-300,
                                         opposingSigns=True)]
    assert result["operationalImportance"] is None


def test_pairing_excludes_fallback_nonfinite_and_keeps_source_pointers():
    actual = dict(series=[
        dict(ts=f"2026-09-20T{h:02}:00:00+09:00", actualMw=value, actualSource=source)
        for h, value, source in [(0, 1000, "observed"), (1, 1100, "tepco_forecast_fallback"),
                                  (2, float("nan"), "observed")]])
    forecast = dict(series=[dict(ts=r["ts"], forecastMw=1200) for r in actual["series"]])
    rows, excluded = core.pair_actual_forecast(actual, forecast, "2026-09-20", "actual", "forecast")
    assert len(rows) == 1 and rows[0]["actualRef"] == dict(source="actual", pointer="/series/0")
    assert [r["code"] for r in excluded] == ["FALLBACK_NOT_OBSERVED", "MISSING_OR_INVALID_ACTUAL"]


@pytest.mark.parametrize("stamp,code", [("2026-09-21T00:00:00+09:00", "FILE_DATE_MISMATCH"),
                                      ("2026-09-20T00:00:00", "NAIVE_TIMESTAMP")])
def test_invalid_time_population_is_not_reinterpreted(stamp, code):
    with pytest.raises(core.EvidenceError, match=code):
        core.ts(stamp, "2026-09-20")


def test_all_stored_artifact_subtypes_validate(inputs):
    # Oversized recorded metadata exercises real chunking at the unchanged bound.
    key = "extra:metrics/model_promotion.json"
    inputs[2]["inputs"][key] = put_input(inputs[0], key, dict(status="champion_retained", reason="recorded " * 5000))
    (inputs[0] / "manifest.json").write_bytes(core.enc(inputs[2]))
    build(inputs)
    schema = json.loads((REPO / "python/eval/review_bundle/review-bundle.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    kinds = set()
    for path in (inputs[1] / "test").rglob("*.json"):
        obj = json.loads(path.read_bytes())
        if isinstance(obj, dict) and obj.get("schemaVersion") == core.VERSION:
            validator.validate(obj)
            kinds.add(obj["type"])
    assert {"review_bundle", "fact_section", "source_index", "date_index", "fact_index",
            "section_manifest", "chunk_manifest", "mandatory_notices"} <= kinds


def test_query_suite_never_writes_or_opens_unregistered_sources(inputs):
    seal = build(inputs)
    registered = {str((inputs[0] / e["path"]).resolve()) for e in inputs[2]["inputs"].values()}
    selection = ("--scope", "primary", "--date", "2026-09-20")
    commands = [("initial",), ("notices",), ("scopes",), ("metrics-inventory", *selection),
                ("direction-screen", *selection), ("stage-interval-review", *selection),
                ("hour-review", "--scope", "primary", "--date", "2026-09-20", "--hours", "0,12")]
    for args in commands:
        code, result, telemetry = invoke(inputs, *args, seal=seal)
        assert code == 0, result
        measure = telemetry["measurement"]
        assert not any(e["write"] for e in measure["opens"])
        assert not measure["denied"]
        assert {e["path"] for e in measure["reads"] if e["category"] == "source"} <= registered
