"""Candidate-only, offline screen contracts; no application imports the new renderer."""
from copy import deepcopy
import pytest

from python.eval.luna_brief import candidate as c, display
from python.eval.luna_brief.__main__ import packet
from tests.test_experimental_luna_report_scope import DAY, synthetic


@pytest.mark.parametrize("lang",display.LANG)
def test_two_peak_definitions_and_rule(lang,tmp_path):
    archive,_,_=synthetic(tmp_path)
    b=c.build(tmp_path,DAY,archive)
    assert b["peaks"]["23:00"]["maxDifference"]==6
    assert b["peaks"]["23:00"]["error"]==-17
    first=display.render(b,lang).split("</section>",1)[0]
    assert "+6.0 MW" in first and "-17.0 MW" in first
    assert b["daily"]["verdict"]==archive["performance"]["verdict"]


@pytest.mark.parametrize("flag,state",[("partial","partial"),("provisional","unconfirmed"),("duplicate","invalid_hour_identity")])
def test_no_daily_claim_on_incomplete_population(tmp_path,flag,state):
    def modify(f):
        if flag=="partial":f["forecast"]["series"].pop()
        if flag=="provisional":f["actual"]["series"][0]["finalized"]=False
        if flag=="duplicate":f["actual"]["series"].append(deepcopy(f["actual"]["series"][0]))
    archive,_,_=synthetic(tmp_path,modify)
    b=c.build(tmp_path,DAY,archive)
    assert b["state"]==state and not b["daily"] and b["action"]=="coverage"
    for lang in display.LANG:
        html=display.render(b,lang)
        assert 'id="daily"' not in html and 'id="research"' not in html


def test_peak_ties_and_interval_denominators(tmp_path):
    def modify(f):
        f["actual"]["series"][0]["actualMw"]=24
        f["forecast"]["series"][2]["forecastMw"]=30
        del f["forecast"]["series"][3]["p95LowerMw"]
    archive,_,_=synthetic(tmp_path,modify)
    b=c.build(tmp_path,DAY,archive)
    assert list(b["peaks"])==["00:00","23:00"]
    assert all(v["timing"] is None and v["publishedHours"]==["00:00","02:00"] for v in b["peaks"].values())
    assert b["intervals"]["95"]["n"]==23 and b["intervals"]["99"]["inside"] is None
    assert b["action"]=="band_data"


def test_unsafe_claims_and_wrong_response_identity_do_not_render(tmp_path):
    archive,_,_=synthetic(tmp_path)
    b=c.build(tmp_path,DAY,archive,[{"claim":"published_closer","relation":"point/00:00"},
        {"claim":"opposite_directions","relation":"change/incorrect"}])
    assert not b["optional"] and all(r["kind"]!="experiment" for r in b["rows"].values())
    assert packet(tmp_path,DAY,archive,{"date":"wrong","response":{"observations":[]}})==b
    archive["performance"]["verdict"]="tampered"
    with pytest.raises(ValueError,match="mismatch"):c.build(tmp_path,DAY,archive)


def test_no_escape_to_non_json_input(tmp_path):
    with pytest.raises(ValueError):c.read_public(tmp_path,"../off-root.json")
    with pytest.raises(ValueError):c.read_public(tmp_path,".env")


def test_optional_revision_check_not_contradictory(tmp_path):
    from tests.test_experimental_luna_full_relations import retained
    def modify(files):
        retained(files)
        row=files["operationalCalibration"]["hourlyDiagnostics"][0]
        row["postCalibrationForecastMw"]=9000
    archive,_,_=synthetic(tmp_path,modify);b=c.build(tmp_path,DAY,archive)
    assert b["action"]=="none" and b["revisionTargets"]==["00:00"]
    for lang,phrase in zip(display.LANG,("only if investigating revisions","발행 이력을 조사할 때만","改定を調査する場合に限り")):
        first=display.render(b,lang).split("</section>",1)[0]
        assert phrase in first


def test_interval_exception_has_comparable_bounds_and_direction(tmp_path):
    def modify(files):files["forecast"]["series"][0].update(p95LowerMw=2,p95UpperMw=4)
    archive,_,_=synthetic(tmp_path,modify);b=c.build(tmp_path,DAY,archive)
    assert b["action"]=="bounds"
    assert b["intervals"]["95"]["exceptions"]==[dict(target="00:00",actual=1,lower=2,upper=4,side="below")]
    assert "하한 미만" in display.render(b,"ko")
