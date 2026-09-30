"""Presentation-only refinement: source, population and adverse evidence parity."""
import json

import pytest
from jsonschema import Draft202012Validator

from python.eval.review_bundle import batch, core
from tests.test_review_bundle_batch import add_stage, expand
from tests.test_review_bundle_cli import REPO, build, inputs, invoke, put_input


OPTIONS = ("--scope", "primary", "--date", "2026-09-20")


def view(inputs, seal, command, *args):
    code, result, _ = invoke(inputs, command, *args, seal=seal)
    assert code == 0, result
    return result["value"]


def test_compact_provenance_expands_exactly(inputs):
    add_stage(inputs)
    seal = build(inputs)
    compact = view(inputs, seal, "review-summary", *OPTIONS)
    full = view(inputs, seal, "review-summary", *OPTIONS, "--expand-provenance")
    for k, section in compact["dates"][0]["sections"].items():
        old = full["dates"][0]["sections"][k]
        descriptor = compact["registry"]["provenance"][section["provenanceRef"]]
        refs = full["registry"]["provenance"][old["provenanceRef"]]
        if descriptor["deferred"]:
            assert descriptor["referenceListSha256"] == core.sha(core.enc(refs))
            assert descriptor["locatorCount"] == len(refs)
            assert descriptor["compatibleBasesAssumed"] is False
            assert descriptor["sealedFactRef"]["fileRef"] in compact["registry"]["files"]
        else:
            assert descriptor["sources"] == refs
        assert descriptor["sourceCount"] == len({r["source"] for r in refs})
        assert section["state"] == old["state"]
        assert section["population"] == old["population"]
        assert section["value"] == old["value"]
        expanded = view(inputs, seal, "provenance", "--fact-id", descriptor.get("factId", section["factId"]))
        assert [{k: r[k] for k in original} for r, original in zip(expanded["sources"], refs)] == refs
        assert len(expanded["sources"]) == len(refs)


@pytest.mark.parametrize("date", ["2026-09-20", "2026-09-19"])
def test_multi_hour_independent_equivalence_and_unavailable(inputs, date):
    add_stage(inputs)
    seal = build(inputs)
    opts = ("--scope", "primary", "--date", date)
    multi = view(inputs, seal, "hour-review", *opts, "--hours", "0,1,23", "--expand-provenance")
    assert multi["dates"][0]["sections"] == {}
    assert [t["hour"] for t in multi["dates"][0]["targets"]] == [0, 1, 23]
    for target in multi["dates"][0]["targets"]:
        one = view(inputs, seal, "hour-review", *opts, "--hour", str(target["hour"]), "--expand-provenance")
        assert target["target"] == one["target"]
        for k, section in target["sections"].items():
            old = one["dates"][0]["sections"][k]
            assert expand(multi, section) == expand(one, old)
            assert section["selection"] == old["selection"]
            assert section["runContext"] == old["runContext"]
            if target["hour"] == 23:
                assert section["selection"]["state"]["status"] == "unavailable"
    compact = view(inputs, seal, "hour-review", *opts, "--hours", "0,1,23")
    for a, b in zip(compact["dates"][0]["targets"], multi["dates"][0]["targets"]):
        for k, section in a["sections"].items():
            desc = compact["registry"]["provenance"][section["provenanceRef"]]
            full = multi["registry"]["provenance"][b["sections"][k]["provenanceRef"]]
            if desc["deferred"]:
                assert desc["referenceListSha256"] == core.sha(core.enc(full))
            else:
                assert desc["sources"] == full


def test_membership_unknown_negative_and_positive_not_interchangeable():
    rows = [dict(hour=h, basis=b, leadMinutes=lead, retrospective=retro, intervalAvailable=interval)
            for h, b, lead, retro, interval in [(0, "advance", -30, True, True),
                (1, "advance", 0, True, True), (2, "advance", None, False, True),
                (3, "advance", 30, False, True), (4, "stage", 45, False, True),
                (5, "advance", 180, False, True), (6, "advance", 60, False, False)]]
    v = batch.membership_counts(rows, list(range(8)))
    assert v["rowsByBasis"] == {"advance": 6, "stage": 1}
    assert (v["positiveLeadRows"], v["nonpositiveLeadRows"], v["unknownLeadRows"], v["retrospectiveRows"]) == (4, 2, 1, 2)
    assert v["positiveLeadAdvanceHours"] == [3, 5, 6]
    assert v["missingPositiveLeadAdvanceHours"] == [0, 1, 2, 4, 7]
    assert v["eligibleRetainedIntervalHours"] == [3, 4]
    assert v["absenceIsNotGlobalNonexistence"] is True


def test_membership_cli_matches_index_and_selected_population(inputs):
    add_stage(inputs)
    seal = build(inputs)
    result = view(inputs, seal, "membership-summary", *OPTIONS, "--hours", "0,23")
    s = result["dates"][0]["sections"]["membership"]
    index = view(inputs, seal, "indexes", *OPTIONS)
    # Membership is an index question, never a forecast-metric population.
    assert s["population"] is None and s["sampleCount"] is None
    assert s["value"]["totalRows"] == len(index["items"])
    assert s["value"]["missingPositiveLeadAdvanceHours"] == [0, 23]
    assert s["value"]["selectedIntervalHours"]["value"] == []
    missing = view(inputs, seal, "membership-summary", "--scope", "primary", "--date", "2026-09-19")
    s = missing["dates"][0]["sections"]["membership"]
    assert s["value"] is None and s["state"]["status"] == "unavailable"


def test_compact_stage_keeps_strongest_adverse_and_all_adverse_path(inputs):
    root, _, manifest = inputs
    day = "2026-09-20"
    for kind, field, value in [("actual", "actualMw", 1000), ("forecast", "forecastMw", 1100)]:
        key = f"20:{kind}/{day}.json"
        manifest["inputs"][key] = put_input(root, key, {"series": [
            {"ts": f"{day}T{h:02}:00:00+09:00", field: value} for h in range(3)]})
    for h, post in enumerate([1050, 1400, 1200]):
        key = f"20:reports/internal/operational-calibration/snapshots/{day}/h{h}.json"
        at = "2026-09-19T23:30:00+09:00" if h == 0 else f"{day}T{h-1:02}:30:00+09:00"
        manifest["inputs"][key] = put_input(root, key, {"generatedAt": at, "correction": {}, "hourlyDiagnostics": [
            {"ts": f"{day}T{h:02}:00:00+09:00", "forecastMwByStage": {"raw_lgbm": 1100, "pre_calibration": 1100}, "postCalibrationForecastMw": post}]})
    (root / "manifest.json").write_bytes(core.enc(manifest))
    seal = build(inputs)
    compact = view(inputs, seal, "stage-interval-review", *OPTIONS)
    full = view(inputs, seal, "stage-interval-review", *OPTIONS, "--expand-details")
    s = compact["dates"][0]["sections"]["stages"]
    old = full["dates"][0]["sections"]["stages"]
    assert s["value"]["raw"] == old["value"]["raw"]
    assert s["value"]["post"] == old["value"]["post"]
    assert s["hourCounts"] == {"improvedHours": 1, "worsenedHours": 2}
    assert s["extremes"]["value"]["strongestWorsening"]["hour"] == 1
    assert s["extremes"]["value"]["strongestWorsening"]["absErrorDelta"] == 300
    assert s["extremes"]["value"]["strongestImprovement"]["absErrorDelta"] == -50
    q = s["evidenceQueries"]["allAdverseHours"]
    adverse = view(inputs, seal, q["command"], "--fact-id", q["factId"], "--pointer", q["pointer"])
    assert adverse["items"] == old["value"]["worsenedHours"] == [1, 2]
    assert s["rowIdentityCohorts"] == old["rowIdentityCohorts"]


def test_initial_references_and_all_new_view_schemas(inputs):
    seal = build(inputs)
    initial = view(inputs, seal, "initial")
    overview = initial["reviewOverview"]
    for date in overview["dates"]:
        for s in date["sections"].values():
            q = s["fullFactQuery"]
            f = view(inputs, seal, q["command"], "--fact-id", q["factId"])
            assert f["state"] == s["state"]
            assert f["population"]["id"] == s["population"]["id"]
    validator = Draft202012Validator
    schema = json.loads((REPO / "python/eval/review_bundle/review-view.schema.json").read_bytes())
    validator.check_schema(schema)
    validator(schema).validate(overview)
    for command, opts in [("hour-review", ("--hours", "0,1,23")), ("membership-summary", ("--hour", "0")), ("stage-interval-review", ())]:
        v = view(inputs, seal, command, *OPTIONS, *opts)
        validator(schema).validate(v)
        assert core.enc(v) == core.enc(view(inputs, seal, command, *OPTIONS, *opts))


@pytest.mark.parametrize("args", [("--hours", "0,0"), ("--hours", "24"), ("--hours", "../.env"), ("--hour", "0", "--hours", "1")])
def test_invalid_multihour_selection(inputs, args):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "hour-review", *OPTIONS, *args, seal=seal)
    assert code == 2 and result["state"]["status"] == "unavailable"
