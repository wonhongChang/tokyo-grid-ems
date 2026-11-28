from collections import deque
import importlib.util
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pages_artifact_gate", ROOT / ".github/scripts/wait_for_pages_artifact.py"
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
NAME = "github-pages-3"
ARTIFACT_ID = 456


def response(*, id=ARTIFACT_ID, count=1, expired=False, size=123):
    return {"artifacts": [{"name": NAME, "id": id, "expired": expired, "size_in_bytes": size}] * count,
            "total_count": count}


def run(responses, *, timeout=30):
    values = deque(responses)
    clock = 0

    def lookup(deadline):
        assert 0 < deadline <= 8
        value = values.popleft() if values else response(count=0)
        if isinstance(value, Exception):
            raise value
        return value

    def sleep(seconds):
        nonlocal clock
        clock += seconds

    gate.wait_for_artifact(lookup, ARTIFACT_ID, NAME, timeout=timeout, now=lambda: clock, sleep=sleep)
    return clock


def test_waits_for_two_consecutive_exact_reads():
    assert run([response(count=0), response(), response(count=0), response(), response()]) == 20


def test_retries_temporary_lookup_failure_but_not_permission_error():
    http = lambda code: HTTPError("https://api.github.com", code, "synthetic", None, None)
    assert run([http(404), http(503), URLError("timeout"), response(), response()]) == 20
    with pytest.raises(gate.GateError, match="HTTP 403"):
        run([http(403), response(), response()])


@pytest.mark.parametrize("payload", [response(id=999), response(count=2), response(expired=True)])
def test_refuses_ambiguous_or_wrong_artifact(payload):
    with pytest.raises(gate.GateError, match="artifact"):
        run([payload, response(), response()])


def test_absent_or_unconfirmed_upload_blocks_deploy():
    with pytest.raises(gate.GateError, match="not confirmed"):
        run([response(size=0), response()], timeout=10)

@pytest.mark.parametrize("name,valid",[("github-pages-3",True),("pages-recovery-3",True),
    ("pages-recovery-retry-3",True),("pages-recovery-2",False),("unknown-3",False)])
def test_cli_exact_artifact_names(monkeypatch,name,valid):
    for k,v in dict(GITHUB_API_URL="https://api.github.com",GITHUB_REPOSITORY="fixture/repo",
        GITHUB_RUN_ID="123",GITHUB_RUN_ATTEMPT="3",PAGES_ARTIFACT_ID="456",
        PAGES_ARTIFACT_NAME=name,GH_TOKEN="not-a-token").items():
        monkeypatch.setenv(k,v)
    seen=[]
    monkeypatch.setattr(gate,"wait_for_artifact",lambda lookup,ident,label:seen.append((ident,label)))
    if not valid:
        with pytest.raises(gate.GateError):gate.main()
    else:
        gate.main()
        assert seen==[(456,name)]


@pytest.mark.parametrize("workflow", ["intraday", "deploy", "etl"])
def test_all_pages_paths_use_same_attempt_and_gate_before_deploy(workflow):
    path = ROOT / ".github/workflows" / f"{workflow}.yml"
    cfg = yaml.safe_load(path.read_bytes())
    assert cfg["permissions"]["actions"] == "read"
    jobs = [job for job in cfg["jobs"].values() if job.get("environment", {}).get("name") == "github-pages"]
    (job,) = jobs
    upload, wait, deploy, ack = job["steps"][-4:]
    assert upload["uses"] == "actions/upload-pages-artifact@v5"
    assert upload["with"]["name"] == wait["env"]["PAGES_ARTIFACT_NAME"] == deploy["with"]["artifact_name"]
    assert "github.run_attempt" in upload["with"]["name"]
    assert wait["env"]["PAGES_ARTIFACT_ID"] == "${{ steps." + upload["id"] + ".outputs.artifact_id }}"
    checks = wait["run"].strip().splitlines()
    assert checks[0] == "python3 .github/scripts/wait_for_pages_artifact.py"
    assert checks[1].startswith("python scripts/pages_release.py fence-release ")
    assert "continue-on-error" not in wait
    assert upload["if"] == wait["if"] == deploy["if"] == "steps.identity.outputs.skip != 'true'"
    assert "steps.deploy.outcome == 'success'" in ack["if"]
    assert deploy["uses"] == "actions/deploy-pages@v5"
