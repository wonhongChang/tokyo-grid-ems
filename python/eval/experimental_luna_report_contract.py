"""Offline report candidate: required facts, optional interpretations, conditional replay."""

from copy import deepcopy
from decimal import Decimal
import math
import re

from . import experimental_luna_evidence_refs as refs
from .experimental_luna_report_copy import METRICS, REPLAY, SENTENCES, TERMS

LOCALES = ("en", "ko", "ja")
CORE_STAGES = ("raw_lgbm", "pre_calibration", "post_calibration")
RUN_STAGES = ("raw_lgbm", "analog_adjusted", "pre_calibration", "post_calibration")


def _text(key, **kwargs):
    return {loc: fmt.format(**{k: v[loc] if isinstance(v, dict) else v for k, v in kwargs.items()})
            for loc, fmt in zip(LOCALES, SENTENCES[key])}


def _join(items, joiners):
    return {loc: sep.join(item[loc] for item in items) for loc, sep in zip(LOCALES, joiners)}


def _names(keys, lookup):
    return _join([dict(zip(LOCALES, lookup[k])) for k in keys], (", ", "·", "・"))


def _hour(hour):
    return type(hour) is int and 0 <= hour < 24


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _window(s, timed=False):
    match = re.fullmatch(r"(\d{2}):00-(\d{2}):00" if timed else r"(\d{2})-(\d{2})", s or "")
    if match:
        a, b = map(int, match.groups())
        if _hour(a) and _hour(b) and a <= b:
            return a, b
    return None


def _fmt_window(a, b):
    return f"{a:02d}:00-{b:02d}:00 JST"


def _full_final(coverage):
    return (coverage.get("scope") == "final_daily_actuals_for_performance"
            and coverage.get("comparableHours") == coverage.get("observedHours") == 24
            and coverage.get("fallbackActualHours") == 0)


def _time_bands(operation, coverage, signs):
    if not _full_final(coverage) or signs.get("modelBiasMw") != "mean(modelForecastMw - actualMw)":
        return []
    candidates = []
    occupied = set()
    for band in operation.get("timeBands") or []:
        bounds = _window(band.get("label"))
        n, bias, mae = (band.get(k) for k in ("hours", "modelBiasMw", "modelMaeMw"))
        if not bounds or not _finite(bias) or not _finite(mae) or abs(bias) > mae:
            continue
        a, b = bounds
        hours = set(range(a, b + 1))
        if type(n) is not int or n != len(hours) or occupied & hours:
            # Conflicting populations do not justify a displayed daily breakdown.
            return []
        candidates.append({"code": band.get("code"), "window": _fmt_window(a, b), "hours": n,
                           "signedBiasMw": bias, "maeMw": mae})
        occupied |= hours
    return candidates


def _additional_points(operation, rows, signs):
    if signs.get("modelErrorMw") != "modelForecastMw - actualMw":
        return []
    in_rows = {r["fromHourJst"] for r in rows.values() if r["kind"] == "point"}
    result = []
    for miss in operation.get("topMisses") or []:
        hour, p, a, err = (miss.get(k) for k in ("hour", "modelForecastMw", "actualMw", "modelErrorMw"))
        if not _hour(hour) or hour in in_rows or not all(map(_finite, (p, a, err))):
            continue
        if Decimal(str(p)) - Decimal(str(a)) == Decimal(str(err)):
            result.append((hour, err))
            in_rows.add(hour)
    return result


def _day_shape(operation):
    largest = (operation.get("shape") or {}).get("largestDeltaMiss") or {}
    a, b, actual, pub = (largest.get(k) for k in ("fromHour", "toHour", "actualDeltaMw", "modelDeltaMw"))
    if _hour(a) and _hour(b) and b == a + 1 and _finite(actual) and _finite(pub):
        return {"kind": "shape", "fromHourJst": a, "toHourJst": b,
                "actualChange": actual, "publishedChange": pub}
    return None


def _plans(packet, events, rows):
    """Reuse the present candidate gate with the retained bundle's same-event evidence."""
    bundles = {b.get("eventId"): b for b in packet.get("eventEvidenceBundles") or []}
    seen = set()
    for ticket in packet.get("recommendationTicketCandidates") or []:
        key, target = ticket.get("eventId"), ticket.get("target")
        row, bundle = rows.get(key), bundles.get(key)
        metrics = ticket.get("acceptanceMetrics") or []
        if (row is None or row["kind"] == "vintage" or bundle is None
                or bundle.get("hour") != row["fromHourJst"] or target not in REPLAY or target in seen
                or not metrics or any(x not in METRICS for x in metrics)):
            continue
        bounds = _window(ticket.get("testWindowJst"), timed=True)
        if not bounds or not bounds[0] <= row["fromHourJst"] <= bounds[1]:
            continue
        derived = refs.prior.live._recommended_ticket_for_event(events[key], bundle.get("shapeEvidence"))
        if ticket != derived or ticket != bundle.get("recommendedTicket"):
            continue
        seen.add(target)
        yield {"eventId": key, "target": target, "window": _fmt_window(*bounds), "metrics": list(metrics),
               "stages": RUN_STAGES}


def _capsule(row):
    return {loc: refs.capsule(row, None, loc) for loc in LOCALES}


def _remark(row, claim):
    a, b = row["fromHourJst"], row.get("toHourJst")
    frame = _fmt_window(a, b) if b is not None else f"{a:02d}:00 JST"
    labels = ("Additional verified interpretation", "추가로 확인된 해석", "追加で確認した解釈")
    return {loc: f"{label} ({frame}): {line}"
            for loc, label, line in zip(LOCALES, labels, refs.COMPARISONS[claim])}


def render(fallback, packet, raw):
    """Render all locales once from shared facts. Only the last neutral notes depend on Luna."""
    report = {loc: deepcopy(fallback) for loc in LOCALES}
    rows = refs.evidence(packet)
    events, tuples = refs.prior._observations(packet)
    accepted, rejected = refs.choose(raw or {}, rows)
    plans = list(_plans(packet, events, rows))
    plans_by_event = {}
    for plan in plans:
        plans_by_event.setdefault(plan["eventId"], []).append(plan)
    core_cards = set(plans_by_event)
    seen = set()
    for key, row in rows.items():
        if row["kind"] not in seen:
            core_cards.add(key)
            seen.add(row["kind"])

    for loc, doc in report.items():
        doc["language"] = doc["contentLanguage"] = loc
        doc["rootCauseHypotheses"] = []
        doc["featureRecommendations"] = []
        doc["operatorNotes"] = []
        doc["limitations"] = [SENTENCES["limits"][LOCALES.index(loc)]]
        doc["dataQuality"]["limitations"] = doc["limitations"]
        summary = refs.prior.live._deterministic_executive_summary_copy(doc)
        if summary is None:
            # No hidden English fallback for an unavailable summary.
            raise ValueError("missing localized deterministic performance summary")
        doc["executiveSummary"] = summary
        doc["generator"].update(provider="openai" if raw is not None else "fallback",
                                model="gpt-6-luna" if raw is not None else None,
                                localizationStatus="ok")
        doc["generator"].pop("localizationModel", None)

    coverage = packet.get("coverageContext") or {}
    finalized = coverage.get("finalActualCoverage") or {}
    snapshot = coverage.get("intradayCalibrationCoverage") or {}
    operation, signs = packet.get("operationFacts") or {}, packet.get("errorSignConvention") or {}

    def note(copy):
        for loc in LOCALES:
            report[loc]["operatorNotes"].append(copy[loc])

    final, retained = finalized.get("observedHours"), snapshot.get("observedHours")
    if type(final) is int and type(retained) is int:
        note(_text("snapshot", final=final, snapshot=retained))
    elif type(final) is int:
        note(_text("final_only", final=final))
    bands = _time_bands(operation, finalized, signs)
    if bands:
        text = [_text("band_values", window=b["window"], count=b["hours"],
                      bias=refs._mw(b["signedBiasMw"]), mae=f'{b["maeMw"]:,.1f} MW') for b in bands]
        label, values = _text("band_label"), _join(text, ("; ", " / ", "；"))
        note({loc: f"{label[loc]} {values[loc]}" for loc in LOCALES})

    for key, row in rows.items():
        if key not in core_cards:
            note(_capsule(row))
            continue
        kind = row["kind"]
        for loc in LOCALES:
            title = _text(f"{kind}_title")[loc]
            stages = RUN_STAGES if key in plans_by_event else CORE_STAGES
            next_check = (_text("ticket_check", window=plans_by_event[key][0]["window"],
                                stages=_names(stages, TERMS)) if key in plans_by_event
                          else _text(f"check_{kind}", stages=_names(stages, TERMS)))
            hours = [row["fromHourJst"]]
            if kind == "shape":
                hours.append(row["toHourJst"])
            report[loc]["rootCauseHypotheses"].append({
                "id": f"review.{key}", "title": title, "explanation": refs.capsule(row, None, loc),
                "mechanism": _text("vintage_cause" if kind == "vintage" else "unverified_cause")[loc],
                "nextCheck": next_check[loc], "counterEvidence": [], "relatedHours": hours,
                "relatedTimeBands": [events[key]["timeBand"]] if events[key].get("timeBand") else [],
                "relatedFeatures": [], "sourceEventIds": [key], "severity": events[key].get("severity", "warning"),
                "confidence": "medium", "evidenceStatus": "partial",
                "evidence": refs.prior._evidence(key, tuples[key], events),
            })
    points = []
    extra_shape = None
    if rows and _full_final(finalized):
        points = _additional_points(operation, rows, signs)
        for h, err in points:
            note(_text("point", hour=f"{h:02d}:00 JST", error=refs._mw(err)))
        day_shape = _day_shape(operation)
        if day_shape and not any(r["kind"] == "shape" and r["fromHourJst"] == day_shape["fromHourJst"]
                                 and r["toHourJst"] == day_shape["toHourJst"] for r in rows.values()):
            extra_shape = day_shape
            note(_capsule(day_shape))

    for plan in plans:
        key, target = plan["eventId"], plan["target"]
        focus = dict(zip(LOCALES, REPLAY[target]["focus"]))
        for loc, risk in zip(LOCALES, REPLAY[target]["risk"]):
            report[loc]["featureRecommendations"].append({
                "id": f"replay.{key}.{target}", "priority": "medium", "type": "evaluation", "target": target,
                "suggestion": _text("ticket_suggestion", window=plan["window"], focus=focus)[loc],
                "expectedEffect": _text("ticket_goal")[loc], "risk": risk,
                "validationPlan": _text("ticket_metrics", metrics=_names(plan["metrics"], METRICS))[loc],
                "linkedHypotheses": [f"review.{key}"], "autoApply": False,
            })
    if plans:
        note(_text("ticket_notice"))

    deterministic_notes = len(report["en"]["operatorNotes"])
    extras = {}
    for key, claim in accepted.items():
        # Point direction is already expressed by the deterministic signed error.
        if claim in refs.COMPARISONS:
            extras[key] = claim
            note(_remark(rows[key], claim))
    return report, {"mandatory": {"bands": bands, "evidenceIds": list(rows), "otherPoints": points,
                                 "otherShape": extra_shape, "operatorNoteCount": deterministic_notes},
                    "additional": extras, "conditional": plans, "rejected": rejected}
