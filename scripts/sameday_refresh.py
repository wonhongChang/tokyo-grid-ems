"""Generate a D0-only release delta outside a read-only, pinned public data tree."""

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
import yaml
from python.etl import run_batch as rb
from python.etl.fetch_today import parse_hourly
from python.forecast.feature_builder import build_inference_features
from python.etl import fetch_today as src
from scripts.pages_release import oid, plain_git_tree

HOURS = {2, 4, 14, 16, 18, 20, 22}
CHAMPION = "c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3"


def read(p):
    return json.loads(p.read_bytes())


def digest(x):
    return hashlib.sha256(
        json.dumps(x, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


def write(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(x, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf8"
    )


def git(base, *args):
    return subprocess.check_output(["git", "-C", str(base), *args], text=True).strip()


def valid_rows(rows, day, now):
    expected = [
        pd.Timestamp(day, tz=src.JST) + pd.Timedelta(hours=h) for h in range(24)
    ]
    if [pd.Timestamp(p["ts"]) for p in rows] != expected:
        raise ValueError("expected 24 ordered target-day slots")
    for p, ts in zip(rows, expected, strict=True):
        if p.get("actualMw") is not None:
            if (
                not math.isfinite(p["actualMw"])
                or p["actualMw"] <= 0
                or p.get("actualSource") not in ("observed", "tepco_forecast_fallback")
            ):
                raise ValueError("invalid actual or source")
            if p["actualSource"] == "observed" and ts + timedelta(hours=1) > now:
                raise ValueError("uncompleted observed hour")


def frame_key(frame):
    if (
        len(frame) != 24
        or frame.hour.tolist() != list(range(24))
        or not frame.temp_c.notna().all()
    ):
        raise ValueError("incomplete effective weather or forecast slots")
    # Time/source headers do not trigger inference. All native numeric feature
    # columns, including bias-corrected and derived weather, are compared.
    nums = frame.select_dtypes(include=["number", "bool"]).sort_index(axis=1)
    return hashlib.sha256(
        nums.to_json(orient="split", index=False, double_precision=15).encode()
    ).hexdigest()


def key(rows, features, policy):
    # Only observations and actual inference inputs justify an extra prediction.
    # Standalone reserve/usage/TEPCO-reference changes belong to the regular ETL.
    observed = [
        [p["ts"], p["actualMw"]] for p in rows if p.get("actualSource") == "observed"
    ]
    return digest([policy, CHAMPION, frame_key(features), observed])


def unchanged(old, current, receipt, baseline, forecast, status):
    if (
        receipt
        and receipt.get("forecastHash") == digest(forecast)
        and receipt.get("statusAt") == status["lastUpdatedAt"]
    ):
        return receipt.get("inputKey") == current
    return old == current and baseline


class History:
    """Existing native interval reader sees historical data plus the new D0 observations."""

    def __init__(self, base, scratch, day):
        self.base, self.scratch, self.day = base, scratch, day

    def __truediv__(self, k):
        if k != "actual":
            return self.base / k
        obj = self

        class Actual:
            def __truediv__(self, k):
                return (
                    (obj.scratch if k == f"{obj.day}.json" else obj.base) / "actual" / k
                )

        return Actual()


def compute(
    base,
    dest,
    base_sha,
    body,
    received,
    cfg,
    *,
    refresh_weather=rb._extend_cache_with_forecast_weather,
    clock=lambda: datetime.now(src.JST),
):
    dest = dest.resolve()
    base = base.resolve()
    if dest.exists() or base == dest or base in dest.parents or dest in base.parents:
        raise ValueError("output must be new and outside the input")
    if git(base, "rev-parse", "HEAD") != oid(base_sha) or git(
        base, "status", "--porcelain", "--untracked-files=all"
    ):
        raise ValueError("input must be a clean checkout of the specified data commit")
    plain_git_tree(base)
    day = received.astimezone(src.JST).date()
    ds = str(day)
    f = f"{day}.json"
    status = read(base / "status.json")
    inc = read(base / "forecast" / f)
    if (
        status["today"]["date"] != ds
        or inc.get("date") != ds
        or inc["model"].get("artifactSha256") != CHAMPION
    ):
        raise ValueError("rollover or champion mismatch")
    policy = rb.serving_policy_fingerprint(cfg)
    if (
        cfg.get("serving_calibration", {})
        .get("same_regime_day_level", {})
        .get("application")
        != "day_ahead_only"
    ):
        raise ValueError("unsupported change of D0 state contract")
    if inc.get("servingPolicyFingerprint") != policy:
        raise ValueError("incompatible serving policy")
    orig = read(base / "actual" / f)
    source_day, rows = parse_hourly(body if isinstance(body, str) else body.decode("cp932"), now=received)
    if source_day != ds:
        raise ValueError("stale source date")
    valid_rows(orig["series"], day, received)
    valid_rows(rows, day, received)
    if any(
        a.get("actualSource") == "observed" and b.get("actualSource") != "observed"
        for a, b in zip(orig["series"], rows, strict=True)
    ):
        raise ValueError("source observation regressed")
    prior_ts = pd.Timestamp(inc["intervalCalibration"]["issuedAt"])
    if prior_ts.date() != day or prior_ts > received:
        raise ValueError("baseline issue clock mismatch")
    if (base / f"ops/same_day/{ds}/{received.hour:02d}.json").exists():
        return "slot_already_published"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        scratch = Path(tmp)
        for i in range(8):
            dd = day - timedelta(days=i)
            for name in ("actual", "forecast") if i <= 1 else ("actual",):
                rel = Path(name) / f"{dd}.json"
                if (base / rel).is_file():
                    (scratch / name).mkdir(exist_ok=True)
                    shutil.copyfile(base / rel, scratch / rel)
        cache = rb.load_hourly_cache(base)
        orig_cache = rb._inject_today_actuals(
            scratch, day, cache, fallback_through=day - timedelta(days=1)
        )
        prev = rb._apply_weather_forecast_bias_correction(
            orig_cache, cfg, now=prior_ts.to_pydatetime()
        )
        old = key(
            orig["series"],
            build_inference_features(prev, day, cfg, include_context=True),
            policy,
        )
        write(scratch / "actual" / f, {**orig, "series": rows})
        observed = rb._inject_today_actuals(
            scratch, day, cache, fallback_through=day - timedelta(days=1)
        )
        # Do not let a partial upstream response pass by reusing cached forecast
        # weather in the very slots being tested for a change.
        probe = observed.copy()
        future = (
            (probe.ts.dt.date == day)
            & (probe.ts.dt.hour >= received.hour)
            & probe.actual_mw.isna()
        )
        weather_cols = [
            "temp_c",
            "apparent_temp_c",
            "humidity_pct",
            "discomfort_index",
            "weather_source",
        ]
        probe.loc[future, [k for k in weather_cols if k in probe]] = None
        display = refresh_weather(probe, days=3)
        remaining = display[
            (display.ts.dt.date == day) & (display.ts.dt.hour >= received.hour)
        ]
        if (
            display is probe
            or sorted(remaining.ts.dt.hour) != list(range(received.hour, 24))
            or remaining[weather_cols].isna().any().any()
        ):
            raise ValueError("weather refresh unavailable; not a no-change")
        issue = clock().astimezone(src.JST)
        if issue < received or issue.date() != day or issue.hour != received.hour:
            raise ValueError("input clock or expired slot")
        effective = rb._apply_weather_forecast_bias_correction(display, cfg, now=issue)
        fr = build_inference_features(effective, day, cfg, include_context=True)
        ink = key(rows, fr, policy)
        rpath = base / "ops" / "same_day" / "latest.json"
        receipt = read(rpath) if rpath.exists() else {}
        alerts_path = base / "alerts" / f
        complete = (
            alerts_path.is_file()
            and read(alerts_path).get("date") == ds
            and len(inc["series"]) == 24
        )
        if complete and unchanged(
            old, ink, receipt, inc.get("availability") == "ok", inc, status
        ):
            return "no_change"
        if (
            hashlib.sha256((base / ".lgbm_model.pkl").read_bytes()).hexdigest()
            != CHAMPION
        ):
            raise ValueError("untrusted model artifact")
        model = rb._try_load_lgbm(base)
        if model is None:
            raise ValueError("model unavailable; no fallback or training")
        ff = cfg["forecast"]
        built = rb._build_forecast_pipeline(
            model,
            effective,
            day,
            ff.get("n_weeks", 12),
            ff.get("min_samples_per_slot", 4),
            cfg,
            rb._make_adjuster(cfg),
            rb._make_guard(cfg),
            rb._make_midday_guard(cfg),
            rb._make_localized_shape_spike_guard(cfg),
            rb._make_same_regime_calibrator(cfg, scratch),
            issued_at=issue.isoformat(),
        )
        if "raw_lgbm" not in built.stages:
            raise ValueError("refusing fallback forecast")
        fc, name = rb._apply_intraday_residual_correction(
            scratch,
            day,
            built.forecasts,
            built.model_name,
            cfg,
            effective,
            stage_forecasts=built.stages,
        )
        diagnostic = read(
            scratch / "reports" / "internal" / "operational-calibration" / f
        )
        if len(diagnostic["hourlyDiagnostics"]) != 24:
            raise ValueError("missing native correction")
        fc, name = rb._freeze_observed_forecast_hours(scratch, day, fc, name, True)
        generated = clock().astimezone(src.JST)
        if generated.date() != day or generated.hour != issue.hour:
            raise ValueError("slot expired")
        pred = rb.build_forecast_json(
            day,
            fc,
            cfg,
            name,
            out_dir=History(base, scratch, day),
            generated_at=generated.isoformat(),
            preserve_observed_bands=True,
        )
        if len(pred["series"]) != 24 or pred["model"].get("artifactSha256") != CHAMPION:
            raise ValueError("bad forecast")
        for a, b, obs in zip(inc["series"], pred["series"], rows, strict=True):
            if obs["actualSource"] == "observed" and a != b:
                raise ValueError("observed forecast changed")
        write(scratch / "forecast" / f, pred)
        alerts = rb._build_today_alerts(
            scratch, day, cfg, day_context=rb._make_day_context(fr, cfg)
        )
        if alerts is None:
            raise ValueError("alerts unavailable")
        today_summary = rb.build_status_json(
            set(),
            set(),
            {},
            set(),
            day,
            fc,
            day + timedelta(days=1),
            [],
            cache,
            cfg,
            today_severity=rb._reserve_risk_severity_from_alerts_payload(alerts),
            extended_cache=effective,
            display_cache=display,
        )["today"]
        stamp = generated.isoformat()
        newstatus = {**status, "today": today_summary, "lastUpdatedAt": stamp}
        receipt = dict(
            version=1,
            scope="same_day_only",
            date=ds,
            slot=issue.hour,
            baseSha=base_sha,
            receivedAt=received.isoformat(),
            weatherCheckedAt=issue.isoformat(),
            statusAt=stamp,
            inputKey=ink,
            forecastHash=digest(pred),
            actualHash=digest(rows),
            model=CHAMPION,
            policy=policy,
        )
        payload = {
            "status.json": newstatus,
            "actual/" + f: read(scratch / "actual" / f),
            "forecast/" + f: pred,
            "alerts/" + f: alerts,
            "ops/same_day/latest.json": receipt,
            f"ops/same_day/{ds}/{issue.hour:02d}.json": dict(
                receipt=receipt, forecast=pred, actual=rows, calibration=diagnostic
            ),
        }
        staged = scratch / "delta"
        for rel, obj in payload.items():
            write(staged / rel, obj)
        staged.rename(dest)
        return "changed"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True, type=Path)
    p.add_argument("--sha", required=True)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    body = src.fetch_csv()
    end = datetime.now(src.JST)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_bytes())
    print(compute(a.base, a.out, a.sha, body, end, cfg))


if __name__ == "__main__":
    main()
