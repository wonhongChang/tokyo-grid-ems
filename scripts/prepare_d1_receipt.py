"""Attest a single D-1 origin at a known public data commit. No network or predictions."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from python.forecast.d1_component import ARTIFACT, BASE, JST, RECEIPTS, compatible_origin, interval_role, local_time, origin_path, requested, with_trial

def make_proof(commit, stamp, day, origin, snapshots=lambda: ()):
    if not origin or stamp.date()!=day-timedelta(days=1) or not compatible_origin(origin,day,stamp):
        return None
    def witnesses():
        yield origin_path(day).as_posix(),origin
        yield from snapshots()
    for path,raw in witnesses():
        if not raw:continue
        q=json.loads(raw)
        if q.get("targetDate")!=str(day) or (q.get("model") or {}).get("artifactSha256")!=ARTIFACT:continue
        if local_time(q["generatedAt"]).date()!=stamp.date() or local_time(q["generatedAt"])>stamp or not interval_role(q,BASE):continue
        return dict(schema="d1-first-public/1", date=str(day), commit=commit, publishedBy=stamp.isoformat(),priorPolicy=BASE,
                    witness=path,witnessSHA256=hashlib.sha256(raw).hexdigest(),originSHA256=hashlib.sha256(origin).hexdigest())
    return None

def from_public_ref(repo, ref, day):
    def git(*args):
        return subprocess.check_output(["git","-C",str(repo),*args])
    rev=git("rev-parse","--verify","--end-of-options",ref+"^{commit}").decode().strip()
    stamp=datetime.fromtimestamp(int(git("show","-s","--format=%ct",rev)),JST)
    path=origin_path(day).as_posix()
    if not git("ls-tree",rev,"--",path).strip():
        return None
    def snapshots():
        folder="forecast_snapshots/"+str(day)
        files=git("ls-tree","-r","--name-only",rev,"--",folder+"/").decode().splitlines()
        for filename in files:
            if not filename.endswith("/index.json"):yield filename,git("show",rev+":"+filename)
    return make_proof(rev,stamp,day,git("show",rev+":"+path),snapshots)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repository",type=Path,default=Path("."))
    ap.add_argument("--ref",default="refs/remotes/origin/data")
    ap.add_argument("--config",type=Path,default=Path("config.yaml"))
    ap.add_argument("--target",type=date.fromisoformat,default=datetime.now(JST).date()+timedelta(days=1))
    args=ap.parse_args()
    import yaml
    cfg=with_trial(yaml.safe_load(args.config.read_text(encoding="utf-8")))
    if not requested(cfg,args.target):
        return
    proof=from_public_ref(args.repository,args.ref,args.target)
    if proof is None:
        print("No matching previously published D-1 origin; incumbent remains active.")
        return
    directory=Path(cfg["d1_component_trial"].get("receipt_dir",RECEIPTS))
    if directory.resolve().is_relative_to((Path("web")/"public").resolve()):
        raise ValueError("do not put the receipt in public output")
    directory.mkdir(exist_ok=True,parents=True)
    with tempfile.NamedTemporaryFile(dir=directory,delete=False) as tmp:
        tmp.write(json.dumps(proof,sort_keys=True).encode());name=tmp.name
    try:os.replace(name,directory/(str(args.target)+".json"))
    finally:Path(name).unlink(missing_ok=True)
    print("D-1 prior publication verified:",args.target,proof["commit"])
if __name__=="__main__":main()
