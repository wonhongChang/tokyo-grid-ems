"""The optional point is never used as a replacement for a Champion series."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from python.forecast import hourly_next as h
from scripts import hourly_delivery as delivery


DAY = "2026-11-28"
ISSUE = h.moment(DAY + "T07:31:50+09:00")
SHA = "f" * 40


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


def inputs():
    hours = [f"{DAY}T{x:02}:00:00+09:00" for x in range(24)]
    points = [dict(ts=t, forecastMw=30100, p95LowerMw=29000, p95UpperMw=31000,
                   p99LowerMw=28000, p99UpperMw=32000) for t in hours]
    stages = dict(raw_lgbm=30010, pre_calibration=30020)
    obs = [dict(ts=t, actualSource="observed", actualMw=30000+i*10) for i,t in enumerate(hours[:7])]
    model = dict(artifactSha256=h.NATIVE)
    native = dict(date=DAY, availability="ok", series=points, model=model, servingPolicyFingerprint=h.POLICY)
    actual = dict(date=DAY, availability="ok", series=obs)
    snap = dict(generatedAt=ISSUE.isoformat(), runType="intraday", targetDate=DAY, model=model,
                servingPolicyFingerprint=h.POLICY, observationSummary=dict(lastObservedActualHour=6),
                forecastBuild=dict(series=[dict(forecastMwByStage=stages) for t in hours]), series=deepcopy(points))
    cal = dict(date=DAY, generatedAt=(ISSUE-timedelta(seconds=6)).isoformat(),
               hourlyDiagnostics=[dict(ts=t, forecastMwByStage=stages, preCalibrationForecastMw=30020,
                                      postCalibrationForecastMw=30100, **{k:v for k,v in (obs[i] if i<7 else {}).items() if k!="ts"})
                                  for i,t in enumerate(hours)])
    return native, actual, snap, cal


@pytest.fixture(scope="module")
def model():
    return h.load_model()


def test_issue_is_a_frozen_sidecar(tmp_path, model):
    inp = inputs()
    before = h.digest(inp)
    clock = lambda: ISSUE + timedelta(seconds=2)
    p = h.seal(tmp_path, *inp, clock=clock, model=model)
    contents = p.read_bytes()
    r = json.loads(contents)["record"]
    assert h.digest(inp) == before
    assert r["issuedAt"] == clock().isoformat() and h.moment(r["targetStart"]).hour == 8
    assert r["championMw"] == 30100 and r["forecastMw"] != 30100
    assert abs(r["bands"]["p95UpperMw"]-r["bands"]["p95LowerMw"]-2000)<1e-8
    assert h.seal(tmp_path, *inp, clock=lambda: clock()+timedelta(seconds=7), model=model) == p
    assert h.seal(tmp_path, *inp, clock=lambda: h.moment(r["targetStart"]), model=model) is None
    assert p.read_bytes() == contents
    bad=json.loads(contents)
    bad["record"]["championMw"] += 1
    write(p,bad)
    with pytest.raises(ValueError,match="immutable"):
        h.seal(tmp_path, *inp, clock=clock, model=model)


@pytest.mark.parametrize("mismatch", ["D-1","preview","fallback","identity","stage","stale","future"])
def test_invalid_inputs_do_not_issue(mismatch, tmp_path, model):
    n,a,s,c=inputs()
    if mismatch=="D-1": s["targetDate"]="2026-11-29"
    if mismatch=="preview": s["runType"]="preview"
    if mismatch=="fallback": a["series"][-1]["actualSource"]="tepco_forecast_fallback"
    if mismatch=="identity": n["servingPolicyFingerprint"]="changed"
    if mismatch=="stage": c["hourlyDiagnostics"][8]["postCalibrationForecastMw"]=30000
    if mismatch=="stale": c["generatedAt"]=(ISSUE-timedelta(minutes=10)).isoformat()
    if mismatch=="future": s["generatedAt"]=(ISSUE+timedelta(minutes=5)).isoformat()
    assert h.seal(tmp_path,n,a,s,c,clock=lambda:ISSUE,model=model) is None
    assert not list(tmp_path.iterdir())


def test_local_and_hosted_compare_only_confirmed_pairs(tmp_path, model):
    n,a,s,c=inputs()
    for sub,obj in (("forecast",n),("actual",a),("reports/internal/operational-calibration",c)):
        write(tmp_path/sub/(DAY+".json"),obj)
    write(tmp_path/"status.json",dict(today=dict(date=DAY)))
    record=h.seal(tmp_path,n,a,s,c,clock=lambda:ISSUE,model=model)
    record_bytes=record.read_bytes()
    def run(t, live=None):
        proofs=delivery.project(tmp_path,SHA,live,clock=lambda:t)
        rows=json.loads((tmp_path/"status.json").read_bytes())["hourlyNext"]["rows"]
        assert len(rows)==1
        return proofs,rows[0]
    turn=h.moment(DAY+"T08:00:00+09:00")
    assert run(turn)[1]["confirmedAt"] is None
    write(tmp_path/"forecast"/(DAY+".json"),dict(n,other=True))
    assert run(ISSUE)[1]["confirmedAt"] is None
    write(tmp_path/"forecast"/(DAY+".json"),n)
    proofs,row=run(ISSUE+timedelta(minutes=1))
    assert len(proofs)==1 and row["actualMw"] is None
    delivery.remember(tmp_path,dict(hourlyProofs=proofs))
    y=dict(ts=turn.isoformat(),actualSource="tepco_forecast_fallback",actualMw=30500)
    write(tmp_path/"actual"/(DAY+".json"),dict(a,series=[y]))
    ended=turn+timedelta(hours=1)
    assert run(ended)[1]["actualMw"] is None
    y["actualSource"]="observed"
    write(tmp_path/"actual"/(DAY+".json"),dict(a,series=[y]))
    assert run(ended-timedelta(seconds=1))[1]["actualMw"] is None
    assert run(ended)[1]["actualMw"] == 30500 and not run(ended)[1]["finalized"]
    del y["actualSource"]
    write(tmp_path/"actual"/(DAY+".json"),dict(a,series=[y]))
    write(tmp_path/".etl_state.json",dict(okDates=[DAY]))
    _,final=run(ended)
    assert final["finalized"] and final["actualMw"]==30500 and final["championMw"]==n["series"][8]["forecastMw"]
    assert record.read_bytes()==record_bytes


def test_local_mirror_keeps_prior_issues(tmp_path):
    def git(*args):
        return subprocess.run(["git","-C",str(tmp_path),*args],capture_output=True,check=True)
    git("init")
    p=tmp_path/delivery.DIR/DAY/"010000.json"
    write(p,{"record":1})
    git("add",".")
    git("-c","user.name=test","-c","user.email=test@example.invalid","commit","-m","prior")
    p.unlink()
    delivery.protect(tmp_path)
    assert json.loads(p.read_bytes())=={"record":1}
    write(p,{"record":2})
    with pytest.raises(ValueError,match="immutable"):
        delivery.protect(tmp_path)


def test_switch_and_locale_docs(tmp_path, monkeypatch):
    n,_,s,_=inputs()
    monkeypatch.setenv("TGEMS_H1_ISSUE","0")
    h.regular(tmp_path,n,s)
    assert not list(tmp_path.iterdir())
    root=Path(__file__).resolve().parents[1]
    for locale in ("en","ja","ko"):
        doc=(root/"docs"/locale/"lgbm-design.md").read_text(encoding="utf8")
        for literal in ("SD-H1-P50","651","44","40/44","594.7","445.6","50:50","2026-08-01"):
            assert literal in doc
