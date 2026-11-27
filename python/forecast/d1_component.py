"""Change ONLY the point forecast on verified repeat D-1 publications."""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
ARTIFACT = "c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3"
BASE = "ba4d14312e56659c46a87b8e9c13750b51e93334dcb59661b8d37e6f2d0647bc"
EDITION = "d1-point/1"
FINGERPRINT = hashlib.sha256(f"{BASE}|{ARTIFACT}|{EDITION}|raw|updates".encode()).hexdigest()
RECEIPTS = Path("data/raw/.d1-point")
SWITCH = "TOKYO_GRID_EMS_D1_TRIAL"
APPROVED_TARGETS = ("2026-11-30", "2026-12-03", "2026-12-05")

def with_trial(config):
    """Overlay for the public emitter only; never change the shared model config."""
    if "d1_component_trial" in config:
        return config
    try:
        value = os.environ.get(SWITCH)
        if value is None:
            path = RECEIPTS / "trial.json"
            if not path.is_file():
                return config
            value = path.read_text(encoding="utf-8-sig")
        if not value:
            return config
        trial = json.loads(value)
        if not isinstance(trial,dict):
            return config
        # Deployment switches can select dates, not arbitrary filesystem paths.
        return {**config, "d1_component_trial": {k:trial.get(k) for k in ("policy","targets")}}
    except (OSError,ValueError,UnicodeError):
        return config

def shift(point, delta):
    from python.forecast.baseline import HourlyForecast
    return HourlyForecast(point.ts, *(round(getattr(point, k) + delta, 1) for k in
        ("forecast_mw", "p95_lower_mw", "p95_upper_mw", "p99_lower_mw", "p99_upper_mw")))

def local_time(value):
    t = datetime.fromisoformat(value)
    if t.utcoffset() is None:
        raise ValueError("timezone required")
    return t.astimezone(JST)

def origin_path(target):
    return Path("forecast_origins") / str(target) / (ARTIFACT + ".json")

def compatible_origin(raw, target, published_by):
    q = json.loads(raw)
    generated = local_time(q["generatedAt"])
    model = q["model"]
    return (q["targetDate"] == str(target) and generated.date() == target-timedelta(days=1)
            and generated <= published_by and model.get("artifactSha256") == ARTIFACT
            and (q.get("origin") or {}).get("type") == "day_ahead_first_publish"
            and (q.get("origin") or {}).get("immutable") is True)

def requested(config, target):
    trial = config.get("d1_component_trial")
    if not isinstance(trial, dict) or trial.get("policy") != FINGERPRINT:
        return False
    targets = trial.get("targets")
    return (isinstance(targets, list) and str(target) in APPROVED_TARGETS
            and all(isinstance(t, str) and t in APPROVED_TARGETS for t in targets)
            and str(target) in targets)

def choose(build, config, target, issued_at, out_dir):
    if not requested(config, target):
        return build
    from python.forecast.rolling_interval_calibration import serving_policy_fingerprint
    try:
        now = local_time(issued_at)
        if target != now.date()+timedelta(days=1) or build.model_name != "lgbm_quantile_q50" or serving_policy_fingerprint(config) != BASE:
            return build
        model = json.loads((out_dir / ".lgbm_model_meta.json").read_text(encoding="utf-8"))
        if model.get("artifactSha256") != ARTIFACT:
            return build
        directory = Path(config["d1_component_trial"].get("receipt_dir", RECEIPTS))
        if directory.resolve().is_relative_to(out_dir.resolve()):
            raise ValueError("receipt must be outside public data")
        proof = json.loads((directory / (str(target)+".json")).read_text(encoding="utf-8"))
        published_by = local_time(proof["publishedBy"])
        if not (proof["schema"] == "d1-first-public/1" and proof["date"] == str(target) and proof["priorPolicy"] == BASE
                and published_by.date() == now.date() and published_by < now):
            return build
        origin = (out_dir / origin_path(target)).read_bytes()
        # Windows git checkout may materialize an LF public blob with CRLF.
        hashes = {hashlib.sha256(buf).hexdigest() for buf in (origin, origin.replace(b"\r\n", b"\n"))}
        if proof["originSHA256"] not in hashes or not compatible_origin(origin,target,published_by):
            return build
        raw, stock = build.stages["raw_lgbm"], build.forecasts
        if len(stock) != 24 or len(raw) != 24 or any(a.ts != b.ts or not math.isfinite(b.forecast_mw) for a,b in zip(stock,raw)):
            raise ValueError("invalid candidate curve")
        effective = [shift(a,b.forecast_mw-a.forecast_mw) for a,b in zip(stock,raw)]
        meta = dict(version=EDITION,mode="raw",scope="updates",fingerprint=FINGERPRINT,referencePolicy=BASE,
                    originCommit=proof["commit"],referenceMw=[p.forecast_mw for p in stock])
        writer=os.environ.get("TOKYO_GRID_EMS_D1_WRITER")
        meta["writer"]=writer if writer in ("windows-etl","github-intraday","github-manual-etl") else None
        return replace(build,forecasts=effective,stages={**build.stages,"incumbent_pre_calibration":stock,
            "d1_component_point":effective,"pre_calibration":effective},metadata={**build.metadata,"d1PointPolicy":meta})
    except (OSError,ValueError,KeyError,TypeError,OverflowError,AttributeError):
        return build

def interval_role(snapshot, requested_policy):
    if snapshot.get("servingPolicyFingerprint") == requested_policy:
        return "forecastMw"
    meta = snapshot.get("d1PointPolicy") or {}
    if (requested_policy == BASE and snapshot.get("servingPolicyFingerprint") == FINGERPRINT
            and isinstance(meta, dict) and meta.get("referencePolicy") == BASE
            and meta.get("version") == EDITION and meta.get("fingerprint") == FINGERPRINT
            and (snapshot.get("model") or {}).get("artifactSha256") == ARTIFACT):
        return "intervalReferenceForecastMw"
    return None
