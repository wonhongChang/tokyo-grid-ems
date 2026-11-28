from pathlib import Path
import yaml
from datetime import datetime
from scripts import hosted_preview as h


def test_hosted_read_only():
    wf=yaml.safe_load((Path(h.sd.ROOT)/".github/workflows/sameday-gaps.yml").read_bytes())
    assert list(wf["jobs"])==["preview"] and wf["permissions"]=={"contents":"read"}
    job=wf["jobs"]["preview"]
    assert "preview" in job["if"] and wf["concurrency"]["group"]!="pages"
    assert job["steps"][-1]["with"]["retention-days"]==90
    assert all(step.get("with",{}).get("persist-credentials") is False for step in job["steps"] if "checkout@" in step.get("uses",""))


def test_off_slot_does_not_contact_provider(monkeypatch,tmp_path):
    for k,v in (("GITHUB_SHA","1"*40),("GITHUB_RUN_ID","1"),("GITHUB_RUN_ATTEMPT","1")):monkeypatch.setenv(k,v)
    monkeypatch.setattr(h.sd,"git",lambda *a:"2"*40)
    monkeypatch.setattr(h,"now",lambda:datetime(2026,11,28,17,0,tzinfo=h.sd.src.JST))
    monkeypatch.setattr(h.sd.src,"fetch_csv",lambda:1/0)
    h.run(tmp_path/"base",tmp_path/"out")
    assert h.sd.read(tmp_path/"out"/"evidence.json")["status"]=="expired_slot"
