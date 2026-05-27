#!/usr/bin/env python3
"""Trigger a GitHub Actions workflow_dispatch event."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_capture(args: list[str]) -> str:
    return subprocess.check_output(args, cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL).strip()


def _repo_full_name() -> str:
    env_repo = os.getenv("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo

    remote = _run_capture(["git", "remote", "get-url", "origin"])
    patterns = [
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
        r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, remote)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    raise RuntimeError(f"Cannot infer GitHub repository from origin URL: {remote}")


def _token_from_git_credential() -> str:
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return ""
    for line in completed.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def _github_token() -> str:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.getenv(name)
        if token:
            return token.strip()

    try:
        token = _run_capture(["gh", "auth", "token"])
        if token:
            return token
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return _token_from_git_credential()


def dispatch(workflow: str, ref: str) -> None:
    repo = _repo_full_name()
    token = _github_token()
    if not token:
        raise RuntimeError(
            "No GitHub token found. Set GH_TOKEN/GITHUB_TOKEN, install gh, "
            "or ensure git credential manager can provide a GitHub token."
        )

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    body = json.dumps({"ref": ref}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 204:
                raise RuntimeError(f"Unexpected GitHub status: {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub workflow dispatch failed: HTTP {exc.code} {detail}") from exc
    print(f"[WORKFLOW] Dispatched {workflow} on {repo}@{ref}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default="deploy.yml")
    parser.add_argument("--ref", default="main")
    args = parser.parse_args()

    try:
        dispatch(args.workflow, args.ref)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
