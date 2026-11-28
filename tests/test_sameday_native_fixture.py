"""Optional native integration on disposable public copies; never runs a live ETL."""

from datetime import datetime
import json
import os
import hashlib
import shutil
import socket
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import yaml
from python.etl import fetch_today, fetch_weather
from scripts import sameday_refresh as s
from python.observability.public import project


@pytest.mark.skipif(
    not all(
        os.getenv(k)
        for k in ("TGEMS_NATIVE_FIXTURE", "TGEMS_D0_DELTA", "TGEMS_NEXT_RECEIPT")
    ),
    reason="requires pinned public inputs and research-only TEPCO receipt",
)
def test_first_regular_update_after_supplementary_issue(tmp_path, monkeypatch):
    base = Path(os.environ["TGEMS_NATIVE_FIXTURE"])
    delta = Path(os.environ["TGEMS_D0_DELTA"])
    receipt = Path(os.environ["TGEMS_NEXT_RECEIPT"])
    source = s.read(receipt)
    assert source["status"] == "valid"
    key = source["sha256"]
    body = (receipt.parents[2] / "blobs" / key[:2] / (key + ".csv")).read_bytes()
    assert hashlib.sha256(body).hexdigest() == key
    txt = body.decode("cp932")
    meta = s.read(delta / "ops/same_day/latest.json")
    assert (
        meta["baseSha"] == s.git(base, "rev-parse", "HEAD")
        and meta["scope"] == "same_day_only"
    )
    at = datetime.fromisoformat(source["received"])
    assert (
        datetime.fromisoformat(meta["statusAt"]) < at and str(at.date()) == meta["date"]
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.replace(tzinfo=None)

    monkeypatch.setattr(s.rb, "datetime", Clock)
    monkeypatch.setattr(fetch_today, "datetime", Clock)
    monkeypatch.setattr(fetch_today, "fetch_csv", lambda: txt)
    monkeypatch.setattr(fetch_weather, "enrich_cache_with_weather", lambda cache: cache)
    monkeypatch.setattr(
        s.rb, "_extend_cache_with_forecast_weather", lambda cache, days: cache
    )

    def no_network(*a, **kw):
        pytest.fail("isolated transition attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = []
    cfg = yaml.safe_load((s.ROOT / "config.yaml").read_bytes())
    for label in ("unchanged", "supplementary"):
        root = tmp_path / label
        shutil.copytree(base, root, ignore=shutil.ignore_patterns(".git"))
        if label == "supplementary":
            shutil.copytree(delta, root, dirs_exist_ok=True)
        state = (root / ".etl_state.json").read_bytes()
        before = s.read(root / "forecast/2026-11-28.json")
        s.rb._run_status_only(root, cfg)
        after = s.read(root / "forecast/2026-11-28.json")
        actual = s.read(root / "actual/2026-11-28.json")
        for orig, got, obs in zip(
            before["series"], after["series"], actual["series"], strict=True
        ):
            if obs["actualSource"] == "observed":
                assert orig == got
        assert state == (root / ".etl_state.json").read_bytes()
        if label == "supplementary":
            for rel in (
                x.relative_to(delta) for x in (delta / "ops/same_day").rglob("*.json")
            ):
                assert (root / rel).read_bytes() == (delta / rel).read_bytes()
        t = s.read(root / "forecast/2026-11-29.json")
        result.append(
            (t["series"], t.get("d1PointPolicy"), t["servingPolicyFingerprint"], actual)
        )
    assert result[0] == result[1]


@pytest.mark.skipif(
    not os.getenv("TGEMS_NATIVE_FIXTURE"),
    reason="supply an isolated public data checkout",
)
def test_pinned_native_noop_weather_only_and_reader(tmp_path):
    base = Path(os.environ["TGEMS_NATIVE_FIXTURE"])
    sha = s.git(base, "rev-parse", "HEAD")
    assert sha == "91dcba73fa2bd0016601957ead088d74d80b7d80"
    cfg = yaml.safe_load((s.ROOT / "config.yaml").read_bytes())
    d = "2026-11-28"
    f = d + ".json"
    p = s.read(base / "forecast" / f)
    t = datetime.fromisoformat(p["intervalCalibration"]["issuedAt"])
    actual = s.read(base / "actual" / f)

    def num(v, unit=1):
        return "" if v is None else str(v / unit)

    text = (
        "DATE,TIME,ACTUAL,FC,PCT,SUPPLY\n"
        + "\n".join(
            ",".join(
                [
                    d.replace("-", "/"),
                    r["ts"][11:16],
                    num(r["actualMw"], 10),
                    num(r["tepcoForecastMw"], 10),
                    num(r["usagePct"]),
                    num(r["supplyMw"], 10),
                ]
            )
            for r in actual["series"]
        )
        + "\n"
    )
    cache = s.rb.load_hourly_cache(base).set_index("ts")

    def refresh(probe, days):
        new = probe.set_index("ts").copy()
        cols = [
            "temp_c",
            "apparent_temp_c",
            "humidity_pct",
            "discomfort_index",
            "weather_source",
        ]
        new.loc[cache.index, cols] = cache[cols]
        return new.reset_index()

    noop = tmp_path / "noop"
    with patch.object(
        s.rb, "_try_load_lgbm", side_effect=AssertionError("noop ran inference")
    ):
        assert (
            s.compute(
                base,
                noop,
                sha,
                text.encode(),
                t,
                cfg,
                refresh_weather=refresh,
                clock=lambda: t,
            )
            == "no_change"
        )
    assert not noop.exists()

    def shift(probe, days):
        v = refresh(probe, days)
        v.loc[(v.ts.dt.date == t.date()) & (v.ts.dt.hour == 18), "temp_c"] += 1
        return v

    dest = tmp_path / "new"
    assert (
        s.compute(
            base,
            dest,
            sha,
            text.encode(),
            t,
            cfg,
            refresh_weather=shift,
            clock=lambda: t,
        )
        == "changed"
    )
    assert len(list(dest.rglob("*.json"))) == 6
    for name in ("tomorrow", "coverageTo", "yesterday"):
        assert s.read(base / "status.json")[name] == s.read(dest / "status.json")[name]
    assert s.read(dest / "actual" / f) == actual

    def reader(path, limit):
        raw = ((dest / path) if (dest / path).is_file() else base / path).read_bytes()
        assert len(raw) <= limit
        return json.loads(raw)

    telemetry = project(reader, t)
    assert telemetry["tgems_quality_samples"] == [
        (24, {"basis": "published", "window": "day"})
    ]
    assert telemetry["tgems_public_slots"][0][0] == sum(
        v["actualSource"] == "observed" for v in actual["series"]
    )
    assert s.git(base, "status", "--porcelain") == ""
