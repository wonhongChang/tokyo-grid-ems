"""Issue a research-only D0 forecast with a contemporaneous, independently read Pages comparator."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sameday_refresh as sd

SITE = "https://wonhongchang.github.io/tokyo-grid-ems/"


def now():
    return datetime.now(sd.src.JST)


def public_read(path):
    url = f"{SITE}{path}?preview={time.time_ns()}"
    with urllib.request.urlopen(url, timeout=12) as resp:
        raw = resp.read(500001)
    if len(raw) > 500000:
        raise ValueError("oversize public response")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def site_view(day):
    try:
        forecast, sha = public_read(f"forecast/{day}.json")
        if forecast["date"] != day or forecast["availability"] != "ok" or len(forecast["series"]) != 24:
            raise ValueError("incomplete public curve")
        view = dict(sha256=sha, forecast=forecast, receivedAt=now().isoformat())
        try:
            view["marker"] = public_read("ops/pages_release.json")[0]
        except (OSError, ValueError):
            view["marker"] = None
        return view
    except (KeyError, OSError, ValueError) as exc:
        return {"unavailable":type(exc).__name__}


def run(base, out):
    if out.exists() or base.resolve() in out.resolve().parents:
        raise ValueError("require new output outside source")
    out.mkdir(parents=True)
    sha = sd.oid(sd.git(base, "rev-parse", "HEAD"))
    start = now()
    record = dict(schema=1, codeSha=os.environ["GITHUB_SHA"], baseSha=sha,
                  run=os.environ["GITHUB_RUN_ID"], attempt=os.environ["GITHUB_RUN_ATTEMPT"],
                  start=start.isoformat(), date=str(start.date()), mode="preview")
    if start.hour not in sd.HOURS:
        record["status"] = "expired_slot"
    else:
        day = str(start.date())
        before = site_view(day)
        body = sd.src.fetch_csv()
        received = now()
        if received.hour != start.hour or received.date() != start.date():
            record["status"] = "expired_slot"
        else:
            config = sd.yaml.safe_load((sd.ROOT/"config.yaml").read_bytes())
            delta = out/"delta"
            record["status"] = sd.compute(base, delta, sha, body, received, config)
            if record["status"] == "changed":
                pr = sd.read(delta/"forecast"/f"{day}.json")
                record["receipt"] = sd.read(delta/"ops/same_day/latest.json")
                record["preview"] = pr
                record["dataBaseline"] = sd.read(base/"forecast"/f"{day}.json")
                after = site_view(day)
                matched = (before.get("sha256") is not None and before["sha256"]==after.get("sha256")
                           and before.get("marker")==after.get("marker"))
                record["siteComparison"] = "observed_stable" if matched else "unavailable"
                record["siteBefore"] = before
                record["siteAfter"] = {k:v for k,v in after.items() if k!="forecast"}
    record["completedAt"] = now().isoformat()
    sd.write(out/"evidence.json", record)
    print(json.dumps({k:record.get(k) for k in ("run","baseSha","status","siteComparison","completedAt")}))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--base",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    run(args.base,args.out)
