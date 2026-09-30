"""Read-only presentation contracts, independent of model logic or services."""
import json

import pytest
from jsonschema import Draft202012Validator

from python.eval.review_bundle import batch, core
from tests.test_review_bundle_cli import REPO, build, inputs, invoke, put_input


def expand(view, section):
    pop = dict(section["population"]) if section["population"] else None
    if pop is not None:
        pop["identity"] = view["registry"]["identities"].get(pop.pop("identityRef"))
    return dict(value=section["value"], population=pop, state=section["state"],
                provenance=view["registry"]["provenance"].get(section["provenanceRef"]),
                detailRef=view["registry"]["details"].get(section["detailRef"]))


def test_summary_equals_individual_facts(inputs):
    seal = build(inputs)
    code, result, telemetry = invoke(inputs, "review-summary", "--scope", "primary", "--date", "2026-09-20", "--expand-provenance", seal=seal)
    assert code == 0, result
    v = result["value"]
    sections = v["dates"][0]["sections"]
    assert set(sections) == set(batch.GROUPS["review-summary"])
    for kind, section in sections.items():
        _, individual, _ = invoke(inputs, "fact", "--fact-id", section["factId"], seal=seal)
        expected = {k: individual["value"][k] for k in ("value", "population", "state", "provenance", "detailRef")}
        assert expand(v, section) == expected
    assert sections["metrics"]["population"]["id"] != sections["stages"]["population"]["id"]
    assert len(telemetry["measurement"]["reads"]) == len({r["path"] for r in telemetry["measurement"]["reads"]})
    assert telemetry["measurement"]["rawSourceBytes"] == 0


def test_unavailable_hour_no_retrospective_substitution(inputs):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "hour-review", "--scope", "primary", "--date", "2026-09-20", "--hour", "0", seal=seal)
    assert code == 0
    ss = result["value"]["dates"][0]["sections"]
    assert ss["metrics"]["value"][0]["forecast"] == 1100
    for k in ("advance", "stages", "interval"):
        assert ss[k]["value"] == [] and ss[k]["selection"]["state"]["status"] == "unavailable"
    assert ss["stages"]["state"]["code"] == "NO_USABLE_ADVANCE_STAGE"


def test_paths_no_guess_and_readonly(inputs):
    seal = build(inputs)
    before = {p: p.read_bytes() for root in inputs[:2] for p in root.rglob("*") if p.is_file()}
    _, result, _ = invoke(inputs, "paths", "--fact-id", "primary:2026-09-20:metrics", seal=seal)
    assert "/rows" in [r["pointer"] for r in result["value"]["validDetailChildren"]]
    code, result, _ = invoke(inputs, "resolve", "--kind", "detail", "--fact-id", "primary:2026-09-20:metrics", "--pointer", "/published", seal=seal)
    assert code == 2 and result["state"]["code"] == "MISSING_POINTER"
    for command in ("initial", "direction-screen", "stage-interval-review", "metrics-inventory"):
        args = [] if command == "initial" else ["--scope", "primary", "--dates", "2026-09-20"]
        code, result, telemetry = invoke(inputs, command, *args, seal=seal)
        assert code == 0, result
        assert not any(e["write"] for e in telemetry["measurement"]["opens"])
    assert all(p.read_bytes() == b for p, b in before.items())


def test_explicit_dates_paging_and_unknown_date(inputs):
    seal = build(inputs)
    _, result, _ = invoke(inputs, "metrics-inventory", "--scope", "primary", "--dates", "2026-09-19,2026-09-20", "--limit", "1", seal=seal)
    assert result["value"]["paging"]["nextOffset"] == 1
    assert result["value"]["dates"][0]["sections"]["metrics"]["state"]["code"] == "FACT_NOT_REGISTERED"
    _, second, _ = invoke(inputs, "metrics-inventory", "--scope", "primary", "--dates", "2026-09-19,2026-09-20", "--limit", "1", "--offset", "1", seal=seal)
    assert second["value"]["dates"][0]["sections"]["metrics"]["value"]["n"] == 1
    assert second["value"]["paging"]["nextOffset"] is None


@pytest.mark.parametrize("opts", [[], ["--date", "../../.env"], ["--dates", "2026-09-20,2026-09-20"], ["--from", "2026-09-21", "--to", "2026-09-20"]])
def test_invalid_selection(inputs, opts):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "metrics-inventory", "--scope", "primary", *opts, seal=seal)
    assert code == 2 and result["state"]["status"] == "unavailable"


def test_initial_overview_budget_notice_and_unknown_identity(inputs):
    seal = build(inputs)
    _, result, measure = invoke(inputs, "initial", seal=seal)
    view = result["value"]["reviewOverview"]
    assert measure["measurement"]["returnedBytes"] <= core.TARGET
    assert view["mandatoryNotices"]["count"] > 0
    metrics = view["dates"][0]["sections"]["metrics"]
    assert view["registry"]["identities"][metrics["population"]["identityRef"]]["artifact"] is None
    assert metrics["value"]["mae"] == 100


def add_stage(inputs, cutoff=True):
    root, _, manifest = inputs
    d = "2026-09-20"
    key = f"20:reports/internal/operational-calibration/snapshots/{d}/capture.json"
    value = {"generatedAt": "2026-09-19T23:30:00+09:00", "correction": {"lastObservedHour": 22} if cutoff else {},
             "hourlyDiagnostics": [{"ts": d + "T00:00:00+09:00", "forecastMwByStage": {"raw_lgbm": 1100, "pre_calibration": 1100}, "postCalibrationForecastMw": 1050}]}
    manifest["inputs"][key] = put_input(root, key, value)
    (root / "manifest.json").write_bytes(core.enc(manifest))
    return root / manifest["inputs"][key]["path"]


@pytest.mark.parametrize("mode", ["recorded", "missing_field", "changed_source", "missing_source"])
def test_hour_cutoff_hash_and_null_identity(inputs, mode):
    source = add_stage(inputs, cutoff=mode != "missing_field")
    seal = build(inputs)
    if mode == "changed_source":
        source.write_bytes(b"{}")
    if mode == "missing_source":
        source.unlink()
    code, r, m = invoke(inputs, "hour-review", "--scope", "primary", "--date", "2026-09-20", "--hour", "0", seal=seal)
    assert code == 0, r
    v = r["value"]
    section = v["dates"][0]["sections"]["stages"]
    row = section["value"][0]
    assert row["sourceIdentity"] == {"artifact": None, "policy": None}
    cutoff = row["observationCutoff"]
    if mode == "recorded":
        assert cutoff["value"] == 22 and cutoff["state"]["status"] == "available"
        assert m["measurement"]["rawSourceBytes"] > 0
    else:
        assert cutoff["value"] is None
        assert cutoff["state"]["code"] == {"missing_field": "MISSING_POINTER", "changed_source": "SOURCE_HASH_MISMATCH", "missing_source": "RETENTION_LOSS"}[mode]
    assert v["target"]["alternativeRunCount"] == 0
    assert section["parentProvenanceQuery"]["factId"] == section["factId"]
    assert section["provenanceScope"] == "selected_target_rows_only"
    assert section["runContext"][0]["matches"][0]["run"]["artifact"] is None


def test_identity_cohorts_dont_fill_unknown_or_collapse():
    rows = [{"hour": 1, "sourceIdentity": {"artifact": None, "policy": "old"}},
            {"hour": 2, "sourceIdentity": {"artifact": None, "policy": "new"}},
            {"hour": 3, "sourceIdentity": {"artifact": None, "policy": None}}]
    groups = batch.identity_cohorts(rows)
    assert len(groups) == 3
    assert groups[-1]["identity"]["policy"] is None


def test_missing_date_input_error_not_zero(inputs):
    root, _, manifest = inputs
    key = "20:actual/2026-09-20.json"
    manifest["inputs"][key] = put_input(root, key, {"series": [
        {"ts": "2026-09-19T00:00:00+09:00", "actualMw": 1000}]})
    (root / "manifest.json").write_bytes(core.enc(manifest))
    seal = build(inputs)
    code, result, _ = invoke(inputs, "review-summary", "--scope", "primary", "--date", "2026-09-20", seal=seal)
    assert code == 0
    for section in result["value"]["dates"][0]["sections"].values():
        assert section["state"]["code"] == "FILE_DATE_MISMATCH"
        assert section["value"] is None and section["population"] is None


def test_initial_large_notice_summary_keeps_references(inputs):
    build(inputs)
    bundle = inputs[1] / "test"
    root = json.loads((bundle / "review_bundle.json").read_bytes())
    root["mandatoryNotices"]["codes"]["oversized_test"] = "x" * 40000
    raw = core.enc(root)
    (bundle / "review_bundle.json").write_bytes(raw)
    seal = json.loads((bundle / "access.json").read_bytes())
    seal["files"]["review_bundle.json"] = {"sha256": core.sha(raw), "bytes": len(raw)}
    (bundle / "access.json").write_bytes(core.enc(seal))
    code, result, measurement = invoke(inputs, "initial", seal=core.sha(core.enc(seal)))
    assert code == 0 and measurement["measurement"]["returnedBytes"] <= core.TARGET
    assert result["value"]["reviewOverview"]["overflow"] is True
    assert result["value"]["mandatoryNotices"]["ref"] == root["mandatoryNotices"]["ref"]
    assert result["value"]["mandatoryNotices"]["count"] == root["mandatoryNotices"]["count"]


def test_batch_query_determinism(inputs):
    seal = build(inputs)
    args = ("--scope", "primary", "--date", "2026-09-20")
    first = invoke(inputs, "review-summary", *args, seal=seal)[1]
    second = invoke(inputs, "review-summary", *args, seal=seal)[1]
    assert core.enc(first) == core.enc(second)


def test_adverse_candidate_outside_overview_and_incompatible_schema(inputs):
    root, _, manifest = inputs
    manifest["scopes"].append(dict(id="candidate", role="candidate_validation", captureKey="candidate",
                                   revision=None, asOf=None, capturedAt=None, finalizedThrough=None,
                                   expectedIdentity={"candidateArtifactSha256": "expected"}))
    key = "candidate:lift_replay.json"
    data = dict(candidateArtifactSha256="different", gates=[{"name": "kept_failure", "passed": False}], rows=[
        dict(day="2026-09-19", hour=12, at="2026-09-19T12:30:00+09:00", lead=-30, actual=1000, baseline=1000, candidate=1200),
        dict(day="2026-09-19", hour=13, at="2026-09-19T12:30:00+09:00", lead=30, actual=1000, baseline=1000, candidate=1100)])
    manifest["inputs"][key] = put_input(root, key, data)
    (root / "manifest.json").write_bytes(core.enc(manifest))
    seal = build(inputs)
    code, result, _ = invoke(inputs, "initial", seal=seal)
    assert code == 0
    v = result["value"]["reviewOverview"]
    s = v["scopeSections"]["candidate:scope:candidate_validation"]
    assert s["state"]["status"] == "incompatible"
    assert s["value"]["degradedPairCount"] == 2
    assert s["value"]["failedGates"] == data["gates"]
    assert "holdout" in s["value"]["missingFields"]
    _, detail, _ = invoke(inputs, "resolve", "--kind", "detail", "--fact-id", s["factId"], "--pointer", "/degradedPairs", seal=seal)
    assert [r["lead"] for r in detail["value"]["items"]] == [-30, 30]
    validator = Draft202012Validator
    schema = json.loads((REPO / "python/eval/review_bundle/review-view.schema.json").read_bytes())
    validator.check_schema(schema)
    validator(schema).validate(v)
