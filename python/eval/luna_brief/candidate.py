"""Unpublished reporting adapter. Only frozen public inputs are read; no clients or serving hooks."""
from datetime import date,timedelta
from math import isfinite
from pathlib import Path
from statistics import median
import json

from python.eval import experimental_luna_full_relations as relations


def load(p):
    return json.loads(p.read_bytes())


def read_public(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root) or p.suffix != ".json":
        raise ValueError("invalid public input reference")
    return load(p)


def intervals(day, forecast, points):
    """Denominator is specific to each pair of published bounds, never the daily MAE count."""
    out = {}
    indexed = relations._index(day, forecast.get("series", []))
    for level in (95, 99):
        widths, outside, exceptions = [], [], []
        for h, (_, row) in indexed.items():
            target = f"{h:02d}:00"
            if target not in points:
                continue
            lo, hi = (row.get(f"p{level}{key}Mw") for key in ("Lower", "Upper"))
            if not all(type(x) in (int, float) and isfinite(x) for x in (lo, hi)) or lo > hi:
                continue
            actual = points[target]["actual"]
            widths.append((hi - lo) / 2)
            if not lo <= actual <= hi:
                outside.append(target)
                exceptions.append(dict(target=target,actual=actual,lower=lo,upper=hi,side="above" if actual>hi else "below"))
        out[str(level)] = dict(n=len(widths), inside=len(widths)-len(outside) if widths else None,
                               medianHalfWidth=round(median(widths), 1) if widths else None,
                               outside=sorted(outside), exceptions=sorted(exceptions,key=lambda r:r["target"]),
                               excluded=len(points)-len(widths))
    return out


def build(root, day, archived, optional=()):
    date.fromisoformat(day)
    root = Path(root).resolve()
    if archived["date"] != day:
        raise ValueError("archive date mismatch")
    fb = relations.live._build_fallback_ai_daily_report(root, day, archived["generatedAt"], "en")
    if fb["inputSnapshot"] != archived["inputSnapshot"] or fb["performance"] != archived["performance"]:
        raise ValueError("archive input identity or deterministic verdict mismatch")
    src = {k:read_public(root,v) for k,v in fb["inputRefs"].items() if v}
    ledger = relations.build(day, src, fb["inputSnapshot"])
    ctx = fb.get("diagnosticContext") or {}
    rows = ledger["relations"]
    def cells(kind):
        return {r["target"]:r["cells"] for r in rows.values() if r["kind"] == kind}
    points, bands = cells("point"), cells("band")
    peaks = {h:dict(c, maxDifference=round(c["publishedPeak"]-c["actualPeak"],1),
                    forecastAtPeak=points[h]["published"],
                    forecastDropFromPeak=round(c["publishedPeak"]-points[h]["published"],1))
             for h,c in cells("peak").items()}
    ranked = sorted(points,key=lambda h:(-abs(points[h]["error"]),h))[:3]
    full = ledger["state"] == "daily_report_full"
    rolling = ctx.get("rollingPatternContext") or {}
    history = []
    if full and rolling.get("targetDate") == day and (repeats:=rolling.get("sameBandRepeatedMisses")):
        left,right = (rolling.get("dateRange") or {}).get("from"), (rolling.get("dateRange") or {}).get("to")
        for r in repeats:
            band = r["label"]
            if band not in bands or not left or right != day:
                continue
            direction = r["dominantDirection"]
            if relations.live._band_direction(bands[band]["bias"]) != direction:
                continue
            per_day = {}
            for p in sorted((root/"reports/daily").glob("????-??-??.json")):
                if not left <= p.stem <= day:
                    continue
                hist = load(p)
                b = next((i for i in hist.get("timeBands",[]) if i["label"]==band),{})
                if hist.get("date")==p.stem and isinstance(b.get("modelBiasMw"),(int,float)):
                    per_day[p.stem] = b["modelBiasMw"]
            if len(per_day)!=r["days"] or sum(relations.live._band_direction(v)==direction for v in per_day.values())!=r["sameDirectionMissDays"]:
                continue
            history.append(dict(band=band, direction=direction, count=r["sameDirectionMissDays"],
                                n=r["days"], mean=r["meanModelBiasMw"], days=per_day))
    ranking = history[0] if history else None
    iv = intervals(day,src.get("forecast") or {},points)
    checks = [r for r in rows.values() if r["kind"]=="check" and r["cells"]["condition"]=="large_point"]
    revision_targets=sorted({r["target"] for r in rows.values() if r["kind"]=="check" and r["cells"]["condition"]=="verified_gap"})
    day_result = cells("daily").get("day",{})
    status = day_result.get("verdict")
    # Research is about an observed phenotype, never an instruction to change a named feature.
    window = None
    if full and status not in (None,"close","insufficient") and (checks or ranking):
        window = ranking["band"] if ranking else next((b for b in bands if int(b[:2])<=int(ranked[0][:2])<=int(b[-2:])),None)
    action = ("coverage" if not full else "bounds" if iv["95"]["outside"] else "history" if ranking and status!="close"
              else "issue" if checks else "band_data" if iv["95"]["excluded"] else "none")
    diag = src.get("internalDiagnostics") or {}
    eligible = {}
    for row in diag.get("rows") or []:
        h = row.get("hour")
        if type(h) is not int or not 0<=h<=23 or f"{h:02d}:00" not in points:
            continue
        non = (row.get("calendarFeatures") or {}).get("is_non_business_day")
        lag = (row.get("lagFeatures") or {}).get("business_midday_x_lag_24h_delta")
        eligible[f"{h:02d}:00"] = dict(nonbusiness=non, value=lag,
            mask=(not bool(non) and 11<=h<=13) if non in (0,1) else None)
    history_index=src.get("operationalCalibrationHistory") or {}
    entries=history_index.get("snapshots") or []
    base=root/"reports/internal/operational-calibration/snapshots"/day
    bodies=0
    for entry in entries:
        name=entry.get("path") or ""
        p=(root/name).resolve()
        if p.parent==base and p.suffix==".json" and p.is_file():
            snapshot=load(p)
            bodies+=int(snapshot.get("date")==day and snapshot.get("generatedAt")==entry.get("generatedAt"))
    highlights = []
    for item in optional:
        ref,claim = item.get("relation"),item.get("claim")
        c=rows.get(ref,{}).get("cells",{})
        if full and ((claim=="published_closer" and str(ref).startswith("vintage/") and c.get("closer")=="published")
                     or (claim=="opposite_directions" and str(ref).startswith("change/") and
                         c.get("actualDelta",0)*c.get("publishedDelta",0)<0)):
            highlights.append({"relation":ref,"claim":claim})
    # Prior published top misses are a bounded, selective search, not a denominator for recurrence.
    contrast=None
    if window and ranked:
        target=ranked[0];cur=points[target]["error"]
        for back in range(1,7):
            prev=str(date.fromisoformat(day)-timedelta(days=back));p=root/f"reports/daily/{prev}.json"
            if not p.is_file():continue
            report=load(p)
            if (report.get("date")!=prev or report.get("availability")!="ok" or report.get("timezone")!="Asia/Tokyo"
                or (report.get("summary") or {}).get("comparableHours")!=24):continue
            hit=next((r for r in report.get("topMisses",[]) if r.get("hour")==int(target[:2])
                      and type(r.get("modelErrorMw")) in (int,float) and r["modelErrorMw"]*cur<0),None)
            if hit:
                contrast=dict(target=target,priorDate=prev,priorError=hit["modelErrorMw"],currentError=cur)
                break
    served={k:v for k,v in rows.items() if v["kind"]!="experiment"}
    return dict(schema="daily-brief/1",day=day,state=ledger["state"],rows=served,peaks=peaks,ranked=ranked,contrast=contrast,
                omitted={"prescriptiveFeatureTickets":"no confirmed original-issue application; replaced with a matched replay question"},
                history=history,intervals=iv,action=action,window=window,revisionTargets=revision_targets,eligibility=eligible,
                optional=highlights[:1],coverage=cells("coverage")["day"],daily=day_result,
                reportTime=archived["generatedAt"],sourceTimes={k:(src.get(k) or {}).get("generatedAt")
                for k in ("actual","forecast","operationalCalibration")},policy=(src.get("forecast") or {}).get("servingPolicyFingerprint"),
                retained=dict(indexed=len(entries) if history_index else None,bodies=bodies if history_index else None),
                issue=ledger["issueTime"],sources=fb["inputSnapshot"]["sources"])
