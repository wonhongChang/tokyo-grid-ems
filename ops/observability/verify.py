"""Read-only acceptance using Grafana's local proxy; never prints secrets or MW data."""
import argparse
import base64
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

from .dashboards import DASHBOARDS


def verify_fixture(doc, outcome):
    groups=doc.get("batches",doc.get("resourceSpans",[]))
    spans={}
    for group in groups:
        attrs=group["resource"].get("attributes",[])
        if not any(a["key"]=="service.name" and a["value"].get("stringValue")=="tgems-fixture" for a in attrs):
            raise ValueError("non-fixture resource")
        for scope in group["scopeSpans"]:
            for s in scope["spans"]:
                if s["spanId"] in spans:raise ValueError("duplicate span identity")
                spans[s["spanId"]]=s
    roots=[s for s in spans.values() if s["name"]=="etl.batch"]
    if len(roots)!=1:raise ValueError("expected one batch root")
    root=roots[0]
    actual=next((a["value"].get("stringValue") for a in root.get("attributes",[]) if a["key"]=="outcome"),None)
    if actual!=outcome:raise ValueError("wrong batch outcome")
    for s in spans.values():
        if s is root:continue
        current=s;visited=set()
        while current is not root:
            if current["spanId"] in visited or current.get("parentSpanId") not in spans:
                raise ValueError("orphan or cyclic stage")
            visited.add(current["spanId"]);current=spans[current["parentSpanId"]]
    names={s["name"] for s in spans.values()}
    required={"ok":{"model.load","features.build","model.predict","forecast.calibrate","forecast.intraday",
                    "forecast.publish","snapshot.retain","publication.freeze","input.quality"},
              "skipped":{"input.inventory"},"failed":set(),"degraded":{"input.parse"}}[outcome]
    if not required.issubset(names):raise ValueError("missing required stage(s): "+str(sorted(required-names)))
    timings={}
    for s in spans.values():
        key=s["name"]
        elapsed=(int(s["endTimeUnixNano"])-int(s["startTimeUnixNano"]))/1e6
        if elapsed<0:raise ValueError("negative stage duration")
        timings.setdefault(key,[]).append(round(elapsed,3))
    return {"outcome":outcome,"spans":len(spans),"distinct_stages":len(names),
            "parent_links_checked":len(spans)-1,"stage_durations_ms":timings}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-public",action="store_true",help="Run the public projector first")
    parser.add_argument("--fixture-trace",action="append",default=[],metavar="OUTCOME:TRACE_ID",
                        help="Exact IDs from the staging result only")
    args=parser.parse_args()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):
            return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    password=(Path(__file__).parent/".local/admin_password").read_bytes().strip()
    auth="Basic "+base64.b64encode(b"admin:"+password).decode("ascii")
    def get(path,**params):
        suffix="?"+urllib.parse.urlencode(params) if params else ""
        req=urllib.request.Request("http://127.0.0.1:3300"+path+suffix,headers={"Authorization":auth})
        with opener.open(req,timeout=10) as response:
            return json.load(response)
    def prom(query):
        data=get("/api/datasources/proxy/uid/tgems-prom/api/v1/query",query=query)
        if data.get("status")!="success":raise ValueError("PromQL failed")
        return data["data"]["result"]
    def tempo(query,window=21600):
        end=int(time.time())
        return get("/api/datasources/proxy/uid/tgems-tempo/api/search",q=query,limit=1,start=end-window,end=end)
    def require(condition,reason):
        if not condition:raise RuntimeError(reason)
    for uid in ("tgems-prom","tgems-tempo"):
        require(get("/api/datasources/uid/"+uid+"/health").get("status")=="OK","Datasource unavailable: "+uid)
    counts={"dashboards":0,"promql":0,"traceql":0}
    for uid,(title,spec) in DASHBOARDS.items():
        doc=get("/api/dashboards/uid/tgems-"+uid)["dashboard"]
        require(doc["title"]==title and len(doc["panels"])==len(spec),"Dashboard provisioning mismatch: "+uid)
        counts["dashboards"]+=1
        for panel in doc["panels"]:
            target=panel["targets"][0]
            if "expr" in target:prom(target["expr"]);counts["promql"]+=1
            else:tempo(target["query"]);counts["traceql"]+=1
    targets=prom('up{job=~"collector|grafana|tempo|prometheus|pipeline"}')
    require({t["metric"]["job"] for t in targets if float(t["value"][1])==1}==
            {"collector","grafana","tempo","prometheus","pipeline"},"Scrape target unavailable")
    if args.require_public:
        require(prom('(tgems_quality_available == 1) and on() (time()-tgems_projector_timestamp_seconds < 180)'),
                "Fresh matching published quality unavailable")
        # Recent exact IDs can be readable before the Tempo search index catches up.
        deadline=time.monotonic()+45
        while not tempo('{ resource.service.name="tgems-public" && name="public.observe" }',300).get("traces"):
            require(time.monotonic()<deadline,"Recent public trace not searchable within 45s")
            time.sleep(3)
    if args.fixture_trace:
        checked=[]
        for ref in args.fixture_trace:
            if not re.fullmatch(r"(ok|skipped|degraded|failed):[0-9a-f]{32}",ref):parser.error("invalid fixture reference")
            outcome,trace=ref.split(":")
            checked.append(verify_fixture(get("/api/datasources/proxy/uid/tgems-tempo/api/traces/"+trace),outcome))
        require(not prom('tgems_stage_calls_total{service_name="tgems-fixture"} or tgems_stage_calls_total{job=~"(.*/)?tgems-fixture"}'),
                "Fixture in business metrics")
        counts["fixture_traces"]=checked
    print(json.dumps({**counts,"scrapes_up":len(targets),"fresh_public_required":args.require_public}))


if __name__=="__main__":
    main()
