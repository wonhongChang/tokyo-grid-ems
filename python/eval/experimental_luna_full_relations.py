"""Offline report input. The required relation builder accepts no model response or prompt projection."""

from datetime import datetime, timedelta

from . import ai_daily_report as live
from . import daily_operation_report as daily
from . import experimental_luna_report_scope as common

SCHEMA = "daily-analysis-relations/1"
STAGES = ("raw_lgbm", "same_regime_level_calibrated", "analog_adjusted", "post_holiday_guarded",
          "midday_guarded", "localized_shape_guarded", "pre_calibration", "post_calibration")
finite = common.core._finite


def _hour(day, stamp):
    try:
        t = datetime.fromisoformat(stamp)
        if (t.utcoffset() == timedelta(hours=9) and t.date().isoformat() == day
                and t.minute == t.second == t.microsecond == 0):
            return t.hour
    except (ValueError, TypeError):
        pass
    return None


def _index(day, rows):
    # Ambiguous keys have no usable row; do not silently choose last or nearest.
    out = {}
    for i, row in enumerate(rows):
        hour = _hour(day, row.get("ts"))
        explicit = row.get("hour", hour)
        if hour is None:
            continue
        if type(explicit) is not int or explicit != hour:
            out[hour] = None
            continue
        out[hour] = None if hour in out else (i, row)
    return out


def _sub(a, b):
    return round(a - b, 1) if finite(a) and finite(b) else None


def _winner(p, t, rival="tepco"):
    if p is None or t is None:
        return None
    return "published" if abs(p) < abs(t) else rival if abs(t) < abs(p) else "tie"


def _dir(value):
    return None if value is None else "over" if value > 0 else "under" if value < 0 else "equal"


def build(day, sources, snapshot):
    """Verified report-time evidence. A retained run timestamp is never a publication timestamp."""
    expected = snapshot["sources"]
    if not {"operationReport", "actual", "forecast", "operationalCalibration"} <= expected.keys():
        raise ValueError("missing input manifest")
    if set(sources) - expected.keys():
        raise ValueError("unfingerprinted source")
    for name, meta in expected.items():
        value = sources.get(name)
        digest = live._fingerprint_json_values(value) if value is not None else None
        if meta.get("fingerprint") != digest or meta.get("exists") != (value is not None):
            raise ValueError("source identity mismatch: " + name)
        if value and name != "metrics" and value.get("date") != day:
            raise ValueError("wrong source date: " + name)

    op, actual, forecast, cal = (sources.get(n) or {} for n in
                                 ("operationReport", "actual", "forecast", "operationalCalibration"))
    q = live._data_quality(actual, op, [])
    coverage = live._build_coverage_context(q, None)["finalActualCoverage"]
    state, triples = common.population(day, actual, forecast, op, coverage)
    aidx, fidx = (_index(day, src.get("series", [])) for src in (actual, forecast))
    if any(not aidx.get(h) or not fidx.get(h) for h in triples):
        state, triples = "invalid_hour_identity", {}
    stamp = cal.get("generatedAt")
    try:
        if datetime.fromisoformat(stamp).utcoffset() is None or cal.get("timezone") != "Asia/Tokyo":
            stamp = None
    except (ValueError, TypeError):
        stamp = None
    result = {"schema": SCHEMA, "date":day, "state":state, "sourceManifest":expected,
              "snapshotIdentity":{k:snapshot.get(k) for k in ("schemaVersion","createdAt")},
              "issueTime":{"published":None, "tepco":None, "latestCalibrationGeneratedAt":stamp},
              "relations":{}, "dispositions":{
                  "unverified_causes":"excluded: retrospectively observed association is not causal attribution",
                  "automatic_model_change":"excluded: replay checks are not approval",
                  "assumed_same_issue":"unavailable: a common target is not a common issue time",
                  "all_internal_feature_rows":"source_only: not assigned to mandatory public analysis",
              }}
    rows = result["relations"]

    def add(kind, window, cells, refs, tier="detail", status="available", suffix=""):
        key = f"{kind}/{window}{suffix}"
        if key in rows:
            raise ValueError("ambiguous relation " + key)
        rows[key] = {"kind":kind,"target":window,"cells":cells,"tier":tier,"status":status,"sources":refs}

    def wh(h): return f"{h:02d}:00"

    add("coverage","day",{"observed":coverage.get("observedHours"),"comparable":coverage.get("comparableHours"),
        "fallback":coverage.get("fallbackActualHours"),"snapshotHours":(cal.get("correction") or {}).get("observedHours"),
        "population":state},["actual#/series","operationReport#/summary","operationalCalibration#/correction"],"front")
    if state not in ("daily_report_full","partial") or not triples:
        return result
    summary = op["summary"]
    if state=="daily_report_full":
        add("daily","day",{k:summary.get(k) for k in ("modelMaeMw","tepcoMaeMw","modelWapePct","tepcoWapePct",
            "modelRmseMw","tepcoRmseMw","modelWins","tepcoWins","ties","verdict")}, ["operationReport#/summary"],"front")
    # Use the daily report's 0.1 MW comparison rows before computing peak and shape.
    daily_triples = {h: tuple(round(v, 1) for v in values) for h, values in triples.items()}
    transitions = {r["toHour"]: r for r in daily._shape_transitions([
        {"hour": h, "actualMw": a, "modelForecastMw": p, "tepcoForecastMw": t}
        for h,(a,p,t) in daily_triples.items()])}
    peak = common.peak(daily_triples)
    for h, err in zip(peak["actual"],peak["errorsAtActualPeak"],strict=True):
        add("peak",wh(h),{"actualPeak":peak["maxima"][0],"publishedHours":list(map(wh,peak["published"])),
            "publishedPeak":peak["maxima"][1],"tepcoHours":list(map(wh,peak["tepco"])),"tepcoPeak":peak["maxima"][2],
            "timing":peak["timing"],"error":err,"population":state},["actual#/series","forecast#/series"],"front")
    for i,b in enumerate(op.get("timeBands",[])):
        bounds = common.core._window(b.get("label"))
        if not bounds or sum(bounds[0] <= h <= bounds[1] for h in triples) != b.get("hours"):
            raise ValueError("incompatible daily band")
        add("band",b["label"],{"hours":b["hours"],"bias":b["modelBiasMw"],"modelMaeMw":b["modelMaeMw"],
            "tepcoMaeMw":b["tepcoMaeMw"],"lowerMAE":_winner(b["modelMaeMw"],b["tepcoMaeMw"]),
            "verdict":b["verdict"]},[f"operationReport#/timeBands/{i}"],"front")
    cidx = _index(day,cal.get("hourlyDiagnostics",[])) if cal.get("timezone")=="Asia/Tokyo" else {}
    top = {m["hour"] for m in op.get("topMisses",[])}
    breaks = {(m["fromHour"],m["toHour"]) for m in (op.get("shape") or {}).get("largeShapeBreaks",[])}
    largest = (op.get("shape") or {}).get("largestDeltaMiss") or {}
    if (shape := op.get("shape")):
        add("shape_daily","day",{k:shape.get(k) for k in ("transitionHours","modelDeltaMaeMw","tepcoDeltaMaeMw",
            "maxActualRiseMw","maxActualDropMw","maxModelRiseMw","maxModelDropMw")},["operationReport#/shape"])
    diag=(sources.get("internalDiagnostics") or {}).get("diagnosticSummary") or {}
    for i,band in enumerate(diag.get("weatherDeltaRiskByBand") or []):
        if band.get("assessment") not in ("neutral",None,"") and common.core._window(band.get("label")):
            add("weather",band["label"],{k:band.get(k) for k in ("coolingDelta24hMean","modelBiasMw","assessment")},
                [f"internalDiagnostics#/diagnosticSummary/weatherDeltaRiskByBand/{i}"])
    regime=diag.get("dayLevelRegime") or {}
    if regime.get("flags"):
        add("regime","day",{k:regime.get(k) for k in ("flags","lag24OverheatMeanMw","tempDelta24hMeanC")},
            ["internalDiagnostics#/diagnosticSummary/dayLevelRegime"])
    for event in live._calibration_hypotheses(cal,0,live.MESSAGES["en"]):
        flag,measure=event["evidence"]
        add("control","day",{"flag":flag["metric"],"measure":measure["metric"],"value":measure.get("value"),
            "unit":measure.get("unit"),"run":stamp},["operationalCalibration#/correction"],suffix="/"+flag["metric"])
    history=sources.get("operationalCalibrationHistory")
    for event in live._calibration_history_hypotheses(history,0,live.MESSAGES["en"]):
        data={v["metric"]:v.get("value") for v in event["evidence"]}
        data["appliedRuns"]=sum(bool(i.get("applied") or i.get("appliedRegimeReason")) for i in history["snapshots"])
        add("history","day",data,["operationalCalibrationHistory#/snapshots"])
    for h,(a,p,t) in sorted(triples.items()):
        target=wh(h)
        ap,fp = f"actual#/series/{aidx[h][0]}", f"forecast#/series/{fidx[h][0]}"
        pe,te = _sub(p,a),_sub(t,a)
        point = {"actual":a,"published":p,"tepco":t,"error":pe,"direction":_dir(pe),"tepcoError":te,
                 "tepcoDirection":_dir(te),"closer":_winner(pe,te)}
        add("point",target,point,[ap,fp],"front" if h in top else "detail")
        matched = cidx.get(h) if stamp else None
        row=matched[1] if matched else {}
        cp=f"operationalCalibration#/hourlyDiagnostics/{matched[0]}" if matched else "operationalCalibration#/hourlyDiagnostics"
        nested=row.get("forecastMwByStage") or {}
        values={}
        for stage in STAGES:
            v=nested.get(stage)
            field={"pre_calibration":"preCalibrationForecastMw","post_calibration":"postCalibrationForecastMw"}.get(stage)
            other=row.get(field) if field else None
            if finite(v) and finite(other) and v!=other:
                raise ValueError(f"conflicting retained stage: {target} {stage}")
            values[stage]=v if finite(v) else other if finite(other) else None
        known=[v for v in values.values() if v is not None]
        status="available" if all(values[k] is not None for k in ("raw_lgbm","pre_calibration","post_calibration")) else (
            "partial" if known else "unavailable")
        add("stages",target,{"run":stamp if matched else None,**values,"actual":a,
            "rawError":_sub(values["raw_lgbm"],a),"preError":_sub(values["pre_calibration"],a),
            "postError":_sub(values["post_calibration"],a),"snapshotActual":row.get("actualMw"),
            "snapshotSource":row.get("actualSource"),"snapshotSlope":row.get("sameDayActualSlopeMw")},[ap,cp],"detail",status)
        late=values["post_calibration"]
        basis="post_calibration" if late is not None else "pre_calibration" if values["pre_calibration"] is not None else None
        late=values.get(basis)
        gap,le=_sub(p,late),_sub(late,a)
        flagged=gap is not None and abs(gap)>=live.FREEZE_GAP_THRESHOLD_MW
        add("vintage",target,{"actual":a,"published":p,"latest":late,"basis":basis,"run":stamp if matched else None,
            "gap":gap,"error":pe,"latestError":le,"closer":_winner(pe,le,"latest")},
            [ap,fp,cp],"detail","available" if late is not None else "unavailable")
        if flagged and state=="daily_report_full":
            add("check",target,{"procedure":"replay_vintage","compare":"paired_release_errors",
                "condition":"verified_gap","asOf":"issue_required"},[ap,fp,cp],suffix="/vintage")
        ticket_events=[]
        if state=="daily_report_full" and abs(pe)>=live.PRIORITY_EVENT_LARGE_ERROR_MW:
            add("check",target,{"procedure":"replay_stages","compare":"original_and_retained",
                "condition":"large_point","asOf":"issue_required"},[ap,fp,cp],"front",suffix="/point")
            ticket_events.append(("point",{"id":f"top_miss_h{h}","hour":h,"modelErrorMw":pe,
                                  "modelErrorDirection":"overprediction" if pe>0 else "underprediction"}))
        if h in transitions:
            tr = transitions[h]
            da,dp,dt=(tr[k] for k in ("actualDeltaMw","modelDeltaMw","tepcoDeltaMw"))
            err,terr=tr["modelDeltaErrorMw"],tr["tepcoDeltaErrorMw"]
            start=wh(h-1)+"→"+target
            shape_refs=[ap,fp,f"actual#/series/{aidx[h-1][0]}",f"forecast#/series/{fidx[h-1][0]}"]
            add("change",start,{"actualDelta":da,"publishedDelta":dp,"tepcoDelta":dt,"deltaError":err,
                "tepcoDeltaError":terr,"closer":_winner(err,terr)},shape_refs,
                "front" if (h-1,h)==(largest.get("fromHour"),largest.get("toHour")) else "detail")
            if state=="daily_report_full" and (h-1,h) in breaks:
                ticket_events.append(("shape",{"id":f"shape_break_{h-1}_{h}","hour":h,"eventType":"shape_break"}))
        for event_kind,event in ticket_events:
            if summary.get("verdict") in ("close","insufficient",None):
                continue
            ticket=live._recommended_ticket_for_event(event,row)
            if ticket:
                add("experiment",target,{"trigger":event_kind,"feature":ticket["target"],
                    "eligibility":("evening_intersection" if ticket["target"].endswith("evening_decline_continuity_guard")
                                   else "morning_hypothesis" if ticket["target"]=="lag_24h_hourly_delta" else "midday_hypothesis"),
                    "window":ticket["testWindowJst"],"metrics":ticket["acceptanceMetrics"],
                    "protocol":"matched_replay","asOf":"issue_required"},[ap,fp,cp],
                    "detail",suffix="/"+event_kind)
    return result


def optional_interpretations(packet, raw, result):
    """Only this path sees the LLM projection. Recheck its numbers against the full relation."""
    if (not isinstance(raw, dict) or not isinstance(raw.get("observations"),list) or
            not all(isinstance(i,dict) for i in raw["observations"]) or not isinstance(packet,dict)
            or result["state"] != "daily_report_full" or packet.get("date") != result["date"]
            or packet.get("inputSnapshot") != live._compact_input_snapshot_for_prompt({
                **result["snapshotIdentity"],"sources":result["sourceManifest"]})):
        return []
    refs=common.core.refs
    try:
        evidence=refs.evidence(packet)
        claims,_=refs.choose(raw,evidence)
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    output=[]
    for key,claim in claims.items():
        r=evidence[key]
        if claim not in refs.COMPARISONS:
            continue
        target=f'{r["fromHourJst"]:02d}:00'
        if r["kind"]=="shape":
            ref="change/"+target+f'→{r["toHourJst"]:02d}:00'
            c=result["relations"].get(ref,{}).get("cells",{})
            if (r["actualChange"],r["publishedChange"])!=(c.get("actualDelta"),c.get("publishedDelta")):continue
            if claim=="same_direction" and r["actualChange"]*r["publishedChange"]<=0:continue
        elif r["kind"]=="vintage":
            ref="vintage/"+target
            c=result["relations"].get(ref,{}).get("cells",{})
            if (r["publishedMinusActual"],r["recalculatedMinusActual"],r["publishedMinusRecalculated"],r["recalculatedBasis"]) != (
                    c.get("error"),c.get("latestError"),c.get("gap"),c.get("basis")):continue
        else:continue
        output.append({"relation":ref,"evidenceId":key,"claim":claim,"copy":common.core._remark(r,claim)})
    return output
