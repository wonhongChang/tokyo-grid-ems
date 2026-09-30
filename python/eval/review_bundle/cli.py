"""Explicit, measured read-only evidence access. No production imports."""
import argparse
import json
import sys
import time
from pathlib import Path

from . import core
from . import batch
from .access import Access, SourceLoader, pointer, relative_path


def page(items, offset, limit):
    end = min(offset + limit, len(items))
    return {"items": items[offset:end], "paging": {"offset": offset, "limit": limit, "total": len(items),
            "nextOffset": end if end < len(items) else None, "truncated": False}}


class Reader:
    def __init__(self, access, manifest, seal_hash):
        self.access, self.manifest = access, manifest
        self.cache = {}
        self.last_fact = None
        self.seal = access.read_json(access.bundle / "access.json", seal_hash, "bundle_manifest")
        if self.seal.get("inputManifestSha256") != core.sha(core.enc(self.public_manifest())):
            core.fail("INPUT_BUNDLE_MISMATCH")
        self.root = self.local("review_bundle.json")
        if "headerContextRef" in self.root:
            self.header = self.local(self.root["headerContextRef"]["path"])
        else:
            self.header = self.root

    def public_manifest(self):
        return dict(self.manifest, inputs={k: {n: e[n] for n in ("path", "sha256", "bytes")} for k, e in self.manifest["inputs"].items()})

    def local(self, name, p=""):
        path = relative_path(self.access.bundle, name)
        entry = self.seal.get("files", {}).get(name)
        if not entry:
            core.fail("BUNDLE_FILE_NOT_REGISTERED", missingLocator=name)
        if name not in self.cache:
            self.cache[name] = self.access.read_json(path, entry["sha256"], "bundle")
        return pointer(p, self.cache[name])

    def reference(self, r):
        if self.seal["files"].get(r["path"], {}).get("sha256") != r["sha256"]:
            core.fail("BUNDLE_REFERENCE_HASH_MISMATCH", missingLocator=r["path"])
        return self.local(r["path"], r.get("pointer", ""))

    def fact(self, id):
        catalog = self.reference(self.header["factIndexRef"])["facts"]
        if id not in catalog:
            core.fail("FACT_NOT_REGISTERED", missingLocator=id)
        self.last_fact = self.reference(catalog[id])
        return self.last_fact

    def scope(self, id):
        return next((s for s in self.header["scopes"] if s["id"] == id), None)

    def context(self, f=None):
        p = f["population"] if f else None
        s = self.scope(f["scope"]) if f else None
        method = p["method"] if p else "metadata"
        return {"scope": f["scope"] if f else None, "scopeMetadata": s,
                "date": f["date"] if f else None, "window": {"asOf": s.get("asOf"), "capturedAt": s.get("capturedAt")} if s else None,
                "method": method, "methodDefinition": core.METHODS.get(method), "population": p,
                "sampleCount": p["n"] if p else None, "evidenceState": f["state"] if f else core.state(),
                "noticeRefs": [self.header["mandatoryNotices"]["ref"]],
                "provenance": f["provenance"] if f else [], "detailRef": f["detailRef"] if f else None,
                "factId": f["id"] if f else None, "compatibleBasesAssumed": False, "promotionAuthorization": False}

    def result(self, value, f=None, **extra):
        return dict(context=self.context(f), state=f["state"] if f else core.state(), value=value, **extra)

    def index(self, scope, date):
        s = self.scope(scope)
        if not s:
            core.fail("SCOPE_NOT_REGISTERED", missingLocator=scope)
        if s["role"] == "candidate_validation":
            f = self.fact(scope + ":scope:candidate_validation")
            return self.reference(f["value"]["indexRef"]), f
        dates = self.reference(self.header["dateIndexRef"])["dates"]
        key = scope + ":" + str(date)
        if key not in dates:
            core.fail("DATE_NOT_REGISTERED", missingLocator=key)
        return self.reference(dates[key]["indexRef"]), None

    def run_rows(self, scope, date, hour=None, issued=None):
        idx, f = self.index(scope, date)
        if f:
            rows = [r for r in idx["rows"] if (date is None or r["targetDate"] == date) and
                    (hour is None or r["targetHour"] == hour) and (issued is None or r["issueTime"] == issued)]
            return rows, f
        rows = []
        for r in idx["rows"]:
            run = idx["runs"][r[2]]
            if (hour is not None and r[1] != hour) or (issued is not None and run["issuedAt"] != issued):
                continue
            v = dict(zip(idx["columns"], r))
            v["run"] = run
            v["provenance"] = {"source": run["source"], "pointer": r[7], "sha256": run["sourceHash"]}
            v["retrospective"] = r[3] <= 0
            rows.append(v)
        return rows, None

    def source(self, f, key, p):
        entry = self.access.inventory.get(key)
        if not entry:
            core.fail("SOURCE_NOT_REGISTERED", expectedSource=key)
        # A parent fact is navigation context, never proof that a raw row belongs
        # to that fact's selected metric population.
        index_rows = []
        if f["date"]:
            index_rows, _ = self.run_rows(f["scope"], f["date"])
        matches = [r for r in index_rows if r["run"]["source"] == key and
                   (p == r["pointer"] or p.startswith(r["pointer"] + "/"))]
        allowed = matches or any(r["source"] == key for r in f["provenance"])
        if not allowed:
            core.fail("SOURCE_NOT_REFERENCED_BY_CONTEXT", expectedSource=key)
        if not p:
            core.fail("SELECTIVE_POINTER_REQUIRED", expectedSource=key)
        try:
            value = pointer(p, self.access.read_json(Path(entry["frozen"]), entry["sha256"], "source"))
        except core.EvidenceError as exc:
            exc.state.update(expectedSource=key, expectedHash=entry["sha256"], pointer=p)
            raise
        out = self.result(value, f)
        out["state"] = core.state()
        out["context"]["parentPopulation"] = out["context"]["population"]
        out["context"]["parentEvidenceState"] = out["context"]["evidenceState"]
        out["context"]["evidenceState"] = out["state"]
        method = "metadata"
        if len(matches) == 1:
            row = matches[0]
            method = "retrospective" if row["retrospective"] else "stages" if row["run"]["kind"] == "calibration" else "interval" if row["intervalAvailable"] else "advance"
        out["context"].update(method=method, methodDefinition=core.METHODS[method], population=None, sampleCount=None,
                              selectedPopulationMembership="not_assumed", sourceRows=matches,
                              provenance=[dict(source=key, pointer=p, sha256=entry["sha256"])])
        return out


class Builder(core.Builder):
    """Contain source absence at scope boundaries without guessing replacements."""
    def __init__(self, manifest, access):
        super().__init__(manifest, access.bundle, SourceLoader(access))
        self.access = access
        self.written = {}

    def write(self, path, obj):
        relative_path(self.out, path)
        r = super().write(path, obj)
        self.written[path] = dict(sha256=r["sha256"], bytes=r["bytes"])
        return r

    def candidate(self, scope):
        try:
            super().candidate(scope)
        except core.EvidenceError as exc:
            self.fact(scope["id"], None, "candidate_validation", "candidate", None, s=exc.state,
                      provenance=[core.ref("candidate:lift_replay.json")])

    def governance(self):
        try:
            super().governance()
        except core.EvidenceError as exc:
            self.fact("primary", None, "governance", "metadata", None, s=exc.state,
                      provenance=[core.ref("extra:metrics/model_promotion.json"), core.ref("extra:metrics/operational_replay.json")])


def query(reader, a):
    if a.command in batch.COMMANDS:
        return batch.query(reader, a)
    if a.command == "initial":
        result = reader.result(reader.root)
        if len(core.enc(result)) + 1 > core.TARGET:
            result = reader.result({"overflow": True, "reason": "CLI_ENVELOPE_OVERFLOW", "facts": [],
                                    "initialPacketRef": {"path": "review_bundle.json", **reader.seal["files"]["review_bundle.json"]},
                                    "mandatoryNotices": {"count": reader.header["mandatoryNotices"]["count"], "ref": reader.header["mandatoryNotices"]["ref"]},
                                    "sectionManifestRef": reader.header["sectionManifestRef"],
                                    "chunkManifestRef": reader.header.get("chunkManifestRef"),
                                    "continuation": "Use manifests, facts and selective fact/detail commands; all facts remain indexed"})
        return batch.initial(reader, result, a.expand_provenance, a.expand_details)
    if a.command == "scopes":
        return reader.result(page(reader.header["scopes"], a.offset, a.limit))
    if a.command == "facts":
        catalog = reader.reference(reader.header["factIndexRef"])["facts"]
        ids = [id for id in catalog if (a.scope is None or id.split(":")[0] == a.scope) and
               (a.date is None or id.split(":")[1] == a.date)]
        listing = page(ids, a.offset, a.limit)
        listing["items"] = [{"factId": id, **reader.context(reader.fact(id))} for id in listing["items"]]
        return reader.result(listing)
    if a.command in {"fact", "metadata", "provenance", "resolve"}:
        f = reader.fact(a.fact_id)
        if a.command == "metadata":
            return reader.result(reader.context(f), f)
        if a.command == "provenance":
            refs = []
            for r in f["provenance"]:
                e = reader.access.inventory.get(r["source"])
                refs.append(dict(r, sha256=e["sha256"] if e else None, bytes=e["bytes"] if e else None))
            return reader.result({"sources": refs, "detailRef": f["detailRef"]}, f)
        if a.command == "resolve" and a.kind == "source":
            return reader.source(f, a.source, a.pointer)
        if a.command == "resolve" and a.kind == "detail":
            if not f["detailRef"]:
                core.fail("DETAIL_NOT_RECORDED", missingLocator=a.fact_id)
            if not a.pointer:
                core.fail("SELECTIVE_POINTER_REQUIRED")
            value = reader.local(f["detailRef"]["path"], a.pointer)
        else:
            value = pointer(a.pointer, f)
        if isinstance(value, list):
            if any(x is not None for x in (a.hour, a.issued_at, a.date)):
                value = [row for row in value if isinstance(row, dict) and
                         (a.hour is None or row.get("hour", row.get("targetHour")) == a.hour) and
                         (a.issued_at is None or row.get("at", row.get("issuedAt")) == a.issued_at) and
                         (a.date is None or row.get("day", row.get("date")) == a.date)]
            value = page(value, a.offset, a.limit)
        return reader.result(value, f, selection={"pointer": a.pointer, "hour": a.hour, "date": a.date, "issuedAt": a.issued_at})
    if a.command == "indexes":
        if a.scope is None:
            dates = reader.reference(reader.header["dateIndexRef"])["dates"]
            return reader.result(page([dict(id=k, **v) for k, v in dates.items()], a.offset, a.limit))
        rows, f = reader.run_rows(a.scope, a.date, a.hour, a.issued_at)
        result = reader.result(page(rows, a.offset, a.limit), f)
        if f is None:
            result["context"].update(scope=a.scope, date=a.date, method="mixed_index_not_comparable", population=None,
                                     methodDefinition="Each indexed row has its own basis, lead and run identity; no common metric population")
        return result
    if a.command == "notices":
        notices = reader.reference(reader.header["mandatoryNotices"]["ref"])["notices"]
        return reader.result(page([n for n in notices if a.scope is None or n["scope"] == a.scope], a.offset, a.limit))
    if a.command == "manifests":
        r = reader.header.get("chunkManifestRef") if a.kind == "chunks" else reader.header["sectionManifestRef"]
        if not r:
            core.fail("NO_CHUNKS_REQUIRED")
        value = reader.reference(r)
        key = "chunks" if a.kind == "chunks" else "sections"
        return reader.result(dict(value, **{key: page(value[key], a.offset, a.limit)}))
    if a.command == "chunk":
        cm = reader.reference(reader.header["chunkManifestRef"])
        if not 0 <= a.chunk < len(cm["chunks"]):
            core.fail("CHUNK_NOT_REGISTERED")
        return reader.result(reader.reference(cm["chunks"][a.chunk]["ref"]))
    core.fail("COMMAND_NOT_IMPLEMENTED")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["build", "initial", "scopes", "facts", "fact", "indexes", "metadata", "provenance", "notices", "manifests", "chunk", "resolve", *sorted(batch.COMMANDS)])
    p.add_argument("--input-root", required=True)
    p.add_argument("--input-sha", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--bundle", required=True)
    p.add_argument("--bundle-sha")
    p.add_argument("--scope")
    p.add_argument("--date")
    p.add_argument("--dates", help="Comma-separated explicit dates; paged, never silently dropped")
    p.add_argument("--from", dest="from_date")
    p.add_argument("--to", dest="to_date")
    p.add_argument("--fact-id")
    p.add_argument("--pointer", default="")
    p.add_argument("--kind", choices=["fact", "detail", "source", "chunks", "sections"], default="fact")
    p.add_argument("--source")
    p.add_argument("--hour", type=int)
    p.add_argument("--hours", help="Distinct comma-separated target hours, 0..23")
    p.add_argument("--expand-provenance", action="store_true", help="Expand batch provenance lists instead of sealed references")
    p.add_argument("--expand-details", action="store_true", help="Return full stage summary and overview detail fields")
    p.add_argument("--issued-at")
    p.add_argument("--chunk", type=int, default=0)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=20)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    start = time.perf_counter()
    access = None
    reader = None
    exit_code = 0
    try:
        if args.offset < 0 or not 1 <= args.limit <= 200:
            core.fail("INVALID_PAGE", missingLocator="offset>=0 and limit=1..200")
        access = Access(args.input_root, args.output_root, args.bundle, args.command == "build")
        access.install()
        manifest = access.manifest(args.input_sha)
        if args.command == "build":
            if access.bundle.exists():
                core.fail("OUTPUT_ALREADY_EXISTS")
            access.bundle.mkdir(parents=True)
            builder = Builder(manifest, access)
            measurement = builder.build()
            public = dict(manifest, inputs={k: {n: e[n] for n in ("path", "sha256", "bytes")} for k, e in manifest["inputs"].items()})
            seal = {"schemaVersion": "review-bundle-access/0.2.0", "inputManifestSha256": core.sha(core.enc(public)),
                    "files": builder.written, "calculatorSha256": core.sha(Path(core.__file__).read_bytes()),
                    "readOnlySources": True, "promotionAuthorization": False}
            (access.bundle / "access.json").write_bytes(core.enc(seal))
            result = {"state": core.state(), "context": {"method": "build_metadata", "promotionAuthorization": False},
                      "value": {"bundleSealSha256": core.sha(core.enc(seal)), "initialPacketBytes": measurement["initialBytes"],
                                "builderMeasurement": measurement}}
        else:
            reader = Reader(access, manifest, args.bundle_sha)
            result = query(reader, args)
    except core.EvidenceError as exc:
        result = {"state": exc.state, "value": None, "context": {"scope": args.scope, "date": args.date,
                  "method": None, "population": None, "sampleCount": None, "factId": args.fact_id,
                  "noticeRefs": [], "provenance": [{"source": args.source, "pointer": args.pointer}],
                  "promotionAuthorization": False}}
        exit_code = 2
        if reader is not None and reader.last_fact is not None:
            result["context"] = reader.context(reader.last_fact)
    except (KeyError, TypeError, ValueError, IndexError, OSError) as exc:
        result = {"state": core.state("unavailable", "INVALID_INPUT_OR_BUNDLE", missingLocator=type(exc).__name__),
                  "value": None, "context": {"scope": args.scope, "date": args.date, "method": None,
                  "population": None, "sampleCount": None, "noticeRefs": [], "provenance": [], "promotionAuthorization": False}}
        exit_code = 2
    raw = core.enc(result)
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()
    measure = access.measurement() if access else {}
    measure.update(returnedBytes=len(raw) + 1, elapsedSeconds=time.perf_counter() - start, exitCode=exit_code)
    sys.stderr.buffer.write(core.enc({"measurement": measure}) + b"\n")
    sys.stderr.buffer.flush()
    return exit_code
