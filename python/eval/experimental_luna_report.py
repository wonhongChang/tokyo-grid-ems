"""Offline-only public report candidate. No production entry point or API calls."""
from copy import deepcopy
import math
import re

from . import ai_daily_report as live

NUMBER = r"([+-]?\d[\d,]*(?:\.\d+)?)"
HOUR = r"(\d{1,2}):00"
SIGNED_POINT = re.compile(
    rf"At {HOUR},? the (?:published forecast|model) (overpredicted|underpredicted) by {NUMBER} MW", re.I
)
SHAPE = re.compile(
    rf"Actual demand (rose|fell) {NUMBER} MW from {HOUR} to {HOUR}(?: JST)?,? "
    rf"(?:and|while) the (?:published|model) forecast (rose|fell) {NUMBER} MW", re.I
)
CROSS_VINTAGE = re.compile(
    rf"At {HOUR},? the (?:latest )?recalculated (?:forecast|line)(?: itself)? was {NUMBER} MW (above|below) actual,? "
    rf"while the published (?:forecast|line) was {NUMBER} MW (above|below) actual", re.I
)
PUBLISHED_FIRST = re.compile(
    rf"At {HOUR},? the published (?:forecast|line) was {NUMBER} MW (above|below) actual,? "
    rf"while the (?:latest )?recalculated (?:forecast|line) was {NUMBER} MW (above|below) actual", re.I
)
END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

EXPERIMENTAL_GUIDANCE = """
For this QA run, evidence validation will preserve entire standalone sentences from
hypothesis explanations. Do not combine different hours or different bases in an
ambiguous number. Tie each card to exact sourceEventIds. Use these sentence forms
where applicable, without markdown, always using real values from the packet:
- At HH:00, the published forecast overpredicted by VALUE MW.
  Use underpredicted instead if negative; express VALUE as a positive magnitude.
- Actual demand rose VALUE MW from HH:00 to HH:00, while the published forecast
  fell VALUE MW. Use rose or fell correctly and use analysisPriorities.events
  for shape direction and the exact interval.
- At HH:00, the published forecast was VALUE MW below actual, while the latest
  recalculated forecast was VALUE MW above actual. Independently use above/below
  as supported. Both must be errors against the same finalized actual.
Keep distinct grounded findings as separate cards, not duplicate cards for a
single relationship. Explain uncertainty separately; a difference in vintages
does not prove a freeze cause. Do not treat a hypothetical replay as a deployment
instruction. An empty event list can mean no actionable event: return no hypotheses
or recommendations in that case. These formats do not override the numeric evidence.
"""


def _number(value):
    return float(value.replace(",", ""))


def _direction(value, word, positive):
    magnitude = _number(value)
    if not math.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("expected positive magnitude")
    return magnitude if word.lower() == positive else -magnitude


def _eq(a, b):
    return type(b) in (int, float) and math.isclose(a, b, rel_tol=0, abs_tol=1e-6)


def _source_ids(hypothesis, events):
    ids = hypothesis.get("sourceEventIds") or []
    return [i for i in ids if isinstance(i, str) and i in events]


def _review_plan(text, hours):
    if not isinstance(text,str):
        return None
    m=re.fullmatch(
        r"Replay (\d{2}):00-(\d{2}):00 JST and compare (?:raw_lgbm and published|published and raw_lgbm)"
        r" slopes across (\d{2}):00-(\d{2}):00 with ([a-zA-Z_0-9 ,.-]+)\.",text)
    if not m:
        return None
    start,end,a,b=map(int,m.groups()[:4])
    refs=re.split(r",\s*|\s+and\s+",m[5].replace(", and ",", "))
    permitted={"lag_24h hourly delta","recent_same_business_type_delta","morningLagDeltaExcessMw",
               "lag24BusinessTypeMismatch","morning causeTags"}
    if start<=a<b<=end<24 and {a,b}==hours and refs and set(refs)<=permitted:
        return text
    return None


def _observations(packet):
    priorities = (packet.get("analysisPriorities") or {}).get("events") or []
    events = {x["id"]:x for x in priorities if isinstance(x.get("id"), str)}
    rows = {x.get("hour"):x for x in packet.get("focusedRows", [])}
    final = packet.get("errorSignConvention") or {}
    if final.get("modelErrorMw")!="modelForecastMw - actualMw":
        return events, {}
    facts = {}
    for event_id,e in events.items():
        hour=e.get("hour")
        r=rows.get(hour) or {}
        if e.get("eventType")=="large_absolute_error":
            error=e.get("modelErrorMw")
            if (type(error) in (int,float) and error and r.get("actualSource")=="observed"
                    and all(type(r.get(k)) in (int,float) for k in ("actualMw","publishedForecastMw"))
                    and _eq(error,r.get("modelErrorMw")) and _eq(error,r["publishedForecastMw"]-r["actualMw"])):
                facts[event_id]=("point", hour, error)
        elif e.get("eventType")=="shape_break":
            a,b=e.get("fromHour"),e.get("toHour")
            x,y=rows.get(a,{}),rows.get(b,{})
            if (type(a) is int and type(b) is int and b==a+1
                    and x.get("actualSource")==y.get("actualSource")=="observed"
                    and all(type(z.get(k)) in (int,float) for z in (x,y) for k in ("actualMw","publishedForecastMw"))):
                actual=y["actualMw"]-x["actualMw"]
                published=y["publishedForecastMw"]-x["publishedForecastMw"]
                if actual and published and _eq(actual,e.get("actualDeltaMw")) and _eq(published,e.get("modelDeltaMw")):
                    facts[event_id]=("shape",a,b,round(actual,1),round(published,1))
        elif e.get("eventType")=="published_recalculated_gap":
            keys=("publishedForecastMw","latestRecalculatedForecastMw","freezeGapMw")
            if (r.get("actualSource")=="observed" and type(r.get("actualMw")) in (int,float)
                    and all(type(e.get(k)) in (int,float) for k in keys)
                    and _eq(e[keys[0]],r.get(keys[0])) and _eq(e[keys[0]]-e[keys[1]],e[keys[2]])):
                # Final actual is identical for both values, but the vintages are not.
                act=r["actualMw"]
                pub,recalc=round(e[keys[0]]-act,1),round(e[keys[1]]-act,1)
                if pub and recalc:
                    facts[event_id]=("vintage",hour,pub,recalc,e[keys[2]])
    return events,facts


def verified_sentence(sentence, choices):
    """Return matched event IDs. Reject unparsed text rather than infer its semantics."""
    sentence=sentence.strip().rstrip(".")
    clauses=[]
    if m:=SIGNED_POINT.fullmatch(sentence):
        h,sign,num=m.groups()
        clauses=[("point",int(h),_direction(num,sign,"overpredicted"))]
    elif m:=SHAPE.fullmatch(sentence):
        da,a,h1,h2,dp,p=m.groups()
        clauses=[("shape",int(h1),int(h2),_direction(a,da,"rose"),_direction(p,dp,"rose"))]
    elif m:=CROSS_VINTAGE.fullmatch(sentence):
        h,r,dr,p,dp=m.groups()
        clauses=[("vintage",int(h),_direction(p,dp,"above"),_direction(r,dr,"above"))]
    elif m:=PUBLISHED_FIRST.fullmatch(sentence):
        h,p,dp,r,dr=m.groups()
        clauses=[("vintage",int(h),_direction(p,dp,"above"),_direction(r,dr,"above"))]
    elif ", while " in sentence:
        head,tail=sentence.split(", while ",1)
        a=verified_sentence(head,choices)
        b=verified_sentence(tail,choices)
        return a+b if a and b else []
    else:
        return []
    def same(a,b):
        return a[0]==b[0] and all(x==y or _eq(x,y) for x,y in zip(a[1:],b[1:]))
    return [k for k,v in choices.items() if any(same(c,v) for c in clauses)]


def _safe_sentences(text, choices):
    if not isinstance(text,str):
        return
    for line in END.split(text.strip()):
        # A counterexample can have a valid first clause and an unverified interpretation.
        first=line.split(";",1)[0].strip().rstrip(".")
        try:
            ids=verified_sentence(first,choices)
        except ValueError:
            continue
        if ids:
            yield first+".",ids


def _event_fallback(kind, numbers):
    if kind=="point":
        h,e=numbers
        return f"At {h:02d}:00, the published forecast {'overpredicted' if e>0 else 'underpredicted'} by {abs(e):,.1f} MW."
    if kind=="shape":
        h,j,a,p=numbers
        return (f"Actual demand {'rose' if a>0 else 'fell'} {abs(a):,.1f} MW from {h:02d}:00 to {j:02d}:00, "
                f"while the published forecast {'rose' if p>0 else 'fell'} {abs(p):,.1f} MW.")
    h,p,r,_=numbers
    return (f"At {h:02d}:00, the published forecast was {abs(p):,.1f} MW {'above' if p>0 else 'below'} actual, "
            f"while the latest recalculated forecast was {abs(r):,.1f} MW {'above' if r>0 else 'below'} actual.")


def _evidence(event_id,fact,events):
    kind,*v=fact
    metrics={"point":("modelErrorMw",),"shape":("actualDeltaMw","modelDeltaMw"),
             "vintage":("publishedErrorMw","recalculatedErrorMw","publishedVsLatestRecalculatedGapMw")}[kind]
    hour=v[1] if kind=="shape" else v[0]
    return [{"source":"analysisPriorities" if kind=="shape" else "eventEvidenceBundles",
             "metric":m,"value":n,"unit":"MW","hour":hour,"timeBand":events[event_id].get("timeBand")}
            for m,n in zip(metrics,v[-len(metrics):])]


def _candidate_tickets(packet, events, cards, structured):
    candidates={(t.get("eventId"),t.get("target")) for t in packet.get("recommendationTicketCandidates", [])}
    by_id={c["id"]:c for c in cards}
    tickets=[]
    for suggestion in structured.get("featureRecommendations",[]):
        if suggestion.get("autoApply") is not False:
            continue
        target=suggestion.get("target")
        source_ids={e for h in suggestion.get("linkedHypotheses",[]) if h in by_id for e in by_id[h]["sourceEventIds"]}
        source_ids.update(e for e,t in candidates if t==target and e in events)
        card=next((c for c in cards if set(c["sourceEventIds"])&source_ids),None)
        if card is None:
            continue
        vintage=target=="serving.published_forecast_freeze" and any(
            events[e].get("eventType")=="published_recalculated_gap" for e in card["sourceEventIds"])
        support=next((t for t in packet.get("recommendationTicketCandidates",[])
                      if t["target"]==target and t["eventId"] in card["sourceEventIds"]),None)
        if (not vintage and not support) or any(t["target"]==target for t in tickets):
            continue
        if vintage:
            todo="Replay identical target hours by issue time and compare the published forecast with the recalculated forecast."
            risk="A later recalculation can be less accurate and may have been unavailable at publication time."
            plan="Keep finalized actuals fixed. Report both absolute errors and the vintage gap separately; check opposite-sign cases."
        else:
            todo=f"Compare issue-time inputs and same-run stages for {support['testWindowJst']} JST in a replay."
            risk=support["failureMode"]
            plan="Compare "+", ".join(support["acceptanceMetrics"])+" on the affected and opposite-direction cases."
        tickets.append(dict(id=f"review.{target}",priority="medium",type=suggestion["type"],target=target,
            suggestion=todo,expectedEffect="Distinguish the observed pattern from a cause before any tuning.",
            risk=risk,validationPlan=plan,linkedHypotheses=[card["id"]],autoApply=False))
    return tickets[:2]


def merge(fallback, structured, packet):
    """Keep business facts/decision, preserve independently verified prose only."""
    result=deepcopy(fallback)
    fixed=live._deterministic_executive_summary_copy(result)
    if fixed is not None:
        result["executiveSummary"]=fixed
    events,facts=_observations(packet)
    result["rootCauseHypotheses"]=[]
    result["featureRecommendations"]=[]
    result["generator"]={**result["generator"],"provider":"openai","model":"gpt-6-luna",
                         "localizationStatus":"not_requested"}
    coverage=packet.get("coverageContext") or {}
    fin=(coverage.get("finalActualCoverage") or {}).get("observedHours")
    snap=(coverage.get("intradayCalibrationCoverage") or {}).get("observedHours")
    result["operatorNotes"]=[]
    if type(fin) is int:
        result["operatorNotes"].append(f"Finalized performance uses {fin} observed hours.")
    if type(snap) is int:
        result["operatorNotes"].append(f"The retained calibration snapshot has {snap} observed hours; it is not the daily performance population.")
    result["limitations"]=["Observed differences do not establish a root cause. Later recalculations are not the original published forecasts."]
    result["dataQuality"]["limitations"]=result["limitations"]
    accepted=[];seen=set();cards=[]
    for h in structured.get("rootCauseHypotheses",[]):
        linked={i:facts[i] for i in _source_ids(h,events) if i in facts}
        # Legacy A contains a standalone safe clause in counterEvidence.
        for text in [h.get("explanation"),*(h.get("counterEvidence") or [])]:
            for sentence,ids in _safe_sentences(text,linked):
                new=[i for i in ids if i not in seen]
                if not new:
                    continue
                if ids!=new:
                    continue
                seen.update(new);accepted.append((sentence,new,h.get("nextCheck")))
    # Prefer different kinds over several near-identical cards for neighboring hours.
    distinct=set()
    paired=[(s,i,"model",check) for s,i,check in accepted]
    paired += [(_event_fallback(f[0],f[1:]),[k],"rules",None) for k,f in facts.items() if k not in seen]
    for sentence,ids,origin,replay in paired:
        kinds={facts[i][0] for i in ids}
        if kinds<=distinct or len(cards)>=3:
            continue
        distinct.update(kinds)
        title={"shape":"Published-forecast shape difference","vintage":"Published forecast versus later recalculation",
               "point":"Largest verified point error"}
        primary=next(k for k in ("shape","vintage","point") if k in kinds)
        scope={"shape":"The directional comparison is observed. Which model or correction stage introduced it is unverified.",
               "vintage":"This is a difference between forecast vintages against the same finalized actual, not a causal attribution.",
               "point":"The point error is observed. Its source within the forecasting pipeline is unverified."}
        step={"shape":"Compare raw, pre-calibration and post-calibration slopes for the same issue and target hours.",
              "vintage":"Compare issue time, publication history and same-run stages before recommending a policy change.",
              "point":"Replay the missed hour and a counterexample; compare same-run stages before tuning."}
        hours={n for i in ids for n in (facts[i][1:3] if facts[i][0]=="shape" else facts[i][1:2])}
        cards.append(dict(id=f"review.{ids[0]}",title=title[primary],explanation=sentence,
            mechanism=scope[primary],nextCheck=_review_plan(replay,hours) or step[primary],counterEvidence=[],relatedHours=sorted(hours),
            relatedTimeBands=sorted({events[i]["timeBand"] for i in ids if events[i].get("timeBand")}),
            relatedFeatures=[],sourceEventIds=ids,severity=events[ids[0]]["severity"],
            confidence="medium",evidenceStatus="partial",
            evidence=[e for i in ids for e in _evidence(i,facts[i],events)]))
        if origin=="model" and len(cards)==1:
            result["executiveSummary"]["summary"] += " "+sentence
    result["rootCauseHypotheses"]=cards
    result["featureRecommendations"]=_candidate_tickets(packet,events,cards,structured)
    if not events:
        assert not cards and not result["featureRecommendations"]
    return result, {"events":list(events),"verifiableEvents":list(facts),
                    "retained": [{"text":s,"events":i} for s,i,_ in accepted
                                 if any(c["explanation"]==s for c in cards)]}


def translatable(doc):
    """Return stable pointers only to human-readable leaves, never evidence or decisions."""
    paths=[]
    for field in ("headline","summary"):
        paths.append(("executiveSummary",field))
    for table,fields in (("rootCauseHypotheses",("title","explanation","mechanism","nextCheck")),
                         ("featureRecommendations",("suggestion","expectedEffect","risk","validationPlan"))):
        for index,_ in enumerate(doc[table]):
            paths.extend((table,index,f) for f in fields)
    for key in ("operatorNotes","limitations"):
        paths.extend((key,i) for i,_ in enumerate(doc[key]))
    return paths


def _get(doc,path):
    for step in path:doc=doc[step]
    return doc


def localization_slots(doc):
    return {f"s{i}":{"field":".".join(map(str,path)),"en":_get(doc,path)}
            for i,path in enumerate(translatable(doc))}


def localize(doc, locale, translated):
    """Validate shape, numeric anchors, and language; never replace structured facts."""
    from collections import Counter
    from decimal import Decimal
    import unicodedata
    slots=localization_slots(doc)
    if translated.keys()!=slots.keys():
        raise ValueError("missing or extra translation slot")
    result=deepcopy(doc)
    no_digits=re.compile(r"[\uac00-\ud7a3]" if locale=="ko" else r"[\u3041-\u30ff]")
    for i,path in enumerate(translatable(doc)):
        key=f"s{i}";src=slots[key]["en"];target=translated[key]
        text=unicodedata.normalize("NFKC",target).replace("\u2212","-")
        def numbers(x):
            ranges=re.sub(r"(?<=\d)[-–~〜](?=\d)"," ",x)
            return Counter(Decimal(v.replace(",","")) for v in re.findall(NUMBER,ranges))
        if (not text.strip() or "\ufffd" in text or not no_digits.search(text) or numbers(src)!=numbers(text)):
            raise ValueError(f"invalid localized slot {locale}/{key}")
        _get(result,path[:-1])[path[-1]]=target
    result["language"]=result["contentLanguage"]=locale
    result["dataQuality"]["limitations"]=result["limitations"]
    result["generator"].update(localizationStatus="ok",localizationModel="gpt-6-luna")
    return result
