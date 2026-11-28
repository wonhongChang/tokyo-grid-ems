"""Pages-only projection and observed data-tip receipts; standard library, no HTTP."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DIR = "ops/hourly-next"
ID = "753f7a732df26f42bb7a4f8c20370ccc8bcbc97628967a93015c229ab5ebd4d7"


def _hash(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(txt):
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(JST)


def records(root, day):
    for p in sorted((root/DIR/day).glob("[0-9]*.json")):
        doc = json.loads(p.read_bytes())
        r, key = doc["record"], doc["sha256"]
        if (_hash(r) != key or r["identity"] != ID or r["targetStart"][:10] != day
                or not _time(r["nativeGeneratedAt"]) <= _time(r["issuedAt"]) < _time(r["targetStart"])):
            raise ValueError("invalid hourly issue")
        yield key, r


def valid(proof, key, r):
    if not isinstance(proof, dict) or proof.get("id") != key or not re.fullmatch("[0-9a-f]{40}", str(proof.get("data"))):
        return False
    try:
        return _time(r["issuedAt"]) <= _time(proof["dataSeenAt"]) < _time(r["targetStart"])
    except (TypeError, ValueError, KeyError):
        return False


def lookup(live):
    return {p["id"]:p for p in (live or {}).get("hourlyProofs", []) if isinstance(p, dict) and isinstance(p.get("id"), str)}


def matches_release(root, day, r, actual):
    # A local run can compute more than once before its data push. Attest only
    # the actual inputs and Champion output that survived into this release.
    inputs = (("forecast", "nativeSha256"), ("reports/internal/operational-calibration", "calibrationSha256"))
    return _hash(actual) == r["actualSha256"] and all(
        (p := root / folder / (day + ".json")).is_file() and _hash(json.loads(p.read_bytes())) == r[field]
        for folder, field in inputs
    )


def remember(root, live):
    """Reuse the existing Pages marker read; the NEXT ordinary data push archives its proofs."""
    known = lookup(live)
    if not known:
        return
    # Inspect only the dates referenced in the previous release (including a missed day).
    dates = {p.get("targetDate", "") for p in known.values()}
    for day in dates:
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        for key, r in records(root, day):
            proof = known.get(key)
            if valid(proof, key, r):
                dest = root/DIR/day/("proof-"+key+".json")
                if not dest.exists():
                    with dest.open("x", encoding="utf8") as f:
                        json.dump(proof, f, sort_keys=True, separators=(",", ":"))


def project(root, data, live=None, *, clock=lambda: datetime.now(JST)):
    status_file = root/"status.json"
    status = json.loads(status_file.read_bytes())
    today = status["today"]["date"]
    yesterday = str(datetime.fromisoformat(today).date()-timedelta(days=1))
    final = set(json.loads((root/".etl_state.json").read_bytes()).get("okDates", [])) if (root/".etl_state.json").exists() else set()
    known = lookup(live); proofs = []; rows = []
    at = clock()
    for day in [yesterday, today]:
        actual_file = root/"actual"/(day+".json")
        actual = json.loads(actual_file.read_bytes()) if actual_file.exists() else {}
        actuals = {p["ts"]:p["actualMw"] for p in actual.get("series", []) if actual.get("date")==day and
                   (p.get("actualSource")=="observed" or (day in final and p.get("actualSource") in (None,"observed_legacy"))) and
                   type(p.get("actualMw")) in (int,float) and p["actualMw"]>0 and _time(p["ts"])+timedelta(hours=1)<=at}
        for key,r in records(root, day):
            disk = root/DIR/day/("proof-"+key+".json")
            proof = json.loads(disk.read_bytes()) if disk.exists() else known.get(key)
            if not valid(proof,key,r) and at < _time(r["targetStart"]) and matches_release(root, day, r, actual):
                proof = dict(id=key,data=data,dataSeenAt=at.isoformat(),targetDate=day)
            confirmed = valid(proof,key,r)
            if confirmed:
                proofs.append(proof)
            y = actuals.get(r["targetStart"]) if confirmed else None
            rows.append(dict(id=key,issuedAt=r["issuedAt"],targetStart=r["targetStart"],targetEnd=r["targetEnd"],
                confirmedAt=proof["dataSeenAt"] if confirmed else None,forecastMw=r["forecastMw"],championMw=r["championMw"],
                actualMw=y,finalized=day in final))
    health = None
    marker = root/"ops/hourly-next-status.json"
    index = root/"forecast_snapshots"/today/"index.json"
    if marker.is_file() and index.is_file():
        entry = json.loads(marker.read_bytes())
        runs = json.loads(index.read_bytes()).get("snapshots", [])
        latest = max((s["generatedAt"] for s in runs if s["generatedAt"][:10]==today), default=None)
        if entry.get("identity")==ID and entry.get("runAt")==latest:
            state = entry["state"]
            if state == "recorded":
                state = "issued" if any(r["id"]==entry["issueId"] and r["confirmedAt"] for r in rows) else "missed"
            if state in {"waiting","disabled","missed","issued"}:
                health = dict(state=state,runAt=latest,targetStart=entry["targetStart"],switch=entry["switch"])
    status["hourlyNext"]=dict(model="SD-H1-P50",rows=rows,health=health)
    status_file.write_text(json.dumps(status,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    return proofs


def protect(worktree):
    """Keep append-only records when Windows publishes a stale mirror."""
    base=["git","-C",str(worktree)]
    if subprocess.run([*base,"rev-parse","--verify","--quiet","HEAD"],stdout=subprocess.DEVNULL).returncode:
        return
    modified=subprocess.check_output([*base,"diff","--no-renames","--name-only","--diff-filter=MT","HEAD","--",DIR])
    if modified:
        raise ValueError("refusing to replace an immutable next-hour issue or receipt")
    missing=subprocess.check_output([*base,"diff","--no-renames","--name-only","-z","--diff-filter=D","HEAD","--",DIR])
    if missing:
        subprocess.run([*base,"restore","--source=HEAD","--worktree","--pathspec-from-file=-","--pathspec-file-nul"],input=missing,check=True)


if __name__=="__main__":
    import sys
    protect(Path(sys.argv[1]))
