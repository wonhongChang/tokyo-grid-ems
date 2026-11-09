import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error

import pytest
import yaml

from scripts import public_artifact_security as sec
from scripts import publish_data_branch as publish
from scripts import trigger_deploy_workflow as dispatch


@pytest.mark.parametrize("name", [".env", ".env.local", "ops/.ENV.backup", "metrics/.git/config",
                                  "reports/credentials.json", "reports/key.PEM.json",
                                  "ops/debug.log", "raw/result.json", "private/summary.json"])
def test_rejects_unexpected_names(tmp_path, name):
    path = tmp_path / name
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text("SENSITIVE_CANARY")
    with pytest.raises(sec.UnsafeArtifact) as err:
        sec.check_tree(tmp_path)
    assert "SENSITIVE_CANARY" not in str(err.value)


@pytest.mark.parametrize("value", [
    b"s" + b"k-proj-" + b"x" * 30, b"-----BEGIN " + b"PRIVATE KEY-----",
    b'{"TYPESAFE_API_KEY":"secret-canary"}', b"https://user:private@somewhere",
])
def test_detects_signature_across_read_boundary(tmp_path, value):
    (tmp_path / "status.json").write_bytes(b" " * (256 * 1024 - 2) + value)
    with pytest.raises(sec.UnsafeArtifact, match="credential signature"):
        sec.check_tree(tmp_path)


def test_link_or_junction_must_not_be_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "public"
    root.mkdir()
    if os.name == "nt":
        # Junction creation needs no Windows symlink privilege.
        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "actual"), str(outside)],
                       check=True, capture_output=True)
    else:
        (root / "actual").symlink_to(outside, target_is_directory=True)
    with pytest.raises(sec.UnsafeArtifact, match="link or reparse"):
        sec.check_tree(root)
    if os.name == "nt":
        (root / "actual").rmdir()
    else:
        (root / "actual").unlink()


def test_git_marker_only_in_worktree(tmp_path):
    (tmp_path / ".git").write_text("gitdir: /unused")
    sec.check_tree(tmp_path, worktree=True)
    with pytest.raises(sec.UnsafeArtifact):
        sec.check_tree(tmp_path)
    (tmp_path / ".git").write_text("untrusted marker")
    with pytest.raises(sec.UnsafeArtifact):
        sec.check_tree(tmp_path, worktree=True)


def test_quality_skip_cannot_skip_security(tmp_path, monkeypatch):
    (tmp_path / ".env").touch()
    monkeypatch.setattr(publish, "PUBLIC_DIR", tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("git reached"))
    with pytest.raises(sec.UnsafeArtifact):
        publish.publish(skip_validation=True)


def test_data_branch_keeps_state_but_pages_excludes_binary_and_redacts_legacy_status(tmp_path):
    (tmp_path / "ops").mkdir()
    path = tmp_path / "ops/local_etl_status.json"
    path.write_text(json.dumps({"stage": "failed", "status": "failed",
                                "message": "private info", "logPath": "private path"}), encoding="utf-8-sig")
    for name in sec.MODEL_STATE:
        (tmp_path / name).write_bytes(b"test")
    (tmp_path / "forecast_origins").mkdir()
    origin = tmp_path / "forecast_origins/origin.json"
    origin.write_bytes(b'{"forecast":[]}')
    sec.prepare(tmp_path)
    assert set(json.loads(path.read_text())) == {"stage", "status", "message"}
    assert "private info" not in path.read_text()
    assert all((tmp_path / name).is_file() for name in sec.MODEL_STATE)
    with pytest.raises(sec.UnsafeArtifact, match="restricted"):
        sec.prepare(tmp_path, pages=True)
    dist = tmp_path / "web/dist"
    dist.mkdir(parents=True)
    for name in sec.MODEL_STATE:
        shutil.copyfile(tmp_path / name, dist / name)
    (dist / "index.html").write_text("<html></html>")
    sec.prepare(dist, pages=True)
    assert not any((dist / name).exists() for name in sec.DATA_BINARY)
    assert all((tmp_path / name).exists() for name in sec.DATA_BINARY)
    assert origin.read_bytes() == b'{"forecast":[]}'


def test_workflows_check_restore_push_build_and_upload():
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    for name in ("etl", "intraday", "deploy"):
        job = next(iter(yaml.safe_load((workflows / f"{name}.yml").read_text(encoding="utf8"))["jobs"].values()))
        steps = job["steps"]
        restore = next(s["run"] for s in steps if "Restore web/public" in s.get("name", ""))
        assert restore.index("public_artifact_security.py restore") < restore.index("rsync")
        build = next(s["run"] for s in steps if s.get("name") == "Build")
        assert build.index("public_artifact_security.py data") < build.index("npm run build")
        upload = next(i for i,s in enumerate(steps) if "upload-pages-artifact" in s.get("uses",""))
        assert "public_artifact_security.py pages web/dist" in steps[upload-1]["run"]
        if name != "deploy":
            push = next(s["run"] for s in steps if "Push web/public" in s.get("name",""))
            assert push.index("public_artifact_security.py data web/public") < push.index("rsync")
            assert push.index("public_artifact_security.py data /tmp/data-wt") < push.index("git add")


def test_local_report_dotenv_only_fills_allowlisted_missing_values(tmp_path, monkeypatch):
    from python.eval.ai_daily_report import _load_local_dotenv
    monkeypatch.setattr(os, "environ", {})
    names = ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "TOKYO_GRID_EMS_OPENAI_API_KEY",
             "OPENAI_DAILY_REPORT_MODEL", "OPENAI_DAILY_REPORT_UNKNOWN", "EXTRA_CANARY")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("\n".join(f"{n}=dummy" for n in names))
    monkeypatch.setenv("OPENAI_DAILY_REPORT_MODEL", "existing")
    _load_local_dotenv(tmp_path / "web/public")
    assert [os.getenv(n) for n in names] == [None, None, "dummy", "existing", None, None]


def test_dispatch_never_logs_remote_or_reflected_response(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(dispatch, "_run_capture", lambda *a: "https://name:CANARY@invalid/repo")
    with pytest.raises(RuntimeError, match="Cannot infer") as err:
        dispatch._repo_full_name()
    assert "CANARY" not in str(err.value)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(dispatch, "_github_token", lambda: "CANARY")
    class Reject:
        def open(self, req, **kwargs):
            raise urllib.error.HTTPError(req.full_url, 403, "CANARY", {}, None)
    monkeypatch.setattr(dispatch.urllib.request, "build_opener", lambda handler: Reject())
    with pytest.raises(RuntimeError, match="HTTP 403") as err:
        dispatch.dispatch("deploy.yml", "main")
    assert "CANARY" not in str(err.value)
    assert dispatch._NoRedirect().redirect_request(None, None, 307, None, {}, "https://other") is None


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell unavailable")
def test_host_failure_never_writes_raw_error_or_log_path_to_public(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "local_etl.ps1"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/local_etl.ps1", script)
    def invoke(args):
        return subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command",
            "function global:docker { throw 'PRIVATE_ERROR_CANARY' }; "
            "& ./scripts/local_etl.ps1 -SkipRestore -ForceHistoricalEtl " + args],
            cwd=tmp_path, capture_output=True)
    assert invoke("-LogDir web/public").returncode != 0
    assert not (tmp_path / "web").exists()
    assert invoke("").returncode != 0
    status = json.loads((tmp_path / "web/public/ops/local_etl_status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "failed" and "logPath" not in status
    assert "PRIVATE_ERROR_CANARY" not in str(status) and str(tmp_path) not in str(status)
