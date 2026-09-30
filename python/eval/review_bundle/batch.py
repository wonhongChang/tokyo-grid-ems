"""Bounded review views over sealed v0.2 facts; no changes to selection rules."""
from collections import Counter
from copy import deepcopy
from datetime import date as Date

from . import core
from .access import pointer

VERSION = "review-bundle-batch/1.1.0"
COMMANDS = {"review-summary", "metrics-inventory", "direction-screen", "stage-interval-review", "hour-review", "membership-summary", "paths"}
GROUPS = {
    "review-summary": ("coverage", "metrics", "bands", "shape", "noon_context", "stages", "advance", "interval", "weather"),
    "metrics-inventory": ("coverage", "metrics"),
    "direction-screen": ("bands", "shape", "noon_context"),
    "stage-interval-review": ("stages", "interval", "advance"),
    "hour-review": ("metrics", "advance", "stages", "interval"),
}
DETAIL_PATHS = {"metrics": "/rows", "advance": "/advance", "stages": "/stages", "interval": "/interval"}
MAX_DATES = 31


def paging(total, offset, limit):
    end = min(total, offset + limit)
    return dict(offset=offset, limit=limit, total=total, nextOffset=end if end < total else None, truncated=False)


class View:
    def __init__(self, reader, name, scope=None):
        self.reader = reader
        self.value = dict(schemaVersion=VERSION, view=name, scopeContext=reader.scope(scope),
                          registry={k: {} for k in ("methods", "identities", "provenance", "details", "notices", "files")},
                          dates=[], scopeSections={}, mandatoryNotices=reader.header["mandatoryNotices"],
                          sourceInventoryRef=reader.header["sourceIndexRef"],
                          compatibleBasesAssumed=False, promotionAuthorization=False)
        self.notices = reader.reference(reader.header["mandatoryNotices"]["ref"])["notices"]
        self.catalog = reader.reference(reader.header["factIndexRef"])["facts"]

    def intern(self, kind, value):
        if value is None:
            return None
        table = self.value["registry"][kind]
        for key, old in table.items():
            if old == value:
                return key
        key = kind[0] + str(len(table))
        table[key] = value
        return key

    def section(self, fact_id):
        if fact_id not in self.catalog:
            scope, date, _ = fact_id.split(":")
            # A failed date is not an empty successful date. Preserve its error.
            error_id = scope + ":" + date + ":day_error"
            f = self.reader.fact(error_id) if error_id in self.catalog else None
            return dict(factId=fact_id, method=None, population=None, sampleCount=None,
                        state=f["state"] if f else core.state("unavailable", "FACT_NOT_REGISTERED", missingLocator=fact_id),
                        value=None, provenanceRef=self.intern("provenance", f["provenance"] if f else []),
                        detailRef=None, noticeRefs=[self.intern("notices", n) for n in self.notices if n.get("fact") == error_id],
                        errorFactId=error_id if f else None)
        f = self.reader.fact(fact_id)
        pop = deepcopy(f["population"])
        if pop is not None:
            pop["identityRef"] = self.intern("identities", pop.pop("identity"))
        method = f["population"]["method"] if f["population"] else "metadata"
        self.value["registry"]["methods"][method] = core.METHODS[method]
        return dict(factId=fact_id, method=method, population=pop,
                    sampleCount=f["population"]["n"] if f["population"] else None,
                    state=f["state"], value=f["value"],
                    provenanceRef=self.intern("provenance", f["provenance"]),
                    detailRef=self.intern("details", f["detailRef"]),
                    noticeRefs=[self.intern("notices", n) for n in self.notices if n.get("fact") == fact_id])

    def detail(self, section, path):
        ref = self.value["registry"]["details"].get(section["detailRef"])
        if ref is None:
            core.fail("DETAIL_NOT_RECORDED", missingLocator=section["factId"])
        return pointer(path, self.reader.reference(ref))

    def supplemental(self, section, function):
        try:
            return dict(state=core.state(), value=function())
        except core.EvidenceError as exc:
            return dict(state=exc.state, value=None)

    def add_date(self, scope, date, kinds):
        sections = {k: self.section(f"{scope}:{date}:{k}") for k in kinds}
        row = dict(scope=scope, date=date, sections=sections)
        self.value["dates"].append(row)
        return row

    def result(self, expand_provenance=False):
        # Hour/overview projections can replace a full-day provenance entry.
        # Keep only entries referenced by the returned sections, not dead copies.
        sections = [s for r in self.value["dates"] for s in r["sections"].values()] + list(self.value["scopeSections"].values())
        sections += [s for r in self.value["dates"] for t in r.get("targets", []) for s in t["sections"].values()]
        if not expand_provenance:
            deferred = {}
            for s in sections:
                refs = self.value["registry"]["provenance"][s["provenanceRef"]]
                if not isinstance(refs, list):
                    continue
                digest = core.sha(core.enc(refs))
                if digest in deferred:
                    s["provenanceRef"] = deferred[digest]
                    continue
                sealed = self.catalog.get(s["factId"])
                sealed_ref = dict(fileRef=self.intern("files", {k: v for k, v in sealed.items() if k != "pointer"}),
                                  pointer=sealed["pointer"]) if sealed else None
                descriptor = dict(deferred=True, command="provenance", factId=s["factId"],
                    sealedFactRef=sealed_ref,
                    sourceCount=len({r["source"] for r in refs}), locatorCount=len(refs),
                    referenceListSha256=digest,
                    identityStatus="see_each_section_population_and_row_identities",
                    compatibleBasesAssumed=False)
                if "selection" in s:
                    scope, date, _ = s["factId"].split(":")
                    descriptor["expandQuery"] = dict(command="hour-review", scope=scope, date=date,
                        hour=s["selection"]["hour"], expandProvenance=True)
                    descriptor["provenanceScope"] = "selected_target_rows_only"
                inline = dict(deferred=False, sources=refs, sourceCount=descriptor["sourceCount"],
                              identityStatus=descriptor["identityStatus"])
                # Deferring a short locator list can cost more than retaining it.
                # Choose by representation bytes only, never evidence salience.
                if len(core.enc(inline)) <= len(core.enc(descriptor)):
                    descriptor = inline
                s["provenanceRef"] = self.intern("provenance", descriptor)
                deferred[digest] = s["provenanceRef"]
        used = {s["provenanceRef"] for s in sections}
        self.value["registry"]["provenance"] = {k: v for k, v in self.value["registry"]["provenance"].items() if k in used}
        file_refs = {v["sealedFactRef"]["fileRef"] for v in self.value["registry"]["provenance"].values()
                     if isinstance(v, dict) and v.get("sealedFactRef")}
        self.value["registry"]["files"] = {k: v for k, v in self.value["registry"]["files"].items() if k in file_refs}
        out = self.reader.result(self.value)
        out["context"].update(method="review_view_not_comparable", population=None,
                              methodDefinition="Resolve each section's own method, population and references; no shared metric population")
        return out


def validate_date(value):
    if Date.fromisoformat(value).isoformat() != value:
        core.fail("INVALID_DATE", missingLocator=value)
    return value


def date_selection(reader, args):
    if not args.scope or reader.scope(args.scope) is None:
        core.fail("SCOPE_NOT_REGISTERED", missingLocator=args.scope)
    count = int(bool(args.date)) + int(bool(args.dates)) + int(bool(args.from_date or args.to_date))
    if count != 1:
        core.fail("DATE_SELECTION_REQUIRED", missingLocator="Choose --date, --dates, or --from and --to")
    if args.date:
        selected = [validate_date(args.date)]
    elif args.dates:
        selected = [validate_date(d) for d in args.dates.split(",")]
        if len(set(selected)) != len(selected):
            core.fail("DUPLICATE_DATE")
    else:
        if not args.from_date or not args.to_date:
            core.fail("DATE_RANGE_REQUIRED")
        start, end = validate_date(args.from_date), validate_date(args.to_date)
        if start > end:
            core.fail("INVALID_DATE_RANGE")
        catalog = reader.reference(reader.header["factIndexRef"])["facts"]
        selected = sorted({i.split(":")[1] for i in catalog if i.split(":")[0] == args.scope and start <= i.split(":")[1] <= end})
    if args.command in {"review-summary", "hour-review"} and (not args.date or len(selected) != 1):
        core.fail("SINGLE_DATE_REQUIRED")
    limit = min(args.limit, MAX_DATES)
    info = paging(len(selected), args.offset, limit)
    return selected[args.offset:args.offset + limit], info


def identity_cohorts(rows):
    groups = {}
    for row in rows:
        identity = row.get("sourceIdentity")
        key = core.enc(identity)
        group = groups.setdefault(key, dict(identity=identity, hours=[], n=0))
        group["hours"].append(row["hour"])
        group["n"] += 1
    return list(groups.values())


def annotate_summaries(view, sections):
    if "shape" in sections:
        section = sections["shape"]

        def strongest():
            rows = view.detail(section, "/shape/transitions")
            opposing = [r for r in rows if r["opposingSigns"]]
            return dict(strongestOpposingTransition=max(opposing, key=lambda r: abs(r["deltaError"]), default=None),
                        transitionsRef=dict(factId=section["factId"], pointer="/shape/transitions"),
                        diagnosticClassification=None)
        section["descriptiveContext"] = view.supplemental(section, strongest)
    for kind in ("stages", "interval", "advance"):
        if kind not in sections:
            continue
        section = sections[kind]
        section["rowIdentityCohorts"] = view.supplemental(
            section, lambda s=section, k=kind: identity_cohorts(view.detail(s, DETAIL_PATHS[k])))
        if kind == "stages" and isinstance(section["value"], dict):
            section["hourCounts"] = {k: len(section["value"][k]) if isinstance(section["value"].get(k), list) else None
                                     for k in ("improvedHours", "worsenedHours")}
        if kind == "interval":
            section["profileScope"] = "recorded_published_file_profile_not_all_selected_snapshot_profiles"


def hour_view(view, scope, date, hour):
    if hour is None or not 0 <= hour <= 23:
        core.fail("INVALID_HOUR", missingLocator=str(hour))
    sections = view.add_date(scope, date, GROUPS["hour-review"])["sections"]
    indexed = None
    try:
        indexed, _ = view.reader.run_rows(scope, date, hour)
        index_state = core.state()
    except core.EvidenceError as exc:
        index_state = exc.state
    selected_runs = set()
    for kind, section in sections.items():
        rows_result = view.supplemental(section, lambda s=section, k=kind: [r for r in view.detail(s, DETAIL_PATHS[k]) if r["hour"] == hour])
        rows = deepcopy(rows_result["value"])
        section["value"] = rows
        selection_state = rows_result["state"]
        if rows == []:
            selection_state = core.state("unavailable", "NO_SELECTED_TARGET_ROW", sampleCount=0, missingLocator=DETAIL_PATHS[kind])
        section["selection"] = dict(hour=hour, rowCount=len(rows) if rows is not None else None, state=selection_state,
                                    detailPointer=DETAIL_PATHS[kind], parentPopulationUnchanged=True)
        section["runContext"] = []
        selected_provenance = []
        for row in rows or []:
            for ref_key in ("sourceRef", "actualRef", "forecastRef"):
                if row.get(ref_key) and row[ref_key] not in selected_provenance:
                    selected_provenance.append(row[ref_key])
            ref = row.get("sourceRef")
            matches = [r for r in indexed or [] if ref and r["run"]["source"] == ref["source"] and r["pointer"] == ref["pointer"]]
            section["runContext"].append(dict(state=core.state() if matches else core.state("unavailable", "RUN_NOT_RECORDED"),
                matches=[dict(run={k: v for k, v in r["run"].items() if k != "source"},
                              leadMinutes=r["leadMinutes"], basis=r["basis"], retrospective=r["retrospective"],
                              sourceRefFromSelectedRow=True) for r in matches], publishedRowRunNotInferred=kind == "metrics"))
            for match in matches:
                selected_runs.add(core.enc(match["run"]))
            if kind == "stages":
                ref = row.get("contextRef")
                if ref:
                    try:
                        f = view.reader.fact(section["factId"])
                        out = view.reader.source(f, ref["source"], ref["pointer"] + "/lastObservedHour")
                        cutoff = dict(value=out["value"], state=out["state"], provenance=out["context"]["provenance"])
                    except core.EvidenceError as exc:
                        cutoff = dict(value=None, state=exc.state, provenance=[dict(source=ref["source"], pointer=ref["pointer"] + "/lastObservedHour")])
                else:
                    cutoff = dict(value=None, state=core.state("unavailable", "FIELD_NOT_RECORDED"), provenance=[])
                row["observationCutoff"] = cutoff
        section["provenanceRef"] = view.intern("provenance", selected_provenance)
        section["provenanceScope"] = "selected_target_rows_only"
        section["parentProvenanceQuery"] = dict(command="provenance", factId=section["factId"])
    all_runs = {core.enc(r["run"]) for r in indexed or []}
    view.value["target"] = dict(scope=scope, date=date, hour=hour, indexState=index_state,
        availableRowsByBasis=dict(Counter(r["basis"] for r in indexed)) if indexed is not None else None,
        availableRunCount=len(all_runs) if indexed is not None else None,
        alternativeRunCount=len(all_runs - selected_runs) if indexed is not None else None,
        alternativeRunsIncluded=False, indexQuery=dict(command="indexes", scope=scope, date=date, hour=hour),
        leadDefinitions=dict(lead="minutes from the recorded run/capture issue time", leadHours="retained control field; not a substitute for issue-time lead", lastObservedHour="recorded correction observation cutoff, null remains unknown"))


def selected_hours(args, required=False):
    if args.hour is not None and args.hours is not None:
        core.fail("AMBIGUOUS_HOUR_SELECTION")
    hours = [args.hour] if args.hour is not None else [int(h) for h in args.hours.split(",")] if args.hours else []
    if (required and not hours) or any(not 0 <= h <= 23 for h in hours) or len(set(hours)) != len(hours):
        core.fail("INVALID_HOUR_SELECTION")
    return hours


def compact_stages(view, sections):
    section = sections.get("stages")
    if section is None or not isinstance(section["value"], dict):
        return
    original = section["value"]
    def extremes():
        rows = view.detail(section, "/stages")
        valid = [r for r in rows if core.finite(r.get("absErrorDelta"))]
        def small(row):
            return {k: row.get(k) for k in ("hour", "generatedAt", "lead", "raw", "pre", "post", "absErrorDelta", "sourceIdentity", "sourceRef")} if row else None
        return dict(strongestImprovement=small(min((r for r in valid if r["absErrorDelta"] < 0), key=lambda r: r["absErrorDelta"], default=None)),
                    strongestWorsening=small(max((r for r in valid if r["absErrorDelta"] > 0), key=lambda r: r["absErrorDelta"], default=None)))
    section["extremes"] = view.supplemental(section, extremes)
    section["value"] = {k: original.get(k) for k in ("raw", "post", "missingSourceStates")}
    section["presentationProjection"] = True
    section["evidenceQueries"] = dict(fullSummary=dict(command="fact", factId=section["factId"], pointer="/value"),
        allHours=dict(command="resolve", kind="detail", factId=section["factId"], pointer="/stages"),
        allAdverseHours=dict(command="fact", factId=section["factId"], pointer="/value/worsenedHours"))


def membership(view, scope, date, hours):
    requested = hours or list(range(24))
    try:
        indexed, candidate = view.reader.run_rows(scope, date)
        if candidate:
            core.fail("CANDIDATE_INDEX_REQUIRES_PAIR_QUERY")
        rows = [r for r in indexed if r["hour"] in requested]
        interval = view.section(f"{scope}:{date}:interval")
        selected = view.supplemental(interval, lambda: sorted({r["hour"] for r in view.detail(interval, "/interval") if r["hour"] in requested}))
        catalog = view.reader.reference(view.reader.header["dateIndexRef"])["dates"]
        ref = catalog[scope + ":" + date]["indexRef"]
        value = membership_counts(rows, requested)
        value["selectedIntervalHours"] = selected
        value["indexQuery"] = dict(command="indexes", scope=scope, date=date)
        value["detailQuery"] = dict(command="resolve", kind="detail", factId=interval["factId"], pointer="/interval")
        state = core.state()
        provenance = dict(deferred=True, sealedIndexRef=ref, sourceCount=len({r["run"]["source"] for r in rows}),
                          identityStatus="row_specific_not_collapsed", expandQuery=value["indexQuery"], compatibleBasesAssumed=False)
    except core.EvidenceError as exc:
        value, state = None, exc.state
        provenance = dict(deferred=True, sealedIndexRef=None, sourceCount=None, identityStatus="unknown",
                          expandQuery=dict(command="indexes", scope=scope, date=date), compatibleBasesAssumed=False)
    method = "index_membership_not_comparable"
    view.value["registry"]["methods"][method] = dict(basis="retained_index_membership", metricPopulation=False,
        intervalEligibility="finite 0 < leadMinutes <= 120 and intervalAvailable; not selected/validated interval membership")
    section = dict(factId=f"{scope}:{date}:index-membership", method=method, population=None, sampleCount=None,
        state=state, value=value, provenanceRef=view.intern("provenance", provenance), detailRef=None, noticeRefs=[])
    view.value["dates"].append(dict(scope=scope, date=date, sections={"membership": section}))


def membership_counts(rows, requested):
    positive = lambda r: core.finite(r.get("leadMinutes")) and r["leadMinutes"] > 0
    advance = sorted({r["hour"] for r in rows if positive(r) and r["basis"] == "advance"})
    return dict(requestedHours=requested, totalRows=len(rows), rowsByBasis=dict(Counter(r["basis"] for r in rows)),
        positiveLeadRows=sum(positive(r) for r in rows),
        nonpositiveLeadRows=sum(core.finite(r.get("leadMinutes")) and r["leadMinutes"] <= 0 for r in rows),
        unknownLeadRows=sum(not core.finite(r.get("leadMinutes")) for r in rows),
        retrospectiveRows=sum(r.get("retrospective") is True for r in rows),
        positiveLeadAdvanceRows=sum(positive(r) and r["basis"] == "advance" for r in rows),
        positiveLeadAdvanceHours=advance, missingPositiveLeadAdvanceHours=sorted(set(requested)-set(advance)),
        positiveLeadHours=sorted({r["hour"] for r in rows if positive(r)}),
        eligibleRetainedIntervalHours=sorted({r["hour"] for r in rows if positive(r) and r["leadMinutes"] <= 120 and r.get("intervalAvailable") is True}),
        retainedIndexOnly=True, absenceIsNotGlobalNonexistence=True)


def paths(reader, args):
    f = reader.fact(args.fact_id)
    if f["detailRef"] is None:
        core.fail("DETAIL_NOT_RECORDED", missingLocator=args.fact_id)
    obj = pointer(args.pointer, reader.reference(f["detailRef"]))
    esc = lambda s: str(s).replace("~", "~0").replace("/", "~1")
    rows = []
    if isinstance(obj, dict):
        rows = [dict(pointer=args.pointer + "/" + esc(k), type=type(v).__name__,
                     length=len(v) if isinstance(v, (dict, list)) else None) for k, v in sorted(obj.items())]
    elif isinstance(obj, list):
        rows = [dict(arrayPointer=args.pointer, indexPattern=args.pointer + "/{index}", length=len(obj),
                     itemFields=sorted({k for row in obj if isinstance(row, dict) for k in row}))]
    return reader.result(dict(validDetailChildren=rows[args.offset:args.offset + args.limit],
                              paging=paging(len(rows), args.offset, args.limit),
                              validFactChildren=["/" + esc(k) for k in sorted(f)],
                              missingPointerSubstitution=False), f)


def query(reader, args):
    if args.command == "paths":
        return paths(reader, args)
    if args.command not in {"hour-review", "membership-summary"} and (args.hours is not None or args.hour is not None):
        core.fail("HOUR_SELECTION_NOT_SUPPORTED")
    dates, pg = date_selection(reader, args)
    view = View(reader, args.command, args.scope)
    view.value["paging"] = pg
    view.value["continuation"] = dict(command=args.command, scope=args.scope, dates=args.dates,
                                      date=args.date, fromDate=args.from_date, toDate=args.to_date,
                                      offset=pg["nextOffset"], limit=pg["limit"])
    for date in dates:
        if args.command == "hour-review":
            hours = selected_hours(args, required=True)
            if args.hours is None:
                hour_view(view, args.scope, date, hours[0])
            else:
                targets = []
                for hour in hours:
                    hour_view(view, args.scope, date, hour)
                    row = view.value["dates"].pop()
                    targets.append(dict(hour=hour, sections=row["sections"], target=view.value.pop("target")))
                view.value["dates"].append(dict(scope=args.scope, date=date, sections={}, targets=targets))
                view.value["counterexampleQuery"] = dict(command="review-summary", scope=args.scope, date=date)
        elif args.command == "membership-summary":
            membership(view, args.scope, date, selected_hours(args))
        else:
            row = view.add_date(args.scope, date, GROUPS[args.command])
            if args.command != "metrics-inventory":
                annotate_summaries(view, row["sections"])
            if args.command == "stage-interval-review" and not args.expand_details:
                compact_stages(view, row["sections"])
    return view.result(args.expand_provenance)


def initial(reader, base, expand_provenance=False, expand_details=False):
    """Add a small presentation overview, leaving stored packets/hashes frozen."""
    view = View(reader, "initial-overview")
    for scope in reader.header["scopes"]:
        dates = sorted({id.split(":")[1] for id in view.catalog if id.startswith(scope["id"] + ":") and id.split(":")[1] != "scope"})
        if dates:
            row = view.add_date(scope["id"], dates[-1], ("coverage", "metrics", "bands", "stages", "interval", "weather"))
            for kind, section in row["sections"].items():
                value = section["value"]
                section["overviewProjection"] = True
                section["fullFactQuery"] = dict(command="fact", factId=section["factId"])
                if kind == "coverage" and isinstance(value, dict) and not expand_details:
                    section["value"] = {k: value.get(k) for k in ("asOf", "finalized", "finalizedThrough", "observedHours", "pairedHours", "missingHours")}
                if kind == "bands" and isinstance(value, list):
                    usable = [b for b in value if core.finite(b.get("bias"))]
                    section["value"] = dict(strongestAbsoluteBiasBand=max(usable, key=lambda b: abs(b["bias"]), default=None),
                                            completeBandsFactId=section["factId"])
                if kind == "stages" and isinstance(value, dict):
                    section["value"] = {k: value.get(k) for k in ("raw", "post", "missingSourceStates")}
                    section["counterexampleQuery"] = dict(command="review-summary", scope=scope["id"], date=dates[-1])
                    if not expand_details:
                        section["value"] = dict(raw={k: value.get("raw", {}).get(k) for k in ("n", "mae", "bias")},
                                                post={k: value.get("post", {}).get(k) for k in ("n", "mae", "bias")},
                                                missingSourceStates=value.get("missingSourceStates"))
                if kind == "interval":
                    section["profileScope"] = "recorded_published_file_profile_not_all_selected_snapshot_profiles"
        for id in view.catalog:
            if id.startswith(scope["id"] + ":scope:") and id.endswith((":governance", ":candidate_validation", ":changes")):
                section = view.section(id)
                if id.endswith(":candidate_validation") and isinstance(section["value"], dict):
                    section["value"] = {k: section["value"].get(k) for k in ("changedPairCount", "degradedPairCount", "failedGates", "identityMismatches", "missingFields", "validationComplete", "notPromotionAuthorization", "indexRef")}
                    section["overviewProjection"] = True
                view.value["scopeSections"][id] = section
    out = deepcopy(base)
    # Small packets can inline the very facts rendered again in the overview.
    # Preserve the sealed full inventory rather than returning them twice.
    if out["value"].get("facts") and not expand_details:
        out["value"]["facts"] = []
        out["value"]["inlineFactsDeferred"] = dict(command="facts", ref=reader.header["factIndexRef"])
    out["value"]["reviewOverview"] = view.result(expand_provenance)["value"]
    if len(core.enc(out)) + 1 > core.TARGET:
        # Do not hide a notice or silently trim an evidence field to fit.
        out["value"]["reviewOverview"] = dict(schemaVersion=VERSION, view="initial-overview", overflow=True,
            reason="OVERVIEW_ENVELOPE_OVERFLOW", mandatoryNotices=reader.header["mandatoryNotices"],
            continuation=[dict(command="review-summary", scope=r["scope"], date=r["date"]) for r in view.value["dates"]],
            scopeFactIds=list(view.value["scopeSections"]), compatibleBasesAssumed=False, promotionAuthorization=False)
    if len(core.enc(out)) + 1 > core.TARGET:
        return reader.result(dict(overflow=True, reason="CLI_REVIEW_OVERVIEW_OVERFLOW",
            mandatoryNotices=dict(count=reader.header["mandatoryNotices"]["count"], ref=reader.header["mandatoryNotices"]["ref"]),
            sectionManifestRef=reader.header["sectionManifestRef"], chunkManifestRef=reader.header.get("chunkManifestRef"),
            reviewOverview=dict(schemaVersion=VERSION, view="initial-overview", overflow=True,
                reason="OVERVIEW_ENVELOPE_OVERFLOW", mandatoryNotices=dict(count=reader.header["mandatoryNotices"]["count"], ref=reader.header["mandatoryNotices"]["ref"]),
                continuation=[dict(command="scopes"), dict(command="facts")], scopeFactIds=[],
                allFactsRef=reader.header["factIndexRef"], allScopesDeferred=True,
                compatibleBasesAssumed=False, promotionAuthorization=False)))
    return out
