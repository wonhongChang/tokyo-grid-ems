"""Offline report contracts, independent of the presence of an LLM response."""
from copy import deepcopy
from inspect import signature

import pytest

from python.eval import experimental_luna_full_relations as rel
from tests.test_experimental_luna_report_scope import DAY, synthetic


def retained(files):
    files["operationalCalibration"] = {
        "date": DAY, "timezone": "Asia/Tokyo", "generatedAt": DAY + "T17:05:00+09:00",
        "hourlyDiagnostics": [{"hour": 0, "ts": DAY + "T00:00:00+09:00", "actualMw": 108.5,
                               "actualSource":"observed", "preCalibrationForecastMw": 4,
                               "postCalibrationForecastMw": 2, "forecastMwByStage": {"raw_lgbm": -3}}]}


def make(tmp, change=None):
    fb, pkt, src = synthetic(tmp, change)
    return rel.build(DAY, src, fb["inputSnapshot"]), fb, pkt, src


def test_not_a_prompt_projection(tmp_path):
    ledger, fb, pkt, src = make(tmp_path, retained)
    assert tuple(signature(rel.build).parameters) == ("day","sources","snapshot")
    before = deepcopy(ledger)
    for focus in ([], None, [{"ts":"wrong","forecastMw":100000}]):
        pkt["focusedRows"] = focus
        rel.optional_interpretations(pkt, {"observations":[]}, ledger)
        assert rel.build(DAY, src, fb["inputSnapshot"]) == before == ledger
    with pytest.raises(ValueError, match="unfingerprinted"):
        rel.build(DAY, {**src,"hidden":{}}, fb["inputSnapshot"])
    src["forecast"]["series"][0]["forecastMw"] += 1
    with pytest.raises(ValueError, match="identity"):
        rel.build(DAY, src, fb["inputSnapshot"])


def test_stage_identity_and_actual_basis(tmp_path):
    ledger, *_ = make(tmp_path, retained)
    r = ledger["relations"]
    s = r["stages/00:00"]["cells"]
    assert [s[k] for k in ("raw_lgbm","pre_calibration","post_calibration","actual","snapshotActual")] == [-3,4,2,1,108.5]
    assert [s[k] for k in ("rawError","preError","postError")] == [-4,3,1]
    assert s["analog_adjusted"] is None
    assert r["point/00:00"]["cells"]["closer"] == "tie"
    assert r["vintage/00:00"]["cells"]["basis"] == "post_calibration"
    assert ledger["issueTime"]["published"] is ledger["issueTime"]["tepco"] is None
    assert r["stages/01:00"]["status"] == "unavailable"
    assert r["vintage/01:00"]["cells"]["closer"] is None


@pytest.mark.parametrize("defect", ["duplicate","wrong_hour","wrong_day","naive_run","unknown_timezone","ambiguous"])
def test_unjoinable_cal_run_never_copies_a_neighbour(tmp_path,defect):
    def change(files):
        retained(files)
        c=files["operationalCalibration"]; row=c["hourlyDiagnostics"][0]
        if defect=="duplicate": c["hourlyDiagnostics"].append(row.copy())
        elif defect=="wrong_day": row["ts"]="2025-12-31T00:00:00+09:00"
        elif defect=="wrong_hour": row["hour"]=1
        elif defect=="naive_run": c["generatedAt"]=DAY+"T09:00:00"
        elif defect=="unknown_timezone": del c["timezone"]
        else: c["hourlyDiagnostics"].append(dict(row,hour=3))
    r=make(tmp_path,change)[0]["relations"]
    assert r["point/00:00"]["cells"]["actual"] == 1
    assert r["stages/00:00"]["status"] == r["vintage/00:00"]["status"] == "unavailable"
    assert r["stages/01:00"]["cells"]["post_calibration"] is None


def test_pre_only_is_named_not_substituted_for_post(tmp_path):
    def change(files):
        retained(files)
        row=files["operationalCalibration"]["hourlyDiagnostics"][0]
        del row["postCalibrationForecastMw"]
    r=make(tmp_path,change)[0]["relations"]
    assert r["stages/00:00"]["status"]=="partial"
    assert r["stages/00:00"]["cells"]["postError"] is None
    assert r["vintage/00:00"]["cells"]["basis"]=="pre_calibration"


def test_conflicting_retained_stages_fail_closed(tmp_path):
    def change(files):
        retained(files)
        files["operationalCalibration"]["hourlyDiagnostics"][0]["forecastMwByStage"]["post_calibration"]=22
    with pytest.raises(ValueError,match="conflicting retained stage"):
        make(tmp_path,change)


def test_paired_day_hour_identity(tmp_path):
    def change(files): files["forecast"]["series"][0]["hour"]=1
    ledger,*_=make(tmp_path,change)
    assert ledger["state"]=="invalid_hour_identity"
    assert set(ledger["relations"])=={"coverage/day"}


def test_partial_no_invented_transition_or_full_day_actions(tmp_path):
    def change(files): del files["forecast"]["series"][5]
    ledger,*_=make(tmp_path,change)
    assert ledger["state"]=="partial"
    assert "point/05:00" not in ledger["relations"] and "point/06:00" in ledger["relations"]
    assert not any(k.startswith(("check/","experiment/","daily/")) for k in ledger["relations"])
    assert not any("05:00" in k for k in ledger["relations"] if k.startswith("change/"))
    assert all(r["cells"]["population"]=="partial" for r in ledger["relations"].values() if r["kind"]=="peak")


def test_hour_winner_and_band_winner_can_differ_even_on_quiet_day(tmp_path):
    def change(files):
        for h,(a,f) in enumerate(zip(files["actual"]["series"],files["forecast"]["series"])):
            a.update(actualMw=1000,tepcoForecastMw=1001 if h==9 else 1020)
            f.update(forecastMw=1010 if h==9 else 1001)
    r=make(tmp_path,change)[0]["relations"]
    assert r["point/09:00"]["cells"]["closer"]=="tepco"
    assert r["band/06-10"]["cells"]["lowerMAE"]=="published"
    assert r["peak/00:00"]["cells"]["timing"] is None
    assert not any(k.startswith("experiment/") for k in r)
