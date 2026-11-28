#!/usr/bin/env python3
"""Publish generated web/public artifacts to the data branch."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO_ROOT / "web" / "public"
DATA_BRANCH = "data"
JST = ZoneInfo("Asia/Tokyo")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.public_artifact_security import check_tree, prepare
from scripts.hourly_delivery import protect
from scripts.pages_release import oid, remote_tip

def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd or REPO_ROOT, text=True, check=True)


def _push_with_retry(cwd: Path, base: str, attempts: int = 3) -> None:
    if subprocess.check_output(["git","rev-parse","HEAD^"],cwd=cwd,text=True).strip() != oid(base):
        raise ValueError("refusing non-child of restore commit")
    intended = subprocess.check_output(["git","rev-parse","HEAD"],cwd=cwd,text=True).strip()
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, attempts + 1):
        try:
            _run(["git","push",f"--force-with-lease=refs/heads/data:{base}","origin","HEAD:refs/heads/data"],cwd=cwd)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            tip = remote_tip(cwd=cwd)
            if tip == intended:
                return
            if tip != base:
                raise RuntimeError("data advanced; restore and recompute, never rebase stale outputs") from exc
            if attempt >= attempts:
                break
            wait_seconds = attempt * 5
            print(
                f"[WARN] data branch push failed on attempt {attempt}/{attempts}; "
                f"retrying in {wait_seconds}s",
                file=sys.stderr,
            )
            import time

            time.sleep(wait_seconds)
    assert last_error is not None
    raise last_error


def _clear_directory(path: Path) -> None:
    for child in path.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_public_to_worktree(worktree: Path) -> None:
    for child in PUBLIC_DIR.iterdir():
        target = worktree / child.name
        if child.is_dir():
            shutil.copytree(child, target, symlinks=True)
        else:
            shutil.copy2(child, target, follow_symlinks=False)


def _validate_public(min_yesterday_hours: int = 24) -> None:
    from scripts.validate_public_before_publish import validate

    result = validate(PUBLIC_DIR, min_yesterday_hours=min_yesterday_hours)
    print("[DATA] Publish validation passed: " + json.dumps(result, ensure_ascii=False, sort_keys=True))


def publish(
    commit_message: str | None = None,
    skip_validation: bool = False,
    min_yesterday_hours: int = 24,
    *, base: str | None = None,
) -> None:
    if not PUBLIC_DIR.exists():
        raise FileNotFoundError(f"Missing generated public directory: {PUBLIC_DIR}")
    check_tree(PUBLIC_DIR, scan_text=False)
    if not skip_validation:
        _validate_public(min_yesterday_hours=min_yesterday_hours)

    if remote_tip(cwd=REPO_ROOT) != oid(base):
        raise RuntimeError("data changed since restore; recompute before publication")
    timestamp = datetime.now(JST).strftime("%Y-%m-%dT%H:%M JST")
    message = commit_message or f"chore: local ETL {timestamp}"

    with tempfile.TemporaryDirectory(prefix="tokyo-grid-data-") as tmp:
        worktree = Path(tmp) / "data-wt"
        _run(["git", "worktree", "add", "--detach", str(worktree), base])

        try:
            check_tree(worktree, worktree=True, scan_text=False)
            _clear_directory(worktree)
            _copy_public_to_worktree(worktree)
            protect(worktree)
            prepare(worktree, worktree=True)
            _run(["git", "add", "-A"], cwd=worktree)

            diff = subprocess.run(
                ["git", "diff", "--staged", "--quiet"],
                cwd=worktree,
            )
            if diff.returncode > 1:
                diff.check_returncode()
            if diff.returncode == 0:
                if remote_tip(cwd=worktree) != base:
                    raise RuntimeError("data changed during no-op publication")
                print("[DATA] No data branch changes to publish")
                return

            _run(["git", "commit", "-m", message], cwd=worktree)
            _push_with_retry(worktree,base)
            print(f"[DATA] Published web/public to origin/{DATA_BRANCH}")
        finally:
            _run(["git", "worktree", "remove", str(worktree), "--force"])


def main() -> None:
    global REPO_ROOT, PUBLIC_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations-root", type=Path, help="Existing Git checkout containing the generated public tree")
    parser.add_argument("--receipt", required=True, type=Path, help="Private receipt produced by this run's restore")
    parser.add_argument("--message", help="Commit message for the data branch update")
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Publish without validating generated web/public first. Use only for emergency manual work.",
    )
    parser.add_argument(
        "--min-yesterday-hours",
        type=int,
        default=24,
        help="Required observed hours in yesterday's actual JSON before publish.",
    )
    args = parser.parse_args()
    if args.operations_root is not None:
        REPO_ROOT = args.operations_root.resolve(strict=True)
        PUBLIC_DIR = REPO_ROOT / "web" / "public"

    try:
        publish(
            args.message,
            base=oid(args.receipt.read_text(encoding="ascii").strip()),
            skip_validation=args.skip_validation,
            min_yesterday_hours=args.min_yesterday_hours,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] command failed: {' '.join(exc.cmd)}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
