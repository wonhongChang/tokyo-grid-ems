import json
from copy import deepcopy
from urllib.error import HTTPError
from unittest.mock import Mock

import pytest
from python.eval import ai_daily_report as live
from python.eval.luna_brief import dashboard as view
from tests.test_experimental_luna_report_scope import synthetic


DAY = "2026-11-26"
STAMP = "2026-11-27T08:00:00+09:00"


def seed(root,monkeypatch):
    from tests import test_experimental_luna_report_scope as fixture
    monkeypatch.setattr(fixture,"DAY",DAY)
    archive,_,_=synthetic(root)
    op=root/f"reports/daily/{DAY}.json"
    doc=json.loads(op.read_bytes());doc["generatedAt"]=STAMP
    live._write_json(op,doc)
    live._write_json(root/"reports/daily/index.json",{"reports":[{"date":DAY,"availability":"ok"}]})
    monkeypatch.setattr(live,"_load_local_dotenv",lambda *_:None)
    monkeypatch.setattr(live,"_clean_env_value",lambda *_:None)
    return root/"reports/ai/daily"


def test_first_new_target_and_immutable_cached_fallback(tmp_path,monkeypatch):
    cache=seed(tmp_path,monkeypatch)
    idx,reports,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=False)
    for lang,(r,) in reports.items():
        assert r["operationsBrief"]["version"]=="tokyo-grid-ops/v8"
        assert r["operationsBrief"]["fingerprint"]==r["inputSnapshot"]["fingerprint"]
        assert r["operationsBrief"]["advisoryStatus"]=="not_requested"
        assert r["operationsBrief"]["date"]==idx[lang]["latest"]["date"]==DAY
        live._write_json(cache/lang/(DAY+".json"),r)
    monkeypatch.setattr(live,"_clean_env_value",lambda *_:"not-a-real-key")
    monkeypatch.setattr(view,"attach",Mock(side_effect=AssertionError("rebuild of archived date")))
    monkeypatch.setattr(live,"_openai_request_json",Mock(side_effect=AssertionError("duplicate API attempt")))
    index2,again,budget=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,existing_report_root=cache,skip_existing=True,use_openai=True)
    assert index2==idx and not any(again.values()) and budget["used"]==0


def test_do_not_mix_new_layout_into_existing_legacy_day(tmp_path,monkeypatch):
    cache=seed(tmp_path,monkeypatch)
    _,old,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,report_layout="legacy",use_openai=False)
    live._write_json(cache/"ko"/(DAY+".json"),old["ko"][0])
    _,again,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,existing_report_root=cache,skip_existing=True,use_openai=False)
    assert not again["ko"]
    assert all("operationsBrief" not in again[l][0] for l in ("en","ja"))


def test_partial_locale_repaired_only_on_exact_frozen_basis(tmp_path,monkeypatch):
    cache=seed(tmp_path,monkeypatch)
    _,fresh,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=False)
    original=fresh["en"][0]
    live._write_json(cache/"en"/(DAY+".json"),original)
    args=dict(existing_report_root=cache,skip_existing=True,use_openai=False)
    indexes,repaired,_=live.build_ai_daily_reports_multilingual(tmp_path,"2026-11-27T09:30:00+09:00",**args)
    assert not repaired["en"] and indexes["en"]["latest"]["date"]==DAY
    assert repaired["ko"]==fresh["ko"] and repaired["ja"]==fresh["ja"]
    altered=deepcopy(original);altered["operationsBrief"]["basisDigest"]="wrong"
    live._write_json(cache/"en"/(DAY+".json"),altered)
    indexes,changes,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,**args)
    assert not any(changes.values()) and indexes["en"]["latest"]["date"]==DAY and not indexes["ko"]["latest"]


def test_render_error_only_disables_the_new_layout(tmp_path,monkeypatch):
    seed(tmp_path,monkeypatch)
    monkeypatch.setattr(view,"render",Mock(side_effect=ValueError("unsupported")))
    indexes,rows,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=False)
    assert all(i["latest"]["date"]==DAY for i in indexes.values())
    assert all("operationsBrief" not in r[0] for r in rows.values())


def test_report_rollback_does_not_call_a_different_model(tmp_path,monkeypatch):
    seed(tmp_path,monkeypatch)
    monkeypatch.setenv("TOKYO_GRID_EMS_DISABLE_REPORT_V8","1")
    monkeypatch.setattr(live,"_clean_env_value",lambda *_:"offline")
    monkeypatch.setattr(live,"_openai_request_json",Mock(side_effect=AssertionError("rollback API call")))
    _,rows,b=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=True)
    assert b["used"]==0 and all("operationsBrief" not in rr[0] for rr in rows.values())


@pytest.mark.parametrize("src",["ko","root"])
def test_missing_default_alias_is_an_exact_copy_not_a_regeneration(tmp_path,monkeypatch,src):
    cache=seed(tmp_path,monkeypatch)
    _,rows,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=False)
    alias,localized=cache/(DAY+".json"),cache/"ko"/(DAY+".json")
    original,other=(localized,alias) if src=="ko" else (alias,localized)
    original.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(rows["ko"][0],indent=3)
    original.write_bytes(text.encode());stamp=original.stat().st_mtime_ns
    _,new,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,existing_report_root=cache,skip_existing=True,use_openai=False)
    assert other.read_bytes()==original.read_bytes()==text.encode()
    assert original.stat().st_mtime_ns==stamp and not new["ko"]


def test_scheduled_writer_persists_view_and_does_not_touch_date_files_again(tmp_path,monkeypatch):
    from python.etl import run_batch
    cache=seed(tmp_path,monkeypatch)
    monkeypatch.setattr(run_batch,"ts_now",lambda:STAMP)
    monkeypatch.setenv("OPENAI_DAILY_REPORT_AUTO_ENABLE","0")
    # Only the report writer is invoked, never the batch or its collection/forecast functions.
    run_batch._write_ai_daily_reports(tmp_path)
    paths=[cache/d/(DAY+".json") for d in ("en","ko","ja","")]
    before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
    assert all(json.loads(blob)["operationsBrief"]["version"]=="tokyo-grid-ops/v8" for blob,_ in before.values())
    run_batch._write_ai_daily_reports(tmp_path)
    assert before=={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
    assert json.loads((cache/"ko/index.json").read_bytes())["latest"]["date"]==DAY


def test_transport_failure_consumes_one_call_and_preserves_every_node(tmp_path,monkeypatch):
    seed(tmp_path,monkeypatch)
    _,ok,_=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=False)
    monkeypatch.setattr(live,"_clean_env_value",lambda *_:"offline-test-key")
    refs=view.relations.common.core.refs
    monkeypatch.setattr(refs,"evidence",lambda _:{"pair":{"kind":"shape"}})
    mock=Mock(side_effect=HTTPError("https://api.openai.com/v1/responses",503,"synthetic",{},None))
    monkeypatch.setattr(live.urllib.request,"urlopen",mock)
    monkeypatch.setenv("OPENAI_DAILY_REPORT_HTTP_ATTEMPTS","5")
    _,failed,budget=live.build_ai_daily_reports_multilingual(tmp_path,STAMP,use_openai=True)
    assert mock.call_count==budget["used"]==1
    payload=json.loads(mock.call_args.args[0].data)
    assert (payload["model"],payload["reasoning"],payload["max_output_tokens"])==("gpt-6-luna",{"effort":"none"},4000)
    for lang,(r,) in failed.items():
        assert r["operationsBrief"]["advisoryStatus"]=="unavailable"
        assert r["operationsBrief"]["nodes"]==ok[lang][0]["operationsBrief"]["nodes"]
        assert r["performance"]==ok[lang][0]["performance"]
        assert r["generator"]["provider"]=="fallback"


@pytest.mark.parametrize("unsafe",['<img src="x">','<a href="https://example.org">link</a>','<p onclick="alert(0)">x</p>','<script>x</script>'])
def test_dashboard_does_not_ship_executable_markup(unsafe):
    with pytest.raises(ValueError):view._Contents().feed("<main>"+unsafe+"</main>")
