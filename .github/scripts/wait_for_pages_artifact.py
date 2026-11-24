"""Wait for the upload from this workflow attempt before handing off to Pages."""
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class GateError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def visible(payload, artifact_id, name):
    artifacts = [row for row in payload["artifacts"] if row["name"] == name]
    if not artifacts:
        return False
    if len(artifacts) != 1 or payload["total_count"] > 1 or artifacts[0]["id"] != artifact_id:
        raise GateError("Unexpected Pages artifact ID or duplicate name for this attempt")
    artifact = artifacts[0]
    if artifact["expired"]:
        raise GateError("Pages artifact already expired")
    return artifact["size_in_bytes"] > 0


def wait_for_artifact(lookup, artifact_id, name, *, timeout=90, interval=5,
                      now=time.monotonic, sleep=time.sleep):
    deadline = now() + timeout
    previous = False
    while (remaining := deadline - now()) > 0:
        try:
            ready = visible(lookup(min(8, remaining)), artifact_id, name)
        except HTTPError as exc:
            if exc.code not in (404, 408, 429) and not 500 <= exc.code < 600:
                raise GateError(f"GitHub artifact lookup rejected: HTTP {exc.code}") from None
            ready = False
        except (URLError, TimeoutError):
            ready = False
        # A second observation gives deploy-pages' separate artifact service
        # time to catch up. Do not retry deployment creation itself.
        if ready and previous and now() <= deadline:
            return
        previous = ready
        if (remaining := deadline - now()) > 0:
            sleep(min(interval, remaining))
    raise GateError("Pages artifact was not confirmed within the lookup window")


def main():
    api = os.environ["GITHUB_API_URL"]
    repo = os.environ["GITHUB_REPOSITORY"]
    run = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    artifact_id = os.environ["PAGES_ARTIFACT_ID"]
    name = os.environ["PAGES_ARTIFACT_NAME"]
    if (api != "https://api.github.com" or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo, re.ASCII)
            or not all(re.fullmatch(r"[1-9][0-9]*", n) for n in (run, attempt, artifact_id))
            or name != f"github-pages-{attempt}"):
        raise GateError("Missing or unexpected GitHub Pages artifact identity")
    url = f"{api}/repos/{repo}/actions/runs/{run}/artifacts?" + urlencode({"name": name})
    request = Request(url, headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                                    "Accept": "application/vnd.github+json"})
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def lookup(timeout):
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise GateError("Unexpectedly large artifact metadata")
        return json.loads(raw)

    wait_for_artifact(lookup, int(artifact_id), name)
    print(f"Confirmed {name} (ID {artifact_id}) for workflow run {run}")


if __name__ == "__main__":
    try:
        main()
    except (GateError, KeyError, TypeError, ValueError) as exc:
        sys.exit(str(exc) if isinstance(exc, GateError) else "Invalid GitHub artifact input or metadata")
