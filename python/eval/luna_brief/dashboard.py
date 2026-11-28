"""Publish the approved brief as text and semantic elements, never executable HTML."""
from html.parser import HTMLParser
from http.client import HTTPException
import hashlib
import json

from .candidate import build, relations
from .display import render


VERSION = "tokyo-grid-ops/v8"
MODEL = "gpt-6-luna"
ALLOWED = set("header small h1 h2 section p b details summary div table thead tbody tr th td a dl dt dd code".split())
ATTRIBUTES = {"id", "class", "scope", "tabindex", "data-id", "data-field", "href"}


class _Contents(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.main = False

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.main = True
        elif self.main:
            attrs = dict(attrs)
            if tag not in ALLOWED or not attrs.keys() <= ATTRIBUTES:
                raise ValueError("unsupported brief markup")
            if "href" in attrs and not (tag == "a" and attrs["href"].startswith("#row-")):
                raise ValueError("external brief link")
            node = [tag, attrs]
            (self.stack[-1] if self.stack else self.nodes).append(node)
            self.stack.append(node)

    def handle_data(self, data):
        if self.main and self.stack:
            self.stack[-1].append(data)

    def handle_endtag(self, tag):
        if tag == "main":
            if self.stack: raise ValueError("unbalanced brief")
            self.main = False
        elif self.main and (not self.stack or self.stack.pop()[0] != tag):
            raise ValueError("unbalanced brief")


def _select(public_dir, anchor, brief, key, budget):
    """Exactly one optional evidence selection for the date, shared across locales."""
    if not key or not budget.get("remaining") or brief["state"] != "daily_report_full":
        return [], "not_requested"
    live = relations.live
    packet = live._sanitize_openai_context(live._load_openai_context(public_dir, anchor))["factPacket"]
    refs = relations.common.core.refs
    evidence = refs.evidence(packet)
    if not any(r["kind"] in ("vintage", "shape") for r in evidence.values()):
        return [], "no_eligible_evidence"
    request = {"model":MODEL, "reasoning":{"effort":"none"}, "max_output_tokens":4000, "store":False,
               "instructions":refs.INSTRUCTIONS, "input":json.dumps({"evidence":list(evidence.values())},ensure_ascii=False,separators=(",",":")),
               "text":{"format":{"type":"json_schema","name":"bounded_observations","schema":refs.SCHEMA,"strict":True}}}
    if not live._consume_openai_budget(budget):return [], "not_requested"
    data = live._openai_request_json(request,key,live._env_int("OPENAI_DAILY_REPORT_TIMEOUT_SECONDS",live.OPENAI_DEFAULT_ANALYSIS_TIMEOUT_SECONDS),
                                     "evidence-selection",MODEL,attempt_limit=1)
    if data.get("status")!="completed" or data.get("model")!=MODEL:
        return [], "unavailable"
    raw = json.loads(live._extract_response_text(data))
    if (not isinstance(raw,dict) or not isinstance(raw.get("observations"),list) or len(raw["observations"])>3
        or any(not isinstance(r,dict) or set(r)!={"evidenceId","claim"} or not all(isinstance(x,str) for x in r.values())
               for r in raw["observations"])):
        return [], "unavailable"
    # Identity and numerical checks use the very same full evidence as the default brief.
    ledger = {"state":brief["state"],"date":brief["day"],"rows":brief["rows"],"relations":brief["rows"],
              "sourceManifest":brief["sources"],"snapshotIdentity":{k:anchor["inputSnapshot"].get(k) for k in ("schemaVersion","createdAt")}}
    verified = relations.optional_interpretations(packet,raw,ledger)
    notes = [{"relation":r["relation"],"claim":r["claim"]} for r in verified if r["claim"] in ("published_closer","opposite_directions")]
    return notes[:1], "selected" if notes else "abstained"


def attach(public_dir, reports, key, budget, *, retained=()):
    anchor = retained[0] if retained else reports.get("en") or next(iter(reports.values()))
    if retained:
        reports = {lang:relations.live._build_fallback_ai_daily_report(public_dir,anchor["date"],anchor["generatedAt"],lang)
                   for lang in reports}
    brief = build(public_dir,anchor["date"],anchor)
    digest = hashlib.sha256(json.dumps(brief,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    for report in reports.values():
        if report["inputSnapshot"]!=anchor["inputSnapshot"] or report["performance"]!=anchor["performance"]:
            raise ValueError("report locale input or verdict mismatch")
    if retained:
        view = anchor["operationsBrief"]
        notes,status = view["selection"],view["advisoryStatus"]
        if any(r["operationsBrief"].get("version")!=VERSION or r["operationsBrief"].get("basisDigest")!=digest
               or r["operationsBrief"].get("selection")!=notes or r["operationsBrief"].get("advisoryStatus")!=status
               or r["inputSnapshot"]!=anchor["inputSnapshot"] for r in retained):
            raise ValueError("partial locale archive: evidence or selection changed")
        if notes!=build(public_dir,anchor["date"],anchor,notes)["optional"]:
            raise ValueError("partial locale archive: selection cannot be verified")
    else:
        before = budget.get("used", 0)
        try:
            notes,status = _select(public_dir,anchor,brief,key,budget)
        except (OSError, HTTPException, ValueError, KeyError, TypeError, RuntimeError, AttributeError, IndexError):
            notes,status = [],"unavailable"
        if status == "unavailable":
            status = "failed" if budget.get("used", 0) > before else "input_unavailable"
    if retained:
        # Repair only missing locales. Never attach today's ETL state to an old issue.
        context = {k:view[k] for k in ("actualStatus","sampleHours","comparisonBasis","hourlyComparison") if k in view}
    else:
        day = brief["day"]
        points = {rid[6:]:r["cells"]["actual"] for rid,r in brief["rows"].items() if rid.startswith("point/")}
        try:
            state = json.loads((public_dir/".etl_state.json").read_bytes())
            ok = state["okDates"]
            finality = ("finalized" if isinstance(ok,list) and day in ok and brief["state"]=="daily_report_full"
                        and len(points)==24 and anchor["dataQuality"]["observedHours"] == 24
                        else "provisional" if isinstance(ok,list) and day not in ok and points else "unknown")
        except (OSError, ValueError, KeyError, TypeError):
            finality = "unknown"
        context = dict(actualStatus=finality, sampleHours=len(points) if brief["state"] in ("daily_report_full","partial") else None,
                       comparisonBasis="retrospective_same_target")
        if (public_dir/"ops/hourly-next"/day).is_dir():
            try:
                from scripts.hourly_delivery import finalized_comparison
                actual = json.loads((public_dir/"actual"/(day+".json")).read_bytes())
                comparison = (finalized_comparison(public_dir, day, actual)
                              if relations.live._fingerprint_json_values(actual)==brief["sources"]["actual"].get("fingerprint") else None)
                if comparison:
                    context["hourlyComparison"] = comparison
            except (ImportError, OSError, TypeError, ValueError, KeyError):
                pass  # Never replace missing proof with the daily Champion score.
    brief["optional"] = notes
    outputs = {}
    for locale,report in reports.items():
        parser=_Contents()
        parser.feed(render(brief,locale))
        parser.close()
        if parser.main or not parser.nodes:raise ValueError("incomplete brief")
        outputs[locale]={**report,"operationsBrief":{"version":VERSION,"language":locale,"date":brief["day"],
            "fingerprint":report["inputSnapshot"]["fingerprint"],"basisDigest":digest,"selection":notes,
            "advisoryStatus":status,"nodes":parser.nodes,**context}}
        result = outputs[locale]
        result["generator"] = {**report["generator"], "provider":"python", "model":None,
            "scope":"deterministicBrief", "promptVersion":"v8-evidence-selection",
            "advisory":{"provider":"openai", "model":MODEL, "status":status,
                        "attempted":None if status=="unavailable" else status in ("selected","abstained","failed")}}
        obsolete = relations.live.MESSAGES[locale]["fallback_note"]
        result["limitations"] = [s for s in report["limitations"] if s != obsolete]
        result["dataQuality"] = {**report["dataQuality"], "limitations":[s for s in report["dataQuality"]["limitations"] if s != obsolete]}
    return outputs
