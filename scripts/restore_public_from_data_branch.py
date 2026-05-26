#!/usr/bin/env python3
"""Restore web/public from the origin/data branch."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO_ROOT / "web" / "public"
DATA_BRANCH = "data"


def _run(args: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, check=True)


def _has_remote_data_branch() -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", DATA_BRANCH],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _clear_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True)
        return
    resolved = path.resolve()
    repo = REPO_ROOT.resolve()
    if repo not in resolved.parents:
        raise RuntimeError(f"Refusing to clear path outside repo: {resolved}")
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def restore() -> None:
    subprocess.run(
        ["git", "fetch", "origin", DATA_BRANCH],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _has_remote_data_branch():
        print("[DATA] No origin/data branch found; keeping current web/public")
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        return

    with tempfile.TemporaryDirectory(prefix="tokyo-grid-data-restore-") as tmp:
        worktree = Path(tmp) / "data-wt"
        _run(["git", "worktree", "add", "--detach", str(worktree), f"origin/{DATA_BRANCH}"])
        try:
            _clear_directory(PUBLIC_DIR)
            for child in worktree.iterdir():
                if child.name == ".git":
                    continue
                target = PUBLIC_DIR / child.name
                if child.is_dir():
                    shutil.copytree(child, target)
                else:
                    shutil.copy2(child, target)
            print("[DATA] Restored web/public from origin/data")
        finally:
            _run(["git", "worktree", "remove", str(worktree), "--force"])


def main() -> None:
    try:
        restore()
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] command failed: {' '.join(exc.cmd)}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
