"""Offline acceptance tests for optional observability; no public or private data."""
from datetime import datetime
import errno
import json
import math
import os
from pathlib import Path
import re
from queue import Queue
import sys
from threading import Event
import time
from types import SimpleNamespace

import pytest
import yaml

from python.observability import public, runner, runtime
from python.observability.contract import OPERATIONS, valid_parent
from python.observability.local_log import LocalLog
from ops.observability import dashboards


@pytest.mark.parametrize("value", ["", "00-"+"0"*32+"-"+"1"*16+"-01",
    "01-"+"1"*32+"-"+"2"*16+"-01","arbitrary", "00-"+"F"*32+"-"+"1"*16+"-01"])
def test_invalid_parent(value):
    assert not valid_parent(value)


@pytest.mark.parametrize("flags", ["00","01","02","03","ff"])
def test_trace_flags_are_a_byte(flags):
    assert valid_parent("00-"+"1"*32+"-"+"2"*16+"-"+flags)


@pytest.mark.parametrize("enabled", [False, True])
def test_no_sdk_keeps_business_exception_and_return(monkeypatch,enabled):
    monkeypatch.setitem(sys.modules,"opentelemetry",None)
    rt=runtime.Runtime("tgems-etl",enabled=enabled)
    calls=[]
    obj=object()
    def business():
        calls.append(1)
        return obj
    with rt.stage("model.predict"):
        assert business() is obj
    exc=ValueError("sensitive error never exported")
    with pytest.raises(ValueError) as e:
        with rt.stage("model.predict"):raise exc
    assert e.value is exc and calls==[1] and not rt.carrier()
    rt.close()


def memory_sdk(monkeypatch,tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.resources import Resource
    exporter=InMemorySpanExporter()
    monkeypatch.setattr(runtime,"transport",lambda service, signal:(Resource({"service.name":service}),exporter))
    monkeypatch.setattr(runtime,"LocalLog",lambda: LocalLog(tmp_path))
    monkeypatch.setenv("TGEMS_OTEL_ENABLED","1")
    monkeypatch.delenv("TGEMS_OTEL_FIXTURE",raising=False)
    return exporter


def test_nesting_propagation_errors_redaction_and_logs(monkeypatch,tmp_path):
    exporter=memory_sdk(monkeypatch,tmp_path)
    monkeypatch.setenv("TGEMS_TRACEPARENT","invalid")
    rt=runtime.Runtime("tgems-host")
    with rt.stage("etl.local_run"):
        env=rt.carrier()
        assert valid_parent(env["TGEMS_TRACEPARENT"])
        with pytest.raises(PermissionError):
            with rt.stage("git.publish"): raise PermissionError("SECRET_CANARY")
    rt.close()
    traces=exporter.get_finished_spans()
    root,child=sorted(traces,key=lambda s:s.start_time)
    assert child.parent.span_id==root.context.span_id and root.parent is None
    assert child.attributes=={"outcome":"failed","reason":"permission"}
    assert root.attributes["outcome"]=="degraded"
    assert all(not s.events and not s.links for s in traces)
    events=(tmp_path/"events.jsonl").read_text()
    assert "SECRET_CANARY" not in events and format(root.context.trace_id,"032x") in events
    assert {json.loads(line)["correlation"] for line in events.splitlines()}=={env["TGEMS_OTEL_CORRELATION"]}
    monkeypatch.setenv("TGEMS_TRACEPARENT",env["TGEMS_TRACEPARENT"])
    exporter=memory_sdk(monkeypatch,tmp_path)
    child_rt=runtime.Runtime("tgems-etl")
    with child_rt.stage("etl.batch"):pass
    child_rt.close()
    propagated=exporter.get_finished_spans()[-1]
    assert propagated.parent.span_id==root.context.span_id and propagated.context.trace_id==root.context.trace_id


def test_setup_failure_does_not_skip_or_retry_business(monkeypatch,tmp_path):
    memory_sdk(monkeypatch,tmp_path)
    def broken(*a,**k): raise RuntimeError("instrumentation")
    monkeypatch.setattr(runtime,"transport",broken)
    rt=runtime.Runtime("tgems-etl")
    assert rt.tracer is None
    rt.tracer=SimpleNamespace(start_span=broken)
    calls=[]
    def business():
        calls.append(1)
        raise SystemExit(23)
    mod=SimpleNamespace(work=business)
    def hooks():
        yield mod,"work","etl.batch",None
        raise ValueError("bad optional hook")
    with pytest.raises(SystemExit) as e:
        with runner.bindings(rt,hooks()):mod.work()
    assert e.value.code==23 and calls==[1] and mod.work is business


def test_sdk_queue_saturation_and_timeout(monkeypatch,tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import SpanExportResult
    blocked, release, seen = Event(), Event(), []
    class Slow:
        def export(self,spans):
            blocked.set()
            release.wait(5)
            seen.extend(spans)
            return SpanExportResult.FAILURE
        def shutdown(self): pass
    monkeypatch.setattr(runtime,"transport",lambda *a:(Resource({}),Slow()))
    monkeypatch.setattr(runtime,"LocalLog",lambda:None)
    rt=runtime.Runtime("tgems-etl",enabled=True)
    total=0
    try:
        for _ in range(64):
            with rt.stage("source.fetch"):total+=1
        assert blocked.wait(2)
        for _ in range(800):
            with rt.stage("source.fetch"):total+=1
        start=time.monotonic()
        rt.close()
        assert time.monotonic()-start<1
    finally:
        release.set()
    rt.provider.shutdown()
    assert total==864 and len(seen)<total


def test_forbidden_export_endpoint(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    monkeypatch.setenv("TGEMS_OTEL_ENDPOINT","https://example.invalid")
    with pytest.raises(ValueError):runtime.transport("tgems-public","metrics")


def test_transport_timeout_is_bounded_and_local(monkeypatch,tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    from requests.adapters import HTTPAdapter
    from requests.exceptions import ReadTimeout
    attempts=[]
    def timeout(self,request,**kwargs):
        attempts.append((request.url,dict(request.headers),kwargs["timeout"]))
        raise ReadTimeout("simulated silent receiver")
    monkeypatch.setattr(HTTPAdapter,"send",timeout)
    monkeypatch.setattr(runtime,"LocalLog",lambda: LocalLog(tmp_path))
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS","Authorization=SECRET_CANARY")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT","https://unauthorized.invalid")
    monkeypatch.delenv("TGEMS_OTEL_ENDPOINT",raising=False)
    rt=runtime.Runtime("tgems-etl",enabled=True)
    calls=[]
    with rt.stage("source.fetch"):calls.append("ok")
    start=time.monotonic();rt.close()
    assert time.monotonic()-start<1 and calls==["ok"]
    assert attempts and all(url=="http://127.0.0.1:4318/v1/traces" and
        "Authorization" not in headers and 0<t<=.4 for url,headers,t in attempts)


def test_log_bounded_and_full_disk(monkeypatch,tmp_path):
    entry={"stage":"model.predict"}
    sink=LocalLog(tmp_path,limit=40)
    sink.done.set()
    sink.thread.join(1)
    for _ in range(40):sink.write(entry)
    assert len(list(tmp_path.glob("events*.jsonl")))==4
    for f in tmp_path.glob("events*.jsonl"):
        os.utime(f,(time.time()-9*86400,)*2)
    sink.write(entry)
    assert len(list(tmp_path.glob("events*.jsonl")))==1
    sink.queue=Queue(1)
    sink.put(entry);sink.put(entry)
    assert sink.queue.qsize()==1
    tried=Event()
    def disk_full(*a):
        tried.set()
        raise OSError(errno.ENOSPC,"simulated")
    monkeypatch.setattr(LocalLog,"write",disk_full)
    limited=LocalLog(tmp_path)
    limited.put(entry);assert tried.wait(1)
    limited.done.set();limited.thread.join(1)
    assert not limited.thread.is_alive()


def public_docs():
    day="2026-01-01"; now=datetime.fromisoformat("2026-01-02T02:00:00+09:00")
    summary=dict(modelMaeMw=50,modelRmseMw=75,modelWapePct=.5)
    row=dict(date=day,hours=24,includedInSummary=True,modelName="lgbm_quantile_q50",
             modelFamily="lgbm_quantile_q50",**summary)
    return now,{"status.json": dict(project="tokyo-grid-ems",schemaVersion="1.0.0",
        timezone="Asia/Tokyo",lastUpdatedAt=now.isoformat(),coverageTo=day),
        ".etl_state.json":{"okDates":[day],"failedDates":[]}, "actual/2026-01-02.json":{"date":"2026-01-02","series":[
             dict(ts=now.isoformat(), actualMw=20000,actualSource="observed")]},
        "metrics/forecast_accuracy.json":{"schemaVersion":"1.0.0","generatedAt":now.isoformat(),
            "methodology":{"type":"latest_published_value_reference","formalParityEligible":False},
            "daily":[row]},
        "reports/daily/"+day+".json":{"date":day,"timezone":"Asia/Tokyo","schemaVersion":"1.0.0",
            "availability":"ok","model":{"name":row["modelName"],"family":row["modelFamily"]},
            "summary":dict(comparableHours=24,**summary),"timeBands":[dict(code=k,hours=v,modelBiasMw=-1,
                modelMaeMw=50) for k,v in public.BANDS.items()]}}


def test_projector_populations_and_unavailable():
    now,docs=public_docs()
    read=lambda:public.project(lambda path,limit:docs[path],now)
    values=read()
    assert values["tgems_quality_wape_ratio"]==[(.005,{"basis":"published","window":"day"})]
    assert len(values["tgems_quality_band_bias_mw"])==5
    docs["reports/daily/2026-01-01.json"]["model"]["family"]="other"
    assert "tgems_quality_band_bias_mw" not in read()
    docs["metrics/forecast_accuracy.json"]["daily"][0]["hours"]=23
    assert "tgems_quality_mae_mw" not in read()
    docs["metrics/forecast_accuracy.json"]["daily"][0]["hours"]=24
    docs[".etl_state.json"]["failedDates"]=["2026-01-01"]
    assert "tgems_quality_samples" not in read()
    docs[".etl_state.json"]["okDates"]=[]
    assert "tgems_quality_samples" not in read()
    docs["actual/2026-01-02.json"]["series"][0]["actualSource"]="unknown"
    assert "tgems_public_slots" not in read()
    assert all(math.isnan(v) for v,a in public.observations({},"quality_band_bias_mw"))


def test_deployment_contract():
    folder=Path(dashboards.__file__).parent
    cfg=yaml.safe_load((folder/"compose.yml").read_text())
    assert cfg["name"]=="tgems-observe" and len(cfg["services"])==4
    for s in cfg["services"].values():
        assert "@sha256:" in s["image"] and s["mem_limit"] and s["read_only"]
        assert all(p.startswith("127.0.0.1:") for p in s.get("ports",[]))
    collector=yaml.safe_load((folder/"collector.yml").read_text())
    assert not any(p.startswith("logs") for p in collector["service"]["pipelines"])
    assert "filter/business" in collector["service"]["pipelines"]["traces/business"]["processors"]
    name_rule=collector["processors"]["filter/traces"]["traces"]["span"][1]
    pattern=name_rule.split('"')[1]
    assert all(re.fullmatch(pattern, op) for op in OPERATIONS)
    dims=collector["connectors"]["span_metrics"]["dimensions"]
    assert {d["name"] for d in dims}=={"outcome","reason"}
    for uid,(title,panels) in dashboards.DASHBOARDS.items():
        assert json.loads((folder/"grafana/dashboards"/(uid+".json")).read_text())==dashboards.build(uid,title,panels)
    assert len(OPERATIONS)<32
