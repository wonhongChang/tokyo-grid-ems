"""Reconstruct features from immutable issue-time snapshots, never final labels."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

import jpholiday
import numpy as np
import pandas as pd

from . import CONTRACT

JST = timezone(timedelta(hours=9))
FEATURES = (
    "target_hour", "weekday", "non_business", "business_return", "issue_hour", "issue_minute",
    "lead_minutes", "last_observed_hour", "observed_count", "observation_age_minutes",
    "raw", "pre", "champion", "raw_delta", "raw_next_delta", "raw_span_2h",
    "raw_from_latest_delta", "pre_delta", "champion_delta", "pre_minus_raw", "post_minus_pre",
    "latest_actual", "actual_to_raw_ratio", "observed_range", "latest_from_peak", "latest_from_trough",
    "actual_delta_1", "actual_delta_2", "actual_delta_3", "actual_delta_mean",
    "raw_residual_1", "raw_residual_2", "raw_residual_3", "raw_residual_4",
    "raw_residual_mean", "raw_residual_median", "raw_residual_trend", "raw_residual_acceleration",
    "raw_residual_abs_trend", "raw_residual_sign_persistence", "pre_residual_mean", "post_residual_mean",
    "slope_disagreement", "lag24_delta", "same_business_delta", "recorded_base_adjustment",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def implementation_sha(path):
    """Git may use CRLF on Windows; source identity ignores that conversion only."""
    return sha(Path(path).read_bytes().replace(b'\r\n', b'\n'))


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Timezone is required")
    return dt.astimezone(JST)


def non_business(day):
    return int(day.weekday() >= 5 or bool(jpholiday.is_holiday(day)))


def stage(row, name):
    values = row.get("forecastMwByStage", {})
    if name == "raw":
        return number(values.get("raw_lgbm"))
    if name == "pre":
        return number(row.get("preCalibrationForecastMw", values.get("pre_calibration")))
    return number(row.get("postCalibrationForecastMw"))


def difference(a, b):
    return a - b if a is not None and b is not None else None


def average(values):
    v = [x for x in values if x is not None]
    return float(np.mean(v)) if v else None


def features(snapshot):
    """Return prospective rows. Actuals beyond the recorded cutoff are ignored.

    Hour h denotes [h,h+1); its complete observation cannot be used before h+1.
    Diagnostics of past hours are same-run context, not original forecast vintages.
    """
    issue = timestamp(snapshot["generatedAt"])
    day = datetime.fromisoformat(snapshot["date"]).date()
    if issue.date() != day:
        raise ValueError("Only same-day snapshots are supported")
    rows = {int(r["hour"]): r for r in snapshot.get("hourlyDiagnostics", [])}
    if len(rows) != len(snapshot.get("hourlyDiagnostics", [])):
        raise ValueError("Duplicate target hours")
    cutoff = number(snapshot.get("correction", {}).get("lastObservedHour"))
    observed = {}
    for h, row in rows.items():
        actual = number(row.get("actualMw"))
        ts = timestamp(row["ts"])
        if ts.date() != day or ts.hour != h:
            raise ValueError("Hour/timestamp mismatch")
        if cutoff is not None and h <= cutoff and ts + timedelta(hours=1) <= issue and row.get("actualSource") == "observed" and actual is not None:
            observed[h] = actual
    last = max(observed) if observed else None
    latest = observed.get(last)
    deltas = [difference(observed.get(last - i), observed.get(last - i - 1)) if last is not None else None for i in range(3)]
    residuals = {}
    for name in ("raw", "pre", "champion"):
        residuals[name] = [difference(observed.get(last - i), stage(rows.get(last - i, {}), name)) if last is not None else None for i in range(4)]
    r = residuals["raw"]
    valid_r = [x for x in r if x is not None]
    latest_raw = stage(rows.get(last, {}), "raw") if last is not None else None
    for h, row in sorted(rows.items()):
        target = timestamp(row["ts"])
        lead = (target - issue).total_seconds() / 60
        raw, pre, post = (stage(row, n) for n in ("raw", "pre", "champion"))
        if lead <= 0 or any(v is None for v in (raw, pre, post)):
            continue
        raw_delta = difference(raw, stage(rows.get(h - 1, {}), "raw"))
        f = {
            "target_hour": h, "weekday": day.weekday(), "non_business": non_business(day),
            "business_return": int(not non_business(day) and non_business(day - timedelta(days=1))),
            "issue_hour": issue.hour, "issue_minute": issue.minute + issue.second / 60,
            "lead_minutes": lead, "last_observed_hour": last, "observed_count": len(observed),
            "observation_age_minutes": (issue - timestamp(rows[last]["ts"]) - timedelta(hours=1)).total_seconds() / 60 if last is not None else None,
            "raw": raw, "pre": pre, "champion": post, "raw_delta": raw_delta,
            "raw_next_delta": difference(stage(rows.get(h + 1, {}), "raw"), raw),
            "raw_span_2h": difference(stage(rows.get(h + 2, {}), "raw"), raw),
            "raw_from_latest_delta": difference(raw, latest_raw),
            "pre_delta": difference(pre, stage(rows.get(h - 1, {}), "pre")),
            "champion_delta": difference(post, stage(rows.get(h - 1, {}), "champion")),
            "pre_minus_raw": pre - raw, "post_minus_pre": post - pre,
            "latest_actual": latest, "actual_to_raw_ratio": latest / latest_raw if latest_raw and latest is not None else None,
            "observed_range": max(observed.values()) - min(observed.values()) if observed else None,
            "latest_from_peak": latest - max(observed.values()) if observed else None,
            "latest_from_trough": latest - min(observed.values()) if observed else None,
            "actual_delta_1": deltas[0], "actual_delta_2": deltas[1], "actual_delta_3": deltas[2], "actual_delta_mean": average(deltas),
            **{f"raw_residual_{i + 1}": v for i, v in enumerate(r)},
            "raw_residual_mean": average(r), "raw_residual_median": float(np.median(valid_r)) if valid_r else None,
            "raw_residual_trend": difference(r[0], r[1]),
            "raw_residual_acceleration": difference(difference(r[0], r[1]), difference(r[1], r[2])),
            "raw_residual_abs_trend": difference(abs(r[0]) if r[0] is not None else None, abs(r[1]) if r[1] is not None else None),
            "raw_residual_sign_persistence": average([int(np.sign(v) == np.sign(r[0])) for v in valid_r]) if r[0] is not None else None,
            "pre_residual_mean": average(residuals["pre"]), "post_residual_mean": average(residuals["champion"]),
            "slope_disagreement": difference(deltas[0], difference(latest_raw, stage(rows.get(last - 1, {}), "raw"))) if last is not None else None,
            "lag24_delta": number(row.get("lag24DeltaMw")), "same_business_delta": number(row.get("recentSameBusinessTypeDeltaMw")),
            "recorded_base_adjustment": number(snapshot.get("correction", {}).get("baseAdjustmentMw")),
        }
        yield {"date": day.isoformat(), "hour": h, "issued_at": issue.isoformat(), "target": target.isoformat(),
               "raw": raw, "pre": pre, "champion": post, "lead_minutes": lead, "features": f,
               "actual_cutoff": last, "feature_observed_hours": sorted(observed),
               "snapshot_model": snapshot.get("model"), "model_artifact": None, "serving_policy": None}


def read_sealed(root, ref):
    root = Path(root).resolve()
    p = (root / ref["path"]).resolve()
    if not p.is_relative_to(root) or p.suffix != ".json" or p.is_symlink():
        raise ValueError("Source outside input root")
    b = p.read_bytes()
    if sha(b) != ref["sha256"]:
        raise ValueError("Source hash mismatch")
    return json.loads(b)


def dataset(root, manifest_sha):
    root = Path(root)
    b = (root / "manifest.json").read_bytes()
    if sha(b) != manifest_sha:
        raise ValueError("Input manifest hash mismatch")
    m = json.loads(b)
    asof = timestamp(m["asOf"])
    labels = {}
    for day, ref in sorted(m["actuals"].items()):
        a = read_sealed(root, ref)
        if a.get('date') != day or ref.get('state') not in ('finalized', 'provisional', 'unavailable'):
            raise ValueError("Actual identity/state mismatch")
        labels[day] = {timestamp(x["ts"]).hour: number(x.get("actualMw")) for x in a.get("series", [])
                       if x.get("actualSource") != "tepco_forecast_fallback" and timestamp(x["ts"]) + timedelta(hours=1) <= asof}
    records = []
    seen = set()
    for ref in m["runs"]:
        s = read_sealed(root, ref)
        if timestamp(s["generatedAt"]) > asof:
            raise ValueError("Snapshot after experiment as-of")
        if s["date"] != ref["date"] or timestamp(s["generatedAt"]) != timestamp(ref["issuedAt"]):
            raise ValueError("Snapshot/manifest vintage mismatch")
        for r in features(s):
            key = (r["date"], r["issued_at"], r["hour"])
            if key in seen:
                raise ValueError("Duplicate issue-target row")
            seen.add(key)
            label = m["actuals"].get(r["date"])
            r.update(actual=labels.get(r["date"], {}).get(r["hour"]), actual_state=label["state"] if label else "unavailable",
                     source_sha=ref["sha256"], source_path=ref["path"], source_revision=ref.get("revision"),
                     source_pointer=f"/hourlyDiagnostics/{next(i for i, x in enumerate(s['hourlyDiagnostics']) if int(x['hour']) == r['hour'])}",
                     actual_sha=label["sha256"] if label else None, input_manifest_sha=manifest_sha,
                     contract=CONTRACT)
            records.append(r)
    return records


def frame(records, names=FEATURES):
    return pd.DataFrame([{k: r["features"].get(k) for k in names} for r in records], columns=names, dtype=float)


def closest(records, maximum=120):
    selected = {}
    for r in records:
        if 0 < r["lead_minutes"] <= maximum:
            key = (r["date"], r["hour"])
            if key not in selected or r["lead_minutes"] < selected[key]["lead_minutes"]:
                selected[key] = r
    return [selected[k] for k in sorted(selected)]
