"""Explicit local input allowlist and process-level filesystem/network guard."""
import json
import os
import re
import sys
from pathlib import Path

from . import core

SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-zA-Z0-9_-]+\Z")
DAY = r"\d{4}-\d{2}-\d{2}"
SOURCE = re.compile(
    r"(?:candidate:(?:lift_replay\.json|decision\.md)|extra:metrics/(?:model_promotion|operational_replay)\.json|"
    r"[a-zA-Z0-9_-]+:(?:manifest\.json|status\.json|\.etl_state\.json|\.lgbm_model_meta\.json|"
    r"(?:actual|forecast)/" + DAY + r"\.json|"
    r"reports/(?:daily/|ai/daily/(?:en|ko|ja)/)" + DAY + r"\.json|"
    r"(?:forecast_snapshots|forecast_origins|metrics|reports/internal)/[a-zA-Z0-9_./-]+\.json))\Z"
)
FORBIDDEN = {".git", ".codex", ".agents", ".ssh", ".aws", ".azure", ".config", "credentials", "secrets", "history", "sessions"}
PRODUCTION = {"python", "web", "data", "docs", "tests", "scripts", ".github", "models", "reports", "replay", "promotion", "etl"}


def clean_parts(value):
    parts = str(value).replace("\\", "/").split("/")
    return not any(p in {"..", "."} or p.lower() in FORBIDDEN or p.lower().startswith((".env", "jev")) for p in parts)


def no_links(path):
    for p in (path, *path.parents):
        if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
            core.fail("LINK_NOT_ALLOWED", missingLocator=str(p))
    if path.is_file() and path.stat().st_nlink > 1:
        core.fail("HARDLINK_NOT_ALLOWED", missingLocator=str(path))


def root_path(value, basename):
    raw = Path(value)
    if str(value).startswith(("\\\\", "//")) or not clean_parts(value):
        core.fail("UNAUTHORIZED_ROOT", missingLocator=str(value))
    no_links(raw.absolute())
    path = raw.resolve()
    if path.name != basename or any(p.lower() in PRODUCTION for p in path.parts):
        core.fail("UNAUTHORIZED_ROOT", missingLocator=str(value))
    if path == Path.home() or path == Path(path.anchor):
        core.fail("UNAUTHORIZED_ROOT", missingLocator=str(value))
    return path


def relative_path(root, value):
    value = str(value)
    if not clean_parts(value) or "\\" in value or ":" in value or Path(value).is_absolute():
        core.fail("PATH_TRAVERSAL", missingLocator=value)
    path = root / value
    no_links(path)
    if not path.resolve().is_relative_to(root.resolve()):
        core.fail("PATH_OUTSIDE_ROOT", missingLocator=value)
    return path


def pointer(value, obj):
    if value != "" and (not value.startswith("/") or re.search(r"~(?![01])", value)):
        core.fail("INVALID_POINTER", pointer=value)
    try:
        current = obj
        for part in value.split("/")[1:]:
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise KeyError(key)
                current = current[int(key)]
            else:
                current = current[key]
        return current
    except (KeyError, IndexError, TypeError, ValueError):
        core.fail("MISSING_POINTER", pointer=value, missingLocator=value)


class Access:
    def __init__(self, input_root, output_root, bundle, build=False):
        self.input_root = root_path(input_root, "review-inputs")
        self.output_root = root_path(output_root, "review-bundles")
        if not NAME.fullmatch(bundle):
            core.fail("INVALID_BUNDLE_NAME")
        if self.input_root.is_relative_to(self.output_root) or self.output_root.is_relative_to(self.input_root):
            core.fail("OVERLAPPING_ROOTS")
        self.bundle = relative_path(self.output_root, bundle)
        self.build = build
        self.read_allow = {self.input_root / "manifest.json", Path(core.__file__).resolve()}
        self.opens = []
        self.reads = []
        self.inventory = {}
        self.denied = []

    def install(self):
        sys.addaudithook(self.audit)

    def audit(self, event, args):
        if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in {"os.system", "os.fork", "ctypes.dlopen"}:
            self.denied.append(event)
            core.fail("PROCESS_OR_NETWORK_DENIED")
        if event == "open":
            if isinstance(args[0], int):
                core.fail("FILE_DESCRIPTOR_ACCESS_DENIED")
            path = Path(os.fsdecode(args[0])).absolute()
            no_links(path)
            path = path.resolve()
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            allowed = self.build and path.is_relative_to(self.bundle) if writing else path in self.read_allow or path.is_relative_to(self.bundle)
            if not allowed:
                self.denied.append(str(path))
                core.fail("WRITE_DENIED" if writing else "READ_DENIED", missingLocator=str(path))
            self.opens.append({"path": str(path), "write": writing})
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.chmod", "os.utime", "os.truncate"}:
            path = Path(os.fsdecode(args[0])).absolute().resolve()
            if event != "os.mkdir" or not self.build or not (path.is_relative_to(self.bundle) or path == self.output_root):
                self.denied.append(event)
                core.fail("MUTATION_DENIED", missingLocator=str(path))

    def read_bytes(self, path, expected, category):
        if not isinstance(expected, str) or not SHA.fullmatch(expected):
            core.fail("EXPECTED_HASH_REQUIRED", missingLocator=str(path))
        no_links(path)
        try:
            with path.open("rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            core.fail("RETENTION_LOSS", expectedHash=expected, missingLocator=str(path))
        except OSError:
            core.fail("SOURCE_IO_ERROR", expectedHash=expected, missingLocator=str(path))
        self.reads.append({"path": str(path), "bytes": len(raw), "category": category})
        if core.sha(raw) != expected:
            core.fail("SOURCE_HASH_MISMATCH", expectedHash=expected, missingLocator=str(path))
        return raw

    def read_json(self, path, expected, category):
        raw = self.read_bytes(path, expected, category)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            core.fail("INVALID_JSON", missingLocator=str(path))

    def manifest(self, expected):
        m = self.read_json(self.input_root / "manifest.json", expected, "input_manifest")
        if m.get("schemaVersion") != "review-bundle-input/0.2.0" or set(m) != {"schemaVersion", "inputs", "scopes"}:
            core.fail("INVALID_INPUT_MANIFEST")
        if not isinstance(m["inputs"], dict) or not isinstance(m["scopes"], list):
            core.fail("INVALID_INPUT_MANIFEST")
        ids = set()
        for s in m["scopes"]:
            if not NAME.fullmatch(str(s.get("id", ""))) or not NAME.fullmatch(str(s.get("captureKey", ""))) or s.get("role") not in {"primary", "followup", "candidate_validation"} or s["id"] in ids:
                core.fail("INVALID_SCOPE")
            ids.add(s["id"])
        roles = [s["role"] for s in m["scopes"]]
        if roles.count("primary") != 1 or roles.count("candidate_validation") > 1:
            core.fail("INVALID_SCOPE_CARDINALITY")
        for s in m["scopes"]:
            if s["role"] == "followup" and s.get("parentScope") not in ids:
                core.fail("INVALID_PARENT_SCOPE")
        for key, e in m["inputs"].items():
            if not isinstance(e, dict) or not SOURCE.fullmatch(key) or not clean_parts(key.split(":", 1)[1]) or "jev" in key.lower():
                core.fail("SOURCE_NOT_ALLOWED", expectedSource=key)
            h = e.get("sha256")
            if not isinstance(h, str) or not SHA.fullmatch(h) or e.get("path") != "sources/" + h + (".md" if key.endswith(".md") else ".json"):
                core.fail("SOURCE_PATH_NOT_ALLOWED", expectedSource=key)
            p = relative_path(self.input_root, e["path"])
            if type(e.get("bytes")) is not int or e["bytes"] < 0:
                core.fail("INVALID_SOURCE_SIZE", expectedSource=key)
            self.inventory[key] = dict(e, frozen=str(p))
        self.read_allow.update(Path(v["frozen"]) for v in self.inventory.values())
        return dict(m, inputs=self.inventory)

    def measurement(self):
        opened = [e for e in self.opens if not e["write"]]
        return {"fileOpenEvents": len(opened), "uniqueFilesOpened": len({e["path"] for e in opened}),
                "readBytes": sum(e["bytes"] for e in self.reads),
                "rawSourceBytes": sum(e["bytes"] for e in self.reads if e["category"] == "source"),
                "reads": self.reads, "opens": self.opens, "denied": self.denied,
                "scope": "Command body after imports; logical content I/O, not physical disk or interpreter startup",
                "modelTokens": None, "modelTokensReason": "No model calls or byte-to-token conversion"}


class SourceLoader(core.Loader):
    def __init__(self, access):
        super().__init__(access.inventory)
        self.access = access

    def get(self, key):
        self.requests[key] += 1
        e = self.inventory.get(key)
        if not e:
            core.fail("SOURCE_NOT_REGISTERED", expectedSource=key)
        p = Path(e["frozen"])
        no_links(p)
        try:
            info = p.stat()
            stamp = (info.st_size, info.st_mtime_ns)
        except OSError:
            stamp = None
        ck = (e["sha256"], *self.identity)
        previous = self.cache.get(ck)
        if previous and previous[0] == str(p) and previous[1] == stamp:
            return previous[2]
        try:
            value = self.access.read_json(Path(e["frozen"]), e["sha256"], "source")
        except core.EvidenceError as exc:
            exc.state["expectedSource"] = key
            raise
        actual_bytes = self.access.reads[-1]["bytes"]
        if actual_bytes != e["bytes"]:
            core.fail("SOURCE_SIZE_MISMATCH", expectedSource=key, expectedHash=e["sha256"],
                      expectedPopulation={"bytes": e["bytes"]}, observedPopulation={"bytes": actual_bytes})
        self.events.append(dict(source=key, bytes=actual_bytes, sha256=e["sha256"]))
        self.cache[ck] = (str(p), stamp, value)
        return value
