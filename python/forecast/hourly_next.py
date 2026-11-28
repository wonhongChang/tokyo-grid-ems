"""Optional SD-H1-P50 pre-start issue. Never feeds a native forecast or interval."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
IDENTITY = "753f7a732df26f42bb7a4f8c20370ccc8bcbc97628967a93015c229ab5ebd4d7"
WEIGHTS = "d2420c84815b5d1d3daa775fa8a6dc7d0ffe7f52d54eafe3f0d15a64e35f6d26"
NATIVE = "c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3"
POLICY = "ba4d14312e56659c46a87b8e9c13750b51e93334dcb59661b8d37e6f2d0647bc"
BANDS = ("p95LowerMw", "p95UpperMw", "p99LowerMw", "p99UpperMw")
LEDGER = Path("ops/hourly-next")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def moment(value):
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError("timezone required")
    return t.astimezone(JST)


def load_model():
    import lightgbm
    raw = Path(__file__).with_name("sd-h1-p50.lgb").read_bytes()
    if hashlib.sha256(raw).hexdigest() != WEIGHTS:
        raise ValueError("hourly model hash mismatch")
    return lightgbm.Booster(model_str=raw.decode("ascii"))


def observed(series, cutoff):
    rows = {}
    for row in series:
        if row.get("actualSource") != "observed" or row.get("actualMw") is None:
            continue
        t = moment(row["ts"])
        v = row["actualMw"]
        if (t.date() != cutoff.date() or t.minute or t.second or t.microsecond or
                t.hour >= cutoff.hour or t.hour in rows or type(v) not in (float, int) or not math.isfinite(v) or v <= 0):
            raise ValueError("invalid completed hour")
        rows[t.hour] = v
    return rows


def propose(native, actual, snap, cal, model):
    import jpholiday
    import numpy as np
    t = moment(snap["generatedAt"])
    day, m = t.date(), t.hour
    if not 1 <= m <= 22 or t.minute < 10 or snap["runType"] not in ("intraday", "intraday_refresh", "etl"):
        return None
    if not (native["date"] == actual["date"] == snap["targetDate"] == cal["date"] == str(day)
            and native["availability"] == actual["availability"] == "ok"
            and native["model"]["artifactSha256"] == snap["model"]["artifactSha256"] == NATIVE
            and native["servingPolicyFingerprint"] == snap["servingPolicyFingerprint"] == POLICY
            and 0 <= (t - moment(cal["generatedAt"])).total_seconds() <= 180):
        return None
    obs = observed(actual["series"], t)
    if m-1 not in obs or obs != observed(cal["hourlyDiagnostics"], t) or snap["observationSummary"]["lastObservedActualHour"] != m-1:
        return None
    h = m+1
    start = t.replace(hour=h, minute=0, second=0, microsecond=0)
    point, diag, stage = native["series"][h], cal["hourlyDiagnostics"][h], snap["forecastBuild"]["series"][h]["forecastMwByStage"]
    if (len(native["series"]) != 24 or moment(point["ts"]) != start or point["ts"] != diag["ts"]
            or any(snap["series"][h][key] != point[key] for key in ("ts", "forecastMw", *BANDS))
            or diag["postCalibrationForecastMw"] != point["forecastMw"]
            or diag["forecastMwByStage"]["raw_lgbm"] != stage["raw_lgbm"] or diag["preCalibrationForecastMw"] != stage["pre_calibration"]):
        return None
    base = point["forecastMw"]
    lo, hi, outer_lo, outer_hi = (point[key] for key in BANDS)
    if not 0 <= outer_lo <= lo <= base <= hi <= outer_hi or not math.isfinite(outer_hi):
        return None
    hol = int(jpholiday.is_holiday(day))
    angle = 2*np.pi*day.timetuple().tm_yday/365.25
    v = [day.month, day.weekday(), hol, int(hol or day.weekday() >= 5), np.sin(angle), np.cos(angle),
         m, 1, (t.minute-10)//5*5, obs[m-1], obs[m-1]-obs.get(m-2, np.nan), obs.get(m-2, np.nan)-obs.get(m-3, np.nan)]
    direct = obs[m-1] + 1000*float(model.predict(np.array([v]), num_threads=1)[0])
    center = round((base+direct)/2, 1)
    if not math.isfinite(center) or outer_lo+center-base < 0:
        return None
    return dict(schema=1, model="SD-H1-P50", identity=IDENTITY, nativeGeneratedAt=t.isoformat(), targetStart=start.isoformat(),
                targetEnd=(start+timedelta(hours=1)).isoformat(), nativeSha256=digest(native), actualSha256=digest(actual),
                calibrationSha256=digest(cal), lastObservedStart=start.replace(hour=m-1).isoformat(), championMw=base, forecastMw=center,
                bands={key:round(point[key]+center-base, 1) for key in BANDS})


def seal(out, native, actual, snapshot, calibration, *, clock=lambda: datetime.now(JST), model=None):
    t = moment(snapshot["generatedAt"])
    now = clock()
    if not (t <= now < t.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)):
        return None
    if not 1 <= t.hour <= 22 or t.minute < 10:
        return None
    result = propose(native, actual, snapshot, calibration, model if model is not None else load_model())
    if result is None:
        return None
    origin = digest(result)
    path = out / LEDGER / str(t.date()) / (t.strftime("%H%M%S-%f")+".json")
    if path.exists():
        old = json.loads(path.read_bytes())
        if old["sha256"] != digest(old["record"]) or old["record"]["origin"] != origin:
            raise ValueError("immutable issue collision")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    recorded = clock()
    if not t <= recorded < moment(result["targetStart"]):
        return None
    record = dict(**result, origin=origin, issuedAt=recorded.isoformat())
    payload = json.dumps(dict(record=record, sha256=digest(record)), allow_nan=False, separators=(",", ":")).encode()
    with path.open("xb") as f:
        f.write(payload)
    return path


def switch(env):
    # Actions has loose cross-type equality. Preserve JSON null vs "" vs "0"
    # until here; only an explicitly opted-in regular job gets a default-on.
    if env.get("TGEMS_H1_REGULAR") != "1":
        return False, "outside_regular"
    raw = env.get("TGEMS_H1_ISSUE")
    if "TGEMS_H1_SETTING_JSON" in env:
        try:
            raw = json.loads(env["TGEMS_H1_SETTING_JSON"])
        except ValueError:
            return False, "invalid"
    if raw is None:
        return True, "default_unset"
    if raw == "":
        return True, "default_empty"
    return (True, "enabled") if raw == "1" else (False, "disabled" if raw == "0" else "invalid")


def regular(out, native, snapshot):
    enabled, source = switch(os.environ)
    if source == "outside_regular" or native["date"] != snapshot["generatedAt"][:10]:
        return
    at = moment(snapshot["generatedAt"])
    target = at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    state = "disabled" if not enabled else "waiting"
    issue = None
    try:
        if enabled and 1 <= at.hour <= 22 and at.minute >= 10 and snapshot["observationSummary"]["lastObservedActualHour"] == at.hour-1:
            state = "missed"
            day = native["date"]+".json"
            native = json.loads((out/"forecast"/day).read_bytes())
            actual = json.loads((out/"actual"/day).read_bytes())
            cal = json.loads((out/"reports/internal/operational-calibration"/day).read_bytes())
            path = seal(out, native, actual, snapshot, cal)
            if path:
                issue = json.loads(path.read_bytes())["sha256"]
                state = "recorded"
    finally:
        path = out/"ops"/"hourly-next-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(schema=1, identity=IDENTITY, runAt=at.isoformat(),
            targetStart=target.isoformat(), switch=source, state=state, issueId=issue)), encoding="utf8")
        print(f"[H1] switch={source} state={state} run={at.isoformat()} issue={issue or '-'}")
