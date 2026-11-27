import json
import os
import subprocess
from datetime import date

import pytest

from python.forecast import d1_component as policy
from scripts.check_d1_trial import assess, summarize
from scripts.prepare_d1_receipt import from_public_ref


DAY = date.fromisoformat(policy.APPROVED_TARGETS[0])


def test_switch_is_bounded_even_if_deployment_variable_is_wrong():
    cfg = {"d1_component_trial": {"policy": policy.FINGERPRINT, "targets": [str(DAY)]}}
    assert policy.requested(cfg, DAY)
    cfg["d1_component_trial"]["targets"].append("2027-01-01")
    assert not policy.requested(cfg, DAY)
    assert not policy.requested(cfg, date(2027, 1, 1))


def test_public_commit_monitor(tmp_path):
    def git(*args, stamp=None):
        env = {**os.environ, "GIT_AUTHOR_NAME":"test", "GIT_COMMITTER_NAME":"test",
               "GIT_AUTHOR_EMAIL":"test@invalid", "GIT_COMMITTER_EMAIL":"test@invalid"}
        if stamp:
            env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], env=env)
    def put(path, data):
        dest=tmp_path/path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data), encoding="utf-8")
    def publish(stamp):
        git("add",".")
        git("-c","commit.gpgsign=false","commit","-qm","fixture",stamp=stamp)
    def snap(stamp,active=False):
        series=[]; stages=[]
        for h in range(24):
            ts=f"{DAY}T{h:02d}:00:00+09:00"
            v=100+h if active else 110
            row=dict(ts=ts,forecastMw=v,p95LowerMw=v-10,p95UpperMw=v+10)
            if active:row["intervalReferenceForecastMw"]=110
            series.append(row)
            stages.append(dict(ts=ts,forecastMwByStage=dict(incumbent_pre_calibration=110,raw_lgbm=v)))
        q=dict(targetDate=str(DAY),generatedAt=stamp,series=series,model=dict(artifactSha256=policy.ARTIFACT),
               servingPolicyFingerprint=policy.FINGERPRINT if active else policy.BASE,
               observationSummary=dict(observedActualHoursAtGeneration=0),forecastBuild=dict(series=stages))
        if active:q["d1PointPolicy"]=dict(referencePolicy=policy.BASE,version=policy.EDITION,fingerprint=policy.FINGERPRINT,writer="windows-etl")
        return q
    git("init","-q")
    put(".etl_state.json",{"okDates":[]})
    s1=snap("2026-11-29T01:00:00+09:00")
    put(policy.origin_path(DAY),dict(s1,origin=dict(type="day_ahead_first_publish",immutable=True)))
    put(f"forecast_snapshots/{DAY}/one.json",s1)
    publish("2026-11-29T01:05:00+09:00")
    assert from_public_ref(tmp_path,"HEAD",DAY)["commit"]==git("rev-parse","HEAD").decode().strip()
    s2=snap("2026-11-29T17:00:00+09:00",True)
    put(f"forecast_snapshots/{DAY}/two.json",s2)
    publish("2026-11-29T17:05:00+09:00")
    assert summarize(tmp_path,"HEAD",DAY)["state"]=="awaiting_finalized_24h"
    s3=snap("2026-11-30T00:05:00+09:00")
    put(f"forecast_snapshots/{DAY}/three.json",s3)
    publish("2026-11-30T00:10:00+09:00")
    put(".etl_state.json",{"okDates":[str(DAY)]})
    put(f"actual/{DAY}.json",{"series":[dict(ts=x["ts"],actualMw=100) for x in s1["series"]]})
    publish("2026-12-01T07:50:00+09:00")
    r=summarize(tmp_path,"HEAD",DAY)
    assert r["state"]=="scored" and r["issues"]==2 and r["changedPolicyIssues"]==1
    assert r["firstD1Incumbent"] and r["sameDayIssues"]==1 and not r["sameDayWrongIdentity"]
    assert r["activeWriterCounts"]=={"windows-etl":1}
    assert r["mae"]==10.75 and r["referenceMae"]==r["referenceRmse"]==10
    assert r["rmse"]==pytest.approx(((2400+sum(h*h for h in range(24)))/48)**.5)
    assert r["p95"]==pytest.approx(20.65) and r["maximum"]==23
    assert r["coverage"]==35/48 and r["referenceCoverage"]==1
    assert r["revisionUtilityMw"]=={"served":-1.5,"reference":0}
    assert r["midnightRevisionUtilityMw"]=={"served":1.5,"reference":0}
    assert assess([r])["state"]=="investigate_do_not_expand"
