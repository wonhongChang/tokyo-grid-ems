"""Read paired public first-publication records, not the mutable latest chart."""
import argparse
import json
import math
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from python.forecast.d1_component import APPROVED_TARGETS, ARTIFACT, BASE, JST, interval_role, local_time

def p95(values):
    ordered=sorted(values)
    rank=.95*(len(ordered)-1)
    a,b=math.floor(rank),math.ceil(rank)
    return ordered[a]+(rank-a)*(ordered[b]-ordered[a])

def error_metrics(errors):
    return dict(mae=mean(errors),rmse=math.sqrt(mean(x*x for x in errors)),
                p95=p95(errors),maximum=max(errors))

def summarize(repo, ref, day):
    def git(*args):
        return subprocess.check_output(["git","-C",str(repo),*args])
    rev=git("rev-parse","--verify","--end-of-options",ref+"^{commit}").decode().strip()
    stamp=datetime.fromtimestamp(int(git("show","-s","--format=%ct",rev)),JST)
    state=json.loads(git("show",rev+":.etl_state.json"))
    values={}
    if str(day) in state.get("okDates",[]):
        for p in json.loads(git("show",rev+":actual/"+str(day)+".json")).get("series",[]):
            t=local_time(p["ts"])
            if t.date()!=day or t.hour in values or p.get("actualMw") is None or p.get("actualSource")=="tepco_forecast_fallback" or not math.isfinite(p["actualMw"]):raise ValueError("invalid finalized actual")
            values[t.hour]=p["actualMw"]
    result=dict(date=str(day),asOf=stamp.isoformat(),commit=rev,issues=0,changedPolicyIssues=0,otherIdentity=0,
                actualHours=len(values),firstD1Incumbent=None,sameDayIssues=0,sameDayWrongIdentity=0,
                firstSameDayObservedHours=None,firstSameDayFreezeRisk=None,midnightRevisionUtilityMw=None,
                sameDayNumericCounterfactual=None,revisionUtilityMw=None,activeWriterCounts={},
                frozenD1DifferencesAtFirstD0=None,source="public data commit; not Pages publication time")
    if values:
        result["actualBlob"]=git("rev-parse",rev+":actual/"+str(day)+".json").decode().strip()
    for metric in ("mae","rmse","p95","maximum","coverage"):
        result[metric]=result["reference"+metric[0].upper()+metric[1:]]=None
    first_d0=None
    errors=[];baseline=[];coverage=[];basecoverage=[];runs=[]
    if stamp.date()<day-timedelta(days=1):
        result["state"]="before_issue_window"
        return result
    log=git("log","--since="+str(day-timedelta(days=3))+"T00:00:00+09:00","--first-parent","--reverse","--format=#%ct","--raw","--no-renames","--no-abbrev","--diff-filter=A",rev,"--","forecast_snapshots/"+str(day)).decode()
    for line in log.splitlines():
        if line.startswith("#"):pub=datetime.fromtimestamp(int(line[1:]),JST);continue
        if not line.startswith(":") or pub.date() not in (day-timedelta(days=1),day):continue
        hdr,path=line.split("\t")
        if path.endswith("/index.json"):continue
        q=json.loads(git("cat-file","blob",hdr.split()[3]))
        if local_time(q["generatedAt"])>pub or q.get("targetDate")!=str(day):raise ValueError("invalid issuance")
        key=interval_role(q,BASE)
        if local_time(q["generatedAt"]).date()!=pub.date():continue
        if pub.date()==day:
            result["sameDayIssues"]+=1
            result["sameDayWrongIdentity"]+=int(key!="forecastMw" or bool(q.get("d1PointPolicy"))
                or q.get("model",{}).get("artifactSha256")!=ARTIFACT)
            if first_d0 is None:
                first_d0=q
                n=q.get("observationSummary",{}).get("observedActualHoursAtGeneration")
                result["firstSameDayObservedHours"]=n
                result["firstSameDayFreezeRisk"]=None if n is None else bool(n)
            continue
        if result["firstD1Incumbent"] is None:
            result["firstD1Incumbent"]=key=="forecastMw" and q.get("model",{}).get("artifactSha256")==ARTIFACT
        if q.get("model",{}).get("artifactSha256")!=ARTIFACT or not key:
            result["otherIdentity"]+=1;continue
        result["issues"]+=1; result["changedPolicyIssues"]+=int(key!="forecastMw")
        if [(local_time(p["ts"]).date(),local_time(p["ts"]).hour) for p in q["series"]]!=[(day,h) for h in range(24)]:raise ValueError("incomplete issue")
        if key!="forecastMw":
            writer=q["d1PointPolicy"].get("writer") or "unknown"
            result["activeWriterCounts"][writer]=1+result["activeWriterCounts"].get(writer,0)
            stages=q["forecastBuild"]["series"]
            if len(stages)!=24 or not all(s["ts"]==p["ts"] and
                s["forecastMwByStage"]["incumbent_pre_calibration"]==p[key] and
                s["forecastMwByStage"]["raw_lgbm"]==p["forecastMw"] for s,p in zip(stages,q["series"])):
                raise ValueError("public raw or paired incumbent mismatch")
        if len(values)!=24:continue
        run=[]
        for i,p in enumerate(q["series"]):
            x=p["forecastMw"];r=p[key];a=values[i];diff=x-r
            if not all(math.isfinite(t) for t in (x,r,p["p95LowerMw"],p["p95UpperMw"])):raise ValueError("nonfinite prediction")
            errors.append(abs(x-a));baseline.append(abs(r-a));coverage.append(p["p95LowerMw"]<=a<=p["p95UpperMw"]);basecoverage.append(p["p95LowerMw"]-diff<=a<=p["p95UpperMw"]-diff)
            run.append((x,r))
        runs.append((pub,local_time(q["generatedAt"]),run))
    result["state"]=("routing_mismatch" if result["otherIdentity"] or result["firstD1Incumbent"] is False or result["sameDayWrongIdentity"]
        else "no_issues" if not result["issues"] else "awaiting_finalized_24h" if not errors
        else "no_trial_exposure" if not result["changedPolicyIssues"] else "scored")
    if result["state"]=="scored":
        for name,scores in (("",errors),("reference",baseline)):
            for k,v in error_metrics(scores).items(): result[(name+k[0].upper()+k[1:]) if name else k]=v
        result.update(coverage=mean(coverage),referenceCoverage=mean(basecoverage),pairedIssueHours=len(errors))
        runs.sort(key=lambda v:(v[0],v[1]))
        cutoff=datetime.combine(day-timedelta(days=1),datetime.min.time(),JST).replace(hour=17,minute=30)
        decision=[r for r in runs if r[0]<=cutoff]
        def mae(entries,hrs):
            return [mean(abs(a[j]-values[h]) for _,_,v in entries for h,a in enumerate(v) if h in hrs) for j in (0,1)] if entries else [None,None]
        result["scopes"]={name:dict(zip(("servedMae","referenceMae"),mae(sel,hours))) for name,sel,hours in
            [("first",runs[:1],range(24)),("decision1730",decision[-1:],range(24)),("last",runs[-1:],range(24)),("16to18",runs,range(16,19))]}
        if len(runs)>1:
            result["revisionUtilityMw"]=dict(zip(("served","reference"),[mean(abs(a[j]-values[h])-abs(b[j]-values[h])
                for (_,_,left),(_,_,right) in zip(runs,runs[1:]) for h,(a,b) in enumerate(zip(left,right))) for j in (0,1)]))
        # Only compare the transition to a common D0 when no observed slot was inherited.
        if first_d0 is not None and result["firstSameDayFreezeRisk"] is False:
            d0=first_d0["series"]
            if [local_time(p["ts"]) for p in d0]!=[datetime.combine(day,datetime.min.time(),JST)+timedelta(hours=h) for h in range(24)]:
                raise ValueError("incomplete first same-day")
            result["midnightRevisionUtilityMw"]=dict(zip(("served","reference"),[mean(
                abs(a[j]-values[h])-abs(d0[h]["forecastMw"]-values[h]) for h,a in enumerate(runs[-1][2])) for j in (0,1)]))
        if first_d0 and first_d0.get("preserveObservedForecastHours"):
            frozen=first_d0.get("intervalCalibration",{}).get("preservedObservedHours")
            if isinstance(frozen,list):
                result["frozenD1DifferencesAtFirstD0"]=[h for h in frozen if runs[-1][2][h][0]!=runs[-1][2][h][1]
                    and first_d0["series"][h]["forecastMw"]==runs[-1][2][h][0]]
    return result

def assess(rows):
    alerts=[]
    for row in rows:
        day=row["date"]
        if row["state"] in ("routing_mismatch","no_trial_exposure"):
            alerts.append([day,row["state"]])
        if row["state"]!="scored":continue
        if row["maximum"]-row["referenceMaximum"]>500:alerts.append([day,"maximum +500 MW"])
        if row["referenceCoverage"]-row["coverage"]>.020000000001:alerts.append([day,"coverage -2 percentage points"])
        if row["firstSameDayFreezeRisk"] is not False:alerts.append([day,"first same-day needs review"])
        for k in ("first","last","16to18"):
            s=row["scopes"][k]
            if s["servedMae"]>1.05*s["referenceMae"]:alerts.append([day,k+" MAE +5%"])
        if date.fromisoformat(day).weekday()>=5 and row["mae"]>1.05*row["referenceMae"]:
            alerts.append([day,"nonbusiness MAE +5%"])
    complete=(sorted(r["date"] for r in rows)==list(APPROVED_TARGETS) and all(
        r["state"]=="scored" and r["firstD1Incumbent"] and r["sameDayIssues"] and
        r["scopes"]["decision1730"]["servedMae"] is not None for r in rows))
    paired=None
    if complete:
        paired={k:mean(r[k] for r in rows) for k in ("mae","referenceMae")}
        for k in ("servedMae","referenceMae"):
            paired["decision1730"+k[0].upper()+k[1:]]=mean(r["scopes"]["decision1730"][k] for r in rows)
    writers={w for r in rows for w in r["activeWriterCounts"]}
    ready=complete and not alerts and {"windows-etl","github-intraday"}<=writers
    if not complete:
        recommendation="wait_for_complete_paired_evidence"
    elif alerts or not ready or paired["mae"]>=paired["referenceMae"] or paired["decision1730ServedMae"]>=paired["decision1730ReferenceMae"]:
        recommendation="retain_incumbent_outside_trial"
    else:
        recommendation="review_for_extension_not_automatic_adoption"
    return dict(state="investigate_do_not_expand" if alerts else "manual_release_review" if complete else "incomplete",
                alerts=alerts,equalDateWeight=paired,observedActiveWriters=sorted(writers),
                recommendation=recommendation,automaticPromotion=False)

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repository",type=Path,required=True);ap.add_argument("--ref",required=True)
    ap.add_argument("--assessment",action="store_true")
    ap.add_argument("dates",nargs="+",type=date.fromisoformat)
    args=ap.parse_args()
    rows=[summarize(args.repository,args.ref,d) for d in args.dates]
    print(json.dumps(dict(dates=rows,assessment=assess(rows)) if args.assessment else rows,indent=2,allow_nan=False))
