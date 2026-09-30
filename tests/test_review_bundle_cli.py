"""Offline CLI boundaries; no project data or model services required."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from python.eval.review_bundle import core
from python.eval.review_bundle.access import Access, SourceLoader, pointer, relative_path, root_path

REPO = Path(__file__).resolve().parents[1]


def put_input(root, key, value):
    raw = core.enc(value)
    h = core.sha(raw)
    p = root / "sources" / (h + ".json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return {"path": "sources/" + p.name, "sha256": h, "bytes": len(raw)}


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "review-inputs"
    root.mkdir()
    day = "2026-09-20"
    ts = day + "T00:00:00+09:00"
    items = {
        "20:actual/" + day + ".json": {"series": [{"ts": ts, "actualMw": 1000, "actualSource": "observed"}]},
        "20:forecast/" + day + ".json": {"series": [{"ts": ts, "forecastMw": 1100}], "model": {}},
        "extra:metrics/model_promotion.json": {"status": "champion_retained"},
        "extra:metrics/operational_replay.json": {},
    }
    inventory = {k: put_input(root, k, v) for k, v in items.items()}
    manifest = {"schemaVersion": "review-bundle-input/0.2.0", "inputs": inventory, "scopes": [
        {"id": "primary", "role": "primary", "captureKey": "20", "revision": "frozen", "asOf": ts,
         "capturedAt": ts, "finalizedThrough": "2026-09-19"}]}
    (root / "manifest.json").write_bytes(core.enc(manifest))
    return root, tmp_path / "review-bundles", manifest


def invoke(inputs, command, *options, seal=None):
    root, out, manifest = inputs
    cmd = [sys.executable, "-B", "-X", "utf8", "-m", "python.eval.review_bundle", command,
           "--input-root", str(root), "--input-sha", core.sha((root / "manifest.json").read_bytes()),
           "--output-root", str(out), "--bundle", "test", *options]
    if seal:
        cmd += ["--bundle-sha", seal]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, timeout=30)
    assert proc.stdout, proc.stderr.decode()
    return proc.returncode, json.loads(proc.stdout), json.loads(proc.stderr)


def build(inputs):
    code, output, _ = invoke(inputs, "build")
    assert code == 0, output
    return output["value"]["bundleSealSha256"]


def test_build_query_context_no_writes(inputs):
    before = {p: p.read_bytes() for p in inputs[0].rglob("*") if p.is_file()}
    seal = build(inputs)
    before_output = {p: p.read_bytes() for p in inputs[1].rglob("*") if p.is_file()}
    code, value, measurement = invoke(inputs, "fact", "--fact-id", "primary:2026-09-20:metrics", "--pointer", "/value/mae", seal=seal)
    assert code == 0 and value["value"] == 100
    assert value["context"]["method"] == "published"
    assert value["context"]["population"]["n"] == 1
    assert value["context"]["noticeRefs"] and value["context"]["provenance"]
    assert not any(e["write"] for e in measurement["measurement"]["opens"])
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert all(p.read_bytes() == raw for p, raw in before_output.items())


@pytest.mark.parametrize("p", ["../outside.json", "a/../../x", "C:/secret.json", "/etc/passwd", "a\\b", ".env", ".codex/auth.json", "jev/artifact.json"])
def test_relative_path_rejection(tmp_path, p):
    with pytest.raises(core.EvidenceError):
        relative_path(tmp_path, p)


@pytest.mark.parametrize("name", [".codex/review-inputs", "web/public/review-inputs", "data/review-inputs", "jev-trial/review-inputs", "unrelated"])
def test_root_rejection(tmp_path, name):
    with pytest.raises(core.EvidenceError):
        root_path(tmp_path / name, "review-inputs")


@pytest.mark.parametrize("p", ["foo", "/rows/-1", "/rows/01", "/bad~2key", "/rows/9"])
def test_invalid_pointer(p):
    with pytest.raises(core.EvidenceError):
        pointer(p, {"rows": [10]})


def test_missing_pointer_preserves_context(inputs):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "resolve", "--fact-id", "primary:2026-09-20:metrics", "--kind", "detail", "--pointer", "/absent", seal=seal)
    assert code == 2 and result["state"]["code"] == "MISSING_POINTER"
    assert result["context"]["method"] == "published"
    assert result["context"]["population"]["n"] == 1


@pytest.mark.parametrize("missing", [False, True])
def test_source_hash_and_missing(inputs, missing):
    seal = build(inputs)
    e = inputs[2]["inputs"]["20:actual/2026-09-20.json"]
    path = inputs[0] / e["path"]
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"{}")
    code, result, _ = invoke(inputs, "resolve", "--kind", "source", "--fact-id", "primary:2026-09-20:metrics", "--source", "20:actual/2026-09-20.json", "--pointer", "/series/0/actualMw", seal=seal)
    assert code == 2
    assert result["state"]["code"] == ("RETENTION_LOSS" if missing else "SOURCE_HASH_MISMATCH")


def test_unauthorized_manifest_source_never_opened(inputs):
    root, _, m = inputs
    m["inputs"]["20:actual/2026-09-20.json"]["path"] = "../.env"
    (root / "manifest.json").write_bytes(core.enc(m))
    code, result, measurement = invoke(inputs, "build")
    assert code == 2 and result["state"]["code"] == "SOURCE_PATH_NOT_ALLOWED"
    assert not any(".env" in e["path"] for e in measurement["measurement"]["opens"])


def test_bundle_hash_and_no_overwrite(inputs):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "initial", seal="0" * 64)
    assert code == 2 and result["state"]["code"] == "SOURCE_HASH_MISMATCH"
    code, result, _ = invoke(inputs, "build")
    assert code == 2 and result["state"]["code"] == "OUTPUT_ALREADY_EXISTS"
    path = inputs[1] / "test/review_bundle.json"
    path.write_bytes(b"{}")
    code, result, _ = invoke(inputs, "initial", seal=seal)
    assert code == 2 and result["state"]["code"] == "SOURCE_HASH_MISMATCH"


def test_no_full_detail_request(inputs):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "resolve", "--kind", "detail", "--fact-id", "primary:2026-09-20:metrics", seal=seal)
    assert code == 2 and result["state"]["code"] == "SELECTIVE_POINTER_REQUIRED"


def test_audit_guard_denies_writes_reads_and_network(tmp_path):
    base = tmp_path
    (base / "review-inputs").mkdir()
    # Run the audit hook in a disposable process: hooks intentionally cannot be
    # removed from a live Python process.
    code = """
import json,sys,socket,subprocess
from pathlib import Path
from python.eval.review_bundle.access import Access
from python.eval.review_bundle.core import EvidenceError
a=Access(sys.argv[1],sys.argv[2],'test');a.install()
results=[]
for op in [lambda: Path(sys.argv[1],'.env').read_bytes(),
           lambda: Path(sys.argv[1],'write.txt').write_text('bad'),
           lambda: Path(sys.argv[2],'test','write.txt').write_text('bad'),
           lambda: socket.socket(),lambda: subprocess.run(['whoami'])]:
    try: op(); results.append('ALLOWED')
    except EvidenceError as e: results.append(e.state['code'])
print(json.dumps(results))
"""
    proc = subprocess.run([sys.executable, "-B", "-c", code, str(base / "review-inputs"), str(base / "review-bundles")], cwd=REPO, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc.stderr.decode()
    assert json.loads(proc.stdout) == ["READ_DENIED", "WRITE_DENIED", "WRITE_DENIED", "PROCESS_OR_NETWORK_DENIED", "PROCESS_OR_NETWORK_DENIED"]


def test_symlink_and_hardlink_rejection(tmp_path):
    root = tmp_path / "review-inputs"
    root.mkdir()
    target = tmp_path / "other.json"
    target.write_bytes(b"{}")
    link = root / "linked.json"
    os.link(target, link)
    with pytest.raises(core.EvidenceError, match="HARDLINK_NOT_ALLOWED"):
        relative_path(root, "linked.json")


def test_deterministic_regeneration(inputs):
    first_seal = build(inputs)
    first = inputs[1] / "test"
    before = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    code, result, _ = invoke(inputs, "build", "--bundle", "repeat")
    assert code == 0, result
    repeat = inputs[1] / "repeat"
    after = {str(p.relative_to(repeat)): p.read_bytes() for p in repeat.rglob("*") if p.is_file()}
    assert before == after
    assert first_seal == result["value"]["bundleSealSha256"]


def test_bundle_reference_traversal_blocked(inputs):
    build(inputs)
    bundle = inputs[1] / "test"
    root = json.loads((bundle / "review_bundle.json").read_bytes())
    root["factIndexRef"]["path"] = "../.env"
    raw = core.enc(root)
    (bundle / "review_bundle.json").write_bytes(raw)
    seal = json.loads((bundle / "access.json").read_bytes())
    seal["files"]["review_bundle.json"] = {"bytes": len(raw), "sha256": core.sha(raw)}
    # Even an explicitly trusted replacement seal must not grant path escape.
    seal["files"]["../.env"] = {"bytes": 2, "sha256": root["factIndexRef"]["sha256"]}
    (bundle / "access.json").write_bytes(core.enc(seal))
    code, result, m = invoke(inputs, "facts", seal=core.sha(core.enc(seal)))
    assert code == 2 and result["state"]["code"] == "PATH_TRAVERSAL"
    assert not any(e["path"].endswith(".env") for e in m["measurement"]["opens"])


def test_unknown_source_denied(inputs):
    seal = build(inputs)
    code, result, _ = invoke(inputs, "resolve", "--kind", "source", "--fact-id", "primary:2026-09-20:metrics", "--source", "20:.env", "--pointer", "/key", seal=seal)
    assert code == 2 and result["state"]["code"] == "SOURCE_NOT_REGISTERED"


def test_missing_candidate_is_unavailable_not_approval(inputs):
    m = inputs[2]
    m["scopes"].append({"id": "candidate", "role": "candidate_validation", "captureKey": "candidate", "revision": None, "asOf": None, "capturedAt": None, "finalizedThrough": None, "expectedIdentity": {}})
    (inputs[0] / "manifest.json").write_bytes(core.enc(m))
    seal = build(inputs)
    code, r, _ = invoke(inputs, "fact", "--fact-id", "candidate:scope:candidate_validation", seal=seal)
    assert code == 0 and r["state"]["status"] == "unavailable"
    assert r["value"]["value"] is None
    assert r["context"]["promotionAuthorization"] is False


def test_unavailable_advance_not_replaced(inputs):
    seal = build(inputs)
    code, r, _ = invoke(inputs, "fact", "--fact-id", "primary:2026-09-20:stages", seal=seal)
    assert code == 0 and r["state"]["code"] == "NO_USABLE_ADVANCE_STAGE"
    assert r["context"]["method"] == "stages"


def test_paging_is_explicit_and_complete(inputs):
    seal = build(inputs)
    _, first, _ = invoke(inputs, "facts", "--limit", "2", seal=seal)
    total = first["value"]["paging"]["total"]
    ids = []
    offset = 0
    while offset is not None:
        _, result, _ = invoke(inputs, "facts", "--limit", "2", "--offset", str(offset), seal=seal)
        ids += [i["factId"] for i in result["value"]["items"]]
        offset = result["value"]["paging"]["nextOffset"]
    assert len(ids) == len(set(ids)) == total


def test_initial_envelope_overflow_is_explicit(inputs):
    build(inputs)
    bundle = inputs[1] / "test"
    root = json.loads((bundle / "review_bundle.json").read_bytes())
    root["paddingForBoundaryTest"] = "a" * 32768
    raw = core.enc(root)
    (bundle / "review_bundle.json").write_bytes(raw)
    seal = json.loads((bundle / "access.json").read_bytes())
    seal["files"]["review_bundle.json"] = {"bytes": len(raw), "sha256": core.sha(raw)}
    (bundle / "access.json").write_bytes(core.enc(seal))
    code, result, m = invoke(inputs, "initial", seal=core.sha(core.enc(seal)))
    assert code == 0 and m["measurement"]["returnedBytes"] <= 32768
    assert result["value"]["reason"] == "CLI_ENVELOPE_OVERFLOW"
    assert result["value"]["sectionManifestRef"] and result["value"]["mandatoryNotices"]


def test_scope_traversal_rejected_before_build(inputs):
    inputs[2]["scopes"][0]["id"] = "../../web/public"
    (inputs[0] / "manifest.json").write_bytes(core.enc(inputs[2]))
    code, result, _ = invoke(inputs, "build")
    assert code == 2 and result["state"]["code"] == "INVALID_SCOPE"
    assert not inputs[1].exists()


def test_build_write_audit_is_output_confined(inputs):
    code, _, m = invoke(inputs, "build")
    assert code == 0
    writes = [Path(e["path"]) for e in m["measurement"]["opens"] if e["write"]]
    assert writes and all(p.is_relative_to(inputs[1] / "test") for p in writes)


def test_source_loader_identity_and_stale_hash(inputs):
    root, out, _ = inputs
    a = Access(root, out, "test")
    a.manifest(core.sha((root / "manifest.json").read_bytes()))
    loader = SourceLoader(a)
    key = "20:actual/2026-09-20.json"
    first = loader.get(key)
    assert loader.get(key) is first
    assert len(loader.events) == 1
    assert (loader.inventory[key]["sha256"], *loader.identity) in loader.cache
    (root / loader.inventory[key]["path"]).write_bytes(b"{}")
    with pytest.raises(core.EvidenceError, match="SOURCE_HASH_MISMATCH"):
        loader.get(key)


def test_source_size_metadata_cannot_fake_read_measurement(inputs):
    root, out, m = inputs
    key = "20:actual/2026-09-20.json"
    actual_bytes = m["inputs"][key]["bytes"]
    m["inputs"][key]["bytes"] = 1
    (root / "manifest.json").write_bytes(core.enc(m))
    a = Access(root, out, "test")
    a.manifest(core.sha((root / "manifest.json").read_bytes()))
    with pytest.raises(core.EvidenceError, match="SOURCE_SIZE_MISMATCH"):
        SourceLoader(a).get(key)
    assert a.measurement()["rawSourceBytes"] == actual_bytes


def test_symlink_root_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "review-inputs"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Host cannot create directory symlinks: {exc}")
    with pytest.raises(core.EvidenceError, match="LINK_NOT_ALLOWED"):
        Access(link, tmp_path / "review-bundles", "test")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_junction_ancestor_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "review-inputs").mkdir()
    link = tmp_path / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)],
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    try:
        with pytest.raises(core.EvidenceError, match="LINK_NOT_ALLOWED"):
            Access(link / "review-inputs", tmp_path / "review-bundles", "test")
    finally:
        # Remove only the junction entry, never the directory it points to.
        link.rmdir()
