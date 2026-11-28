"""Release identity, idempotence and data-tip fencing. No model dependencies."""

import argparse
from datetime import date, datetime, timedelta
import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


def oid(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value or ""):
        raise ValueError("expected full commit SHA")
    return value


def remote_tip(branch="data", *, cwd=None):
    if branch not in {"data", "main"}:
        raise ValueError("unexpected branch")
    result = subprocess.check_output(
        ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"],
        text=True,
        cwd=cwd,
    )
    sha, ref = result.strip().split()
    if ref != f"refs/heads/{branch}":
        raise ValueError("unexpected data ref")
    return oid(sha)


def eligible(failed, latest, ancestor, live, code):
    oid(failed)
    oid(latest)
    oid(code)
    if not ancestor:
        raise ValueError("failed publication is not an ancestor of data tip")
    if live is not None:
        if not isinstance(live, dict) or live.get("schema") != 1:
            raise ValueError("unknown live marker format")
        if (oid(live.get("data")), oid(live.get("code"))) == (latest, code):
            return False
    return True


def output(key, value):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        print(f"{key}={value}", file=f)


def plain_git_tree(repo):
    entries = subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-rz", "HEAD"]
    ).split(b"\0")
    if any(x and x.split(b" ", 1)[0] not in {b"100644", b"100755"} for x in entries):
        raise ValueError("unsafe data tree entry")


def marker():
    # No auth to Pages. A transport failure is not proof of a missing release.
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
    url = f"https://{owner}.github.io/{repo}/ops/pages_release.json?attempt={os.environ['GITHUB_RUN_ID']}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read(2048))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # bootstrap: caller already proved failure after valid push
        raise


def status_receipt(sha, record=False):
    repo = os.environ["GITHUB_REPOSITORY"]
    code = oid(os.environ["GITHUB_SHA"])
    context = "tgems/pages-release"
    suffix = ("statuses/" + oid(sha)) if record else ("commits/" + oid(sha) + "/status")
    body = (
        json.dumps(
            dict(
                state="success",
                context=context,
                description="code:" + code,
                target_url=f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            )
        ).encode()
        if record
        else None
    )
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/" + suffix,
        data=body,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        obj = json.load(response)
    if record:
        return
    return any(
        s["context"] == context
        and s["state"] == "success"
        and s["description"] == "code:" + code
        for s in obj["statuses"]
    )


def verify_payload(root, today):
    load = lambda path: json.loads((root / path).read_bytes())
    status = load("status.json")
    updated = datetime.fromisoformat(status["lastUpdatedAt"])
    if (
        status["today"]["date"] != today
        or updated.tzinfo is None
        or str(updated.astimezone(ZoneInfo("Asia/Tokyo")).date()) != today
    ):
        raise ValueError("stale or incomplete release")
    if status["tomorrow"]["date"] != str(date.fromisoformat(today) + timedelta(days=1)):
        raise ValueError("invalid next-day target")
    for section in ("today", "tomorrow"):
        day = status[section]["date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("invalid target date")
        forecast = load(f"forecast/{day}.json")
        times = [f"{day}T{hour:02d}:00:00+09:00" for hour in range(24)]
        if (
            forecast["date"] != day
            or forecast["availability"] != "ok"
            or [r["ts"] for r in forecast["series"]] != times
        ):
            raise ValueError("incomplete release curve")
        for r in forecast["series"]:
            bounds = [
                r[k]
                for k in (
                    "p99LowerMw",
                    "p95LowerMw",
                    "forecastMw",
                    "p95UpperMw",
                    "p99UpperMw",
                )
            ]
            if any(
                type(v) not in (float, int) or not math.isfinite(v) for v in bounds
            ) or bounds != sorted(bounds):
                raise ValueError("invalid forecast or intervals")
    ac = load(f"actual/{today}.json")
    if ac["date"] != today or [r["ts"] for r in ac["series"]] != [
        f"{today}T{h:02d}:00:00+09:00" for h in range(24)
    ]:
        raise ValueError("inconsistent observation date")


def descendant(base, tip):
    if base == tip:
        return True
    # Avoid fetching the full multi-year data branch merely to compare two SHAs.
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/compare/{oid(base)}...{oid(tip)}?per_page=1",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        info = json.load(response)
    return (
        info.get("status") == "ahead"
        and info.get("merge_base_commit", {}).get("sha") == base
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "action",
        choices=("select", "stamp", "fence", "fence-release", "ack", "check-current"),
    )
    p.add_argument("sha")
    a = p.parse_args()
    sha = oid(a.sha)
    if a.action in {"fence", "fence-release"}:
        if remote_tip() != sha or (
            a.action == "fence-release"
            and remote_tip("main") != oid(os.environ["GITHUB_SHA"])
        ):
            raise SystemExit("base changed; do not deploy stale inputs")
    elif a.action == "ack":
        status_receipt(sha, record=True)
    elif a.action == "check-current":
        # Primary delivery is never blocked just because optional dedup telemetry is down.
        try:
            live = marker()
            known = bool(
                live
                and not eligible(sha, sha, True, live, os.environ["GITHUB_SHA"])
                and status_receipt(sha)
            )
        except (OSError, ValueError, KeyError):
            known = False
        output("skip", str(known).lower())
    elif a.action == "stamp":
        dest = Path("web/dist/ops/pages_release.json")
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(
            json.dumps(
                {"schema": 1, "data": sha, "code": oid(os.environ["GITHUB_SHA"])}
            ),
            encoding="utf-8",
        )
    else:
        tip = remote_tip()
        # Recovery checks out the data branch with history into data-wt. Its contents are data, never code.
        if (
            subprocess.check_output(
                ["git", "-C", "data-wt", "rev-parse", "HEAD"], text=True
            ).strip()
            != tip
        ):
            raise SystemExit("data changed during restore")
        plain_git_tree("data-wt")
        verify_payload(
            Path("data-wt"), str(datetime.now(ZoneInfo("Asia/Tokyo")).date())
        )
        if remote_tip("main") != oid(os.environ["GITHUB_SHA"]):
            raise SystemExit("refuse recovery with superseded dashboard code")
        live = marker()
        if (
            live
            and live.get("data") != tip
            and not descendant(oid(live.get("data")), tip)
        ):
            raise SystemExit("refuse to replace a newer or unrelated live release")
        run = eligible(sha, tip, descendant(sha, tip), live, os.environ["GITHUB_SHA"])
        if (
            run
            and live
            and live.get("code") == os.environ["GITHUB_SHA"]
            and status_receipt(tip)
        ):
            # Under the fenced, tip-only release policy this revision was already
            # deployed; a still-old CDN marker is not reason for a second deployment.
            run = False
        output("needed", str(run).lower())
        output("sha", tip)


if __name__ == "__main__":
    main()
