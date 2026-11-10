"""Credential-free public sources for the observability process only."""
import json
import math
import re
import time
import urllib.request
from datetime import datetime

REPO = "wonhongChang/tokyo-grid-ems"
API = "https://api.github.com/repos/" + REPO
PAGES = "https://wonhongchang.github.io/tokyo-grid-ems/"
DATE_PATH = re.compile(r"(actual|reports/daily)/\d{4}-\d{2}-\d{2}\.json")
_traffic = [0, 0]  # External HTTPS attempts and response body bytes; excludes OTLP/TLS.


def traffic():
    return tuple(_traffic)


def allowed(path):
    return path in ("status.json", ".etl_state.json", "metrics/forecast_accuracy.json") or bool(DATE_PATH.fullmatch(path))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url, limit, *, timeout=6):
    # Do not use the user's Git configuration, cookies, .netrc, or proxy credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    _traffic[0] += 1
    with opener.open(url, timeout=timeout) as response:
        data = response.read(limit + 1)
        _traffic[1] += len(data)
    if len(data) > limit:
        raise ValueError("public response too large")
    return data


class RemoteData:
    def __init__(self):
        self.sha = None
        self.docs = {}

    def reader(self):
        # The ref advertisement is public, small, and not an authenticated API
        # poll. Resolve once per projection, then use only immutable raw URLs.
        adv = fetch("https://github.com/" + REPO + "/info/refs?service=git-upload-pack", 1024 * 1024)
        refs = []
        pos = 0
        while pos < len(adv):
            header = adv[pos:pos + 4]
            if not re.fullmatch(b"[0-9a-fA-F]{4}", header):
                raise ValueError("invalid ref advertisement")
            size = int(header, 16)
            if size == 0:
                pos += 4
                continue
            if size < 4 or pos + size > len(adv):
                raise ValueError("invalid pkt-line")
            record = adv[pos + 4:pos + size].split(b"\0", 1)[0].rstrip(b"\n")
            if m := re.fullmatch(rb"([a-f0-9]{40}) refs/heads/data", record):
                refs.append(m[1].decode("ascii"))
            pos += size
        if len(refs) != 1:
            raise ValueError("no unique public data ref")
        sha = refs[0]
        if sha != self.sha:
            self.sha, self.docs = sha, {}
        cache = self.docs

        def read(path, limit):
            if not allowed(path):
                raise ValueError("unapproved public path")
            if path not in cache:
                cache[path] = fetch(f"https://raw.githubusercontent.com/{REPO}/{sha}/{path}", limit)
            if len(cache[path]) > limit:
                raise ValueError("public response too large")
            return json.loads(cache[path])
        return read


class PagesDeployment:
    """Newest confirmed success in a bounded public deployment history; not status.json age."""
    def __init__(self):
        self.next_check = 0
        self.latest = math.nan

    def read(self):
        if time.monotonic() < self.next_check:
            return self.latest
        self.next_check = time.monotonic() + 360
        self.latest = math.nan
        rows = json.loads(fetch(API + "/deployments?environment=github-pages&per_page=3", 131072))
        if not isinstance(rows, list):
            raise ValueError("invalid deployment list")
        successes = []
        for row in rows[:3]:
            ident = row.get("id")
            if type(ident) is not int or ident <= 0 or row.get("environment") != "github-pages":
                continue
            states = json.loads(fetch(f"{API}/deployments/{ident}/statuses?per_page=10", 131072))
            for state in states:
                if state.get("state") == "success" and state.get("environment_url") == PAGES:
                    dt = datetime.fromisoformat(state["created_at"])
                    if dt.tzinfo is not None:
                        successes.append(dt.timestamp())
        self.latest = max(successes, default=math.nan)
        return self.latest
