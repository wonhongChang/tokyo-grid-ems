"""Read-only projector: one immutable public data-branch revision, fixed paths."""
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from .runtime import Runtime, transport
from .public_source import allowed, fetch, PagesDeployment, RemoteData, PAGES

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parents[2]
BANDS = {"overnight":6,"morning_ramp":5,"daytime":5,"late_afternoon":3,"evening":5}
QUALITY = {"mae_mw":"modelMaeMw","rmse_mw":"modelRmseMw","wape_ratio":"modelWapePct"}
INVALID = (KeyError, ValueError, TypeError, AttributeError, OverflowError, subprocess.SubprocessError, OSError)


def read_commit():
    def git(*args):
        return subprocess.check_output(["git","--no-optional-locks","-c",f"safe.directory={ROOT.as_posix()}",*args],
                                       cwd=ROOT, stderr=subprocess.DEVNULL,timeout=5)
    rev = git("rev-parse","--verify","refs/remotes/origin/data^{commit}").decode().strip()
    if not re.fullmatch("[0-9a-f]{40}",rev):
        raise ValueError("invalid public revision")
    def read(path, limit):
        if not allowed(path):
            raise ValueError("unapproved source")
        ref = f"{rev}:{path}"
        if int(git("cat-file","-s",ref)) > limit:
            raise ValueError("size limit")
        return json.loads(git("cat-file","blob",ref))
    return read


def finite(v):
    return type(v) in (int,float) and math.isfinite(v)


def epoch(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("naive time")
    return dt.timestamp()


def pages():
    doc=json.loads(fetch(PAGES+"status.json",262144,timeout=3))
    if doc.get("project")!="tokyo-grid-ems" or doc.get("schemaVersion")!="1.0.0":raise ValueError("invalid status")
    return doc


def project(read, now):
    # Each metric maps to observations (value, finite/allowlisted attributes).
    out = {}
    def add(name,v,**attrs):
        if finite(v):
            out.setdefault("tgems_"+name,[]).append((v,attrs))
    status = read("status.json",262144)
    if (status.get("project"),status.get("schemaVersion"),status.get("timezone")) != (
            "tokyo-grid-ems","1.0.0","Asia/Tokyo"):
        raise ValueError("unrecognized status")
    add("public_artifact_timestamp_seconds",epoch(status["lastUpdatedAt"]))
    try:
        day = now.astimezone(JST).date()
        doc = read(f"actual/{day}.json",65536)
        if doc.get("date") != day.isoformat():
            raise ValueError("actual date mismatch")
        seen,observed,fallback = set(),[],[]
        for point in doc["series"]:
            ts = datetime.fromisoformat(point["ts"])
            if ts.tzinfo is None or ts.astimezone(JST).date()!=day or ts.minute or ts.second or ts.microsecond or ts in seen:
                raise ValueError("invalid slot")
            seen.add(ts)
            if ts<=now and finite(point.get("actualMw")):
                if point.get("actualSource")=="observed": observed.append(ts.timestamp())
                elif point.get("actualSource")=="tepco_forecast_fallback": fallback.append(ts.timestamp())
                else: raise ValueError("unknown slot provenance")
        add("public_slots",len(observed),kind="observed")
        add("public_slots",len(fallback),kind="fallback")
        if observed: add("observed_slot_timestamp_seconds",max(observed))
    except INVALID:
        pass
    try:
        state=read(".etl_state.json",4*1024*1024)
        accepted={date.fromisoformat(d) for d in state["okDates"]}
        failed={date.fromisoformat(d) for d in state["failedDates"]}
        report=read("metrics/forecast_accuracy.json",1024*1024)
        method=report["methodology"]
        if report.get("schemaVersion")!="1.0.0" or method.get("type")!="latest_published_value_reference" or method.get("formalParityEligible") is not False:
            return out
        day=max(d for d in accepted if d < now.astimezone(JST).date())
        if day in failed:return out
        rows=[row for row in report["daily"] if row.get("date")==day.isoformat()]
        if len(rows)!=1:return out
        row=rows[0]
        if (row.get("hours")!=24 or row.get("includedInSummary") is not True or
            row.get("modelFamily")!="lgbm_quantile_q50" or row.get("modelName") not in
            ("lgbm_quantile_q50","lgbm_quantile_q50_intraday_residual")):return out
        attrs={"basis":"published","window":"day"}
        if not all(finite(row.get(k)) for k in QUALITY.values()):return out
        add("quality_report_timestamp_seconds",epoch(report["generatedAt"]))
        add("quality_target_timestamp_seconds",datetime.combine(day,datetime.min.time(),JST).timestamp())
        for name,key in QUALITY.items():
            if finite(row.get(key)):add("quality_"+name,row[key]/(100 if name=="wape_ratio" else 1),**attrs)
        add("quality_samples",24,**attrs)
        daily=read(f"reports/daily/{day}.json",262144)
        if not (daily.get("date")==day.isoformat() and daily.get("schemaVersion")=="1.0.0"
                and daily.get("availability")=="ok" and daily["model"].get("name")==row["modelName"]
                and daily["model"].get("family")==row["modelFamily"] and daily.get("timezone")=="Asia/Tokyo"
                and daily["summary"].get("comparableHours")==24 and all(
                    daily["summary"].get(k)==row.get(k) for k in QUALITY.values())):return out
        bands=daily["timeBands"]
        if len(bands)!=len(BANDS) or {b["code"] for b in bands}!=BANDS.keys():return out
        if any(b["hours"]!=BANDS[b["code"]] for b in bands):return out
        for band in bands:
            add("quality_band_bias_mw",band["modelBiasMw"],band=band["code"],**attrs)
            add("quality_band_mae_mw",band["modelMaeMw"],band=band["code"],**attrs)
    except INVALID:
        pass
    return out


NAMES = ("public_artifact_timestamp_seconds","public_slots","observed_slot_timestamp_seconds",
         "quality_report_timestamp_seconds","quality_target_timestamp_seconds","quality_mae_mw",
         "quality_rmse_mw","quality_wape_ratio","quality_samples","quality_band_bias_mw",
         "quality_band_mae_mw","projector_timestamp_seconds","projector_success","quality_available",
         "pages_success","pages_status_timestamp_seconds","pages_status_timestamp_match","pages_last_success_timestamp_seconds")


def observations(snapshot, suffix):
    # OTLP omission alone leaves the previous gauge visible until expiry. Explicit
    # NaN invalidates it immediately, without inventing a zero for a new population.
    if suffix=="public_slots":
        expected=[{"kind":s} for s in ("observed","fallback")]
    elif suffix.startswith("quality_band_"):
        expected=[{"basis":"published","window":"day","band":b} for b in BANDS]
    elif suffix in ("quality_samples", *("quality_"+k for k in QUALITY)):
        expected=[{"basis":"published","window":"day"}]
    else:
        expected=[{}]
    values=snapshot.get("tgems_"+suffix,())
    return [(next((v for v,a in values if a==attrs),math.nan),attrs) for attrs in expected]


def main(argv=None, *, managed=None):
    from argparse import ArgumentParser
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("--watch",action="store_true")
    parser.add_argument("--live-public",action="store_true",help="Explicitly enable this isolated projector and follow the public data branch over anonymous HTTPS.")
    parser.add_argument("--cycles",type=int,help="Stop after this many watch cycles; no scheduling or persistence.")
    args=parser.parse_args(argv)
    if args.cycles is not None and (not args.watch or args.cycles<1):parser.error("--cycles requires --watch and a positive count")
    live=args.live_public
    if live and (os.getenv("TGEMS_OTEL_FIXTURE")=="1" or os.getenv("TGEMS_OTEL_ENABLED") not in (None,"","1")):
        parser.error("live reader refused in a fixture or explicitly disabled environment")
    if not live and os.getenv("TGEMS_OTEL_ENABLED")!="1":
        parser.error("set TGEMS_OTEL_ENABLED=1 for the public projector")
    from .reader_control import exclusive
    with exclusive():
        return run(args,managed)


def run(args, managed):
    live=args.live_public
    from opentelemetry.metrics import Observation
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    resource,exporter=transport("tgems-public","metrics")
    reader=PeriodicExportingMetricReader(exporter,export_interval_millis=math.inf)
    provider=MeterProvider(resource=resource,metric_readers=[reader],shutdown_on_exit=False)
    meter=provider.get_meter("tgems.ops")
    snapshot={}
    for suffix in NAMES:
        name="tgems_"+suffix
        meter.create_observable_gauge(name,[lambda options,key=suffix:
            [Observation(v,a) for v,a in observations(snapshot,key)]])
    rt=Runtime("tgems-public",enabled=True)
    remote=RemoteData() if live else None
    source=remote.reader if live else read_commit
    deployment=PagesDeployment()
    cycles=0
    backoff=10
    try:
        while True:
            if managed:
                if managed.stop_requested():break
                if not managed.collector():
                    managed.mark("waiting_for_collector")
                    if not managed.wait(backoff):break
                    backoff=min(backoff*2,60)
                    continue
                backoff=10
            with rt.stage("public.observe") as result:
                try:
                    values=project(source(),datetime.now(JST))
                    success=1
                except INVALID:
                    values={};success=0
                try:
                    published=epoch(pages()["lastUpdatedAt"])
                    values["tgems_pages_status_timestamp_seconds"]=[(published,{})]
                    values["tgems_pages_success"]=[(1,{})]
                    if "tgems_public_artifact_timestamp_seconds" in values:
                        local=values["tgems_public_artifact_timestamp_seconds"][0][0]
                        values["tgems_pages_status_timestamp_match"]=[(int(local==published),{})]
                except INVALID:
                    values["tgems_pages_success"]=[(0,{})]
                if live:
                    try:values["tgems_pages_last_success_timestamp_seconds"]=[(deployment.read(),{})]
                    except INVALID:pass
                available=int("tgems_quality_samples" in values)
                if not (success and available and values["tgems_pages_success"][0][0]): result.outcome="degraded"
                snapshot=dict(values,tgems_projector_success=[(success,{})],
                              tgems_quality_available=[(available,{})],
                              tgems_projector_timestamp_seconds=[(time.time(),{})])
            provider.force_flush(timeout_millis=1500)
            if managed:managed.projected(bool(success),remote.sha)
            cycles+=1
            if not args.watch or cycles==args.cycles:break
            if managed:
                if not managed.wait(60):break
            else:time.sleep(60)
    finally:
        rt.close()
        provider.shutdown(timeout_millis=1500)
        if managed:managed.mark("faulted" if sys.exc_info()[0] is not None else "stopped")


if __name__=="__main__":
    main()
