"""Fail-closed release boundary for the data branch and Pages (stdlib only)."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path


DATA_DIRS = {"actual", "alerts", "forecast", "forecast_origins", "forecast_snapshots",
             "metrics", "ops", "reports"}
MODEL_STATE = {".etl_state.json", ".hourly_cache.parquet", ".lgbm_model.pkl",
               ".lgbm_model_meta.json", ".lgbm_model.rollback.pkl",
               ".lgbm_model.rollback_meta.json", ".lgbm_model.shadow.pkl",
               ".lgbm_model.shadow_meta.json"}
DATA_BINARY = {n for n in MODEL_STATE if n.endswith((".pkl", ".parquet"))}
ASSET_EXTENSIONS = {".js", ".css", ".woff", ".woff2", ".svg", ".png", ".webp", ".jpg", ".ico"}
SENSITIVE_NAME = re.compile(
    r"(?:^|[._-])(?:env|credentials?|secrets?|id_rsa|id_ed25519|private[_-]?key)(?:[._-]|$)"
    r"|\.(?:pem|pfx|p12|key)(?:\.|$)", re.I)
TOKEN = re.compile(
    rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}"
    rb"|gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,}"
    rb"|AKIA[0-9A-Z]{16}|https?://[^\s/:@<>]{1,120}:[^\s/@<>]{1,240}@"
    rb'|"(?:[\w.-]{0,80}(?:api[_-]?key|access[_-]?token|password|client[_-]?secret))"'
    rb'\s{0,32}:\s{0,32}"[^"\r\n]{8}', re.I)


class UnsafeArtifact(ValueError):
    pass


def _plain(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise UnsafeArtifact("link or reparse point")
    return info


def _scan_text(path: Path) -> None:
    tail = b""
    with path.open("rb") as stream:
        while block := stream.read(256 * 1024):
            window = tail + block
            if TOKEN.search(window):
                raise UnsafeArtifact("credential signature in publishable text")
            tail = window[-1024:]


def check_tree(root: Path, *, worktree: bool = False, pages: bool = False,
               scan_text: bool = True) -> None:
    """Allow only contract files; do not dereference links or report their contents."""
    root = root.absolute()
    for parent in [*reversed(root.parents), root]:
        if not stat.S_ISDIR(_plain(parent).st_mode):
            raise UnsafeArtifact("invalid directory ancestor")
    def walk(folder: Path) -> None:
        for path in folder.iterdir():
            mode = _plain(path).st_mode
            parts = path.relative_to(root).parts
            if worktree and parts == (".git",) and stat.S_ISREG(mode):
                # Only the linked worktree's own administrative file is exempt.
                with path.open("rb") as marker:
                    if marker.read(8) != b"gitdir: ":
                        raise UnsafeArtifact("invalid worktree marker")
                continue
            if SENSITIVE_NAME.search(path.name):
                raise UnsafeArtifact("credential filename")
            state_file = len(parts) == 1 and path.name in MODEL_STATE
            if path.name.startswith(".") and not state_file:
                raise UnsafeArtifact("unexpected hidden entry")
            asset = pages and parts[0] == "assets"
            if stat.S_ISDIR(mode):
                if parts[0] not in DATA_DIRS and not asset:
                    raise UnsafeArtifact("unexpected artifact directory")
                walk(path)
            elif stat.S_ISREG(mode):
                if not (state_file or parts == ("status.json",)
                        or len(parts) > 1 and parts[0] in DATA_DIRS and path.suffix == ".json"
                        or asset and len(parts) > 1 and path.suffix in ASSET_EXTENSIONS
                        or pages and parts == ("index.html",)):
                    raise UnsafeArtifact("unexpected artifact type")
                if scan_text and not (state_file and path.name in DATA_BINARY) and (
                        not asset or path.suffix in {".js", ".css", ".svg"}):
                    _scan_text(path)
            else:
                raise UnsafeArtifact("special filesystem entry")
    walk(root)


def scrub_legacy_status(root: Path) -> None:
    """Only sanitize the mutable operator status, never forecast/identity evidence."""
    path = root / "ops" / "local_etl_status.json"
    if not path.exists():
        return
    if path.stat().st_size > 65536:
        raise UnsafeArtifact("invalid operator status size")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise UnsafeArtifact("invalid operator status")
    changed = "logPath" in obj
    obj.pop("logPath", None)
    message = "Local ETL failed; check the private scheduler log."
    if obj.get("status") == "failed" and obj.get("message") != message:
        obj["message"] = message
        changed = True
    if changed:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(root: Path, *, pages: bool = False, worktree: bool = False) -> None:
    if pages and (root.absolute().parts[-2:] != ("web", "dist") or worktree):
        raise UnsafeArtifact("Pages cleanup is restricted to web/dist")
    check_tree(root, worktree=worktree, pages=pages, scan_text=False)
    if pages and not (root / "index.html").is_file():
        raise UnsafeArtifact("missing Pages entry point")
    scrub_legacy_status(root)
    if pages:
        for name in DATA_BINARY:
            (root / name).unlink(missing_ok=True)
    check_tree(root, worktree=worktree, pages=pages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("restore", "data", "pages"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "restore":
            check_tree(args.root, worktree=args.worktree)
        else:
            prepare(args.root, pages=args.mode == "pages", worktree=args.worktree)
    except (OSError, ValueError) as exc:
        # Filenames, offending text and JSON exception detail are not public logs.
        parser.exit(1, "Release security check failed: " +
                    (str(exc) if isinstance(exc, UnsafeArtifact) else type(exc).__name__) + "\n")


if __name__ == "__main__":
    main()
