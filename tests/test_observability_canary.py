"""Integration boundaries only; Git and HTTP transports never leave these fixtures."""
from contextlib import contextmanager
import io
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

from python.observability import runner
from ops.observability.verify import verify_fixture
from scripts import restore_public_from_data_branch as restore
from scripts import trigger_deploy_workflow as dispatch
from tests.test_observability import memory_sdk


@pytest.mark.parametrize("fetch_rc,probe_rc,expected", [(0,2,"skipped"),(1,2,"degraded"),(0,128,"degraded")])
def test_restore_preserves_original_decision(monkeypatch,tmp_path,fetch_rc,probe_rc,expected):
    exporter=memory_sdk(monkeypatch,tmp_path/"events")
    monkeypatch.setattr(restore,"REPO_ROOT",tmp_path)
    monkeypatch.setattr(restore,"PUBLIC_DIR",tmp_path/"public")
    calls=[]
    def run(args,**kwargs):
        assert kwargs["cwd"]==tmp_path
        calls.append(args[1])
        result={"fetch":fetch_rc,"ls-remote":probe_rc}[args[1]]
        return subprocess.CompletedProcess(args,result)
    fake=SimpleNamespace(run=run,DEVNULL=subprocess.DEVNULL,CalledProcessError=subprocess.CalledProcessError)
    monkeypatch.setattr(restore,"subprocess",fake)
    assert runner.main(["restore"]) is None
    assert calls==["fetch","ls-remote"] and restore.subprocess is fake and restore.PUBLIC_DIR.is_dir()
    spans={s.name:s for s in exporter.get_finished_spans()}
    assert spans["data.restore"].attributes["outcome"]==expected
    for child in ("restore.fetch","restore.probe"):
        assert spans[child].parent.span_id==spans["data.restore"].context.span_id


@pytest.mark.parametrize("existing", [False,True])
def test_fetch_month_no_duplicate_download(monkeypatch,tmp_path,existing):
    from python.etl import fetch_tepco
    exporter=memory_sdk(monkeypatch,tmp_path/"events")
    name="20230430_power_usage.csv"; payload=b"synthetic bytes"
    wire=io.BytesIO()
    with zipfile.ZipFile(wire,"w") as archive:archive.writestr(name,payload)
    out=tmp_path/"csv";dest=out/"2023"/"202304_power_usage"/name
    if existing:
        dest.parent.mkdir(parents=True);dest.write_bytes(payload)
    calls=[]
    def fetch(url):
        calls.append(1)
        return wire.getvalue()
    monkeypatch.setattr(fetch_tepco,"_download_zip_bytes",fetch)
    runner.main(["fetch","--month","202304","--out",str(out)])
    spans={s.name:s for s in exporter.get_finished_spans()}
    assert dest.read_bytes()==payload and calls==[1]
    assert spans["etl.fetch_historical"].attributes["outcome"]==("skipped" if existing else "ok")
    assert spans["source.fetch"].parent.span_id==spans["etl.fetch_historical"].context.span_id


def test_publish_transport_not_dispatch(monkeypatch,tmp_path):
    from scripts import publish_data_branch as publish
    exporter=memory_sdk(monkeypatch,tmp_path/"events")
    calls=[]
    def fake_run(args,cwd):
        assert cwd==tmp_path
        calls.append(tuple(args))
    monkeypatch.setattr(publish,"_run",fake_run)
    # Exercise the actual retry boundary, never the real repository orchestrator.
    monkeypatch.setattr(publish,"main",lambda:publish._push_with_retry(tmp_path))
    runner.main(["publish"])
    spans={s.name:s for s in exporter.get_finished_spans()}
    assert calls==[("git","push","origin","HEAD:data")]
    assert set(spans)=={"publish.request","git.publish"}
    assert spans["git.publish"].parent.span_id==spans["publish.request"].context.span_id


@pytest.mark.parametrize("http_status,exit_code", [(204,0),(500,1)])
def test_dispatch_only_measures_request(monkeypatch,tmp_path,http_status,exit_code):
    exporter=memory_sdk(monkeypatch,tmp_path/"events")
    monkeypatch.setattr(dispatch,"_repo_full_name",lambda:"example/fixture")
    monkeypatch.setattr(dispatch,"_github_token",lambda:"synthetic-not-a-key")
    calls=[]
    @contextmanager
    def open_request(req,timeout):
        calls.append(req.get_method());yield SimpleNamespace(status=http_status)
    monkeypatch.setattr(dispatch.urllib.request,"build_opener",lambda *a:SimpleNamespace(open=open_request))
    try:
        runner.main(["dispatch"]);actual=0
    except SystemExit as e:actual=e.code
    assert actual==exit_code and calls==["POST"]
    (span,)=exporter.get_finished_spans()
    assert span.name=="workflow.dispatch" and span.attributes["outcome"]==("failed" if exit_code else "ok")


def test_trace_verification_requires_fixture_and_reachable_edges():
    root={"name":"etl.batch","spanId":"a","attributes":[{"key":"outcome","value":{"stringValue":"skipped"}}],
          "startTimeUnixNano":"5","endTimeUnixNano":"3000005"}
    child={**root,"name":"input.inventory","spanId":"b","parentSpanId":"a"}
    service={"key":"service.name","value":{"stringValue":"tgems-fixture"}}
    doc={"batches":[{"resource":{"attributes":[service]},"scopeSpans":[{"spans":[root,child]}]}]}
    result=verify_fixture(doc,"skipped")
    assert result["parent_links_checked"]==1 and result["stage_durations_ms"]["etl.batch"]==[3]
    child["parentSpanId"]="missing"
    with pytest.raises(ValueError,match="orphan"):verify_fixture(doc,"skipped")
    service["value"]["stringValue"]="tgems-etl"
    with pytest.raises(ValueError,match="non-fixture"):verify_fixture(doc,"skipped")
