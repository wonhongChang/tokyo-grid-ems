"""Real CLI boundaries, with only synthetic input and a temporary output tree."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from python.observability import runner


@pytest.mark.parametrize("enabled",["0","1"])
def test_real_batch_missing_input_preserves_exit_and_argv(tmp_path,monkeypatch,enabled):
    monkeypatch.setenv("TGEMS_OTEL_ENABLED",enabled)
    monkeypatch.setenv("TGEMS_OTEL_ENDPOINT","forbidden")  # no network in this test
    before=sys.argv
    with pytest.raises(SystemExit) as exc:
        runner.main(["batch","--input",str(tmp_path/"missing"),"--out",str(tmp_path/"out"),
                     "--config",str(tmp_path/"absent.yaml")])
    assert exc.value.code==1 and sys.argv is before
    assert list((tmp_path/"out").iterdir())==[]


def test_exporter_init_disabled_and_rollback(tmp_path):
    root=Path(__file__).resolve().parents[1]
    source=tmp_path/"csv"; source.mkdir()
    for enabled in ("1","0"):
        cmd=[sys.executable,"-B","-m","python.observability.host","batch","--input",str(source),
             "--out",str(tmp_path/"out"),"--config",str(tmp_path/"missing.yaml")]
        proc=subprocess.run(cmd,cwd=root,capture_output=True,timeout=30,
            env=dict(os.environ,TGEMS_OTEL_ENABLED=enabled,TGEMS_OTEL_ENDPOINT="forbidden"))
        assert proc.returncode==0 and b"No CSV files" in proc.stderr
    assert list((tmp_path/"out").iterdir())==[]


def test_abrupt_child_restart_does_not_hold_log_lock(tmp_path):
    from python.observability.local_log import LocalLog
    root=Path(__file__).resolve().parents[1]
    program=("import os,sys; from pathlib import Path; from python.observability.local_log import LocalLog; "
             "sink=LocalLog(Path(sys.argv[1])); sink.write({'test':1}); os._exit(37)")
    proc=subprocess.run([sys.executable,"-B","-c",program,str(tmp_path)],cwd=root,timeout=15)
    assert proc.returncode==37
    sink=LocalLog(tmp_path)
    sink.put({"test":2});sink.done.set();sink.thread.join(2)
    assert (tmp_path/"events.jsonl").read_text().splitlines()==['{"test":1}','{"test":2}']


@pytest.mark.skipif(not shutil.which("pwsh"),reason="PowerShell Core not installed")
@pytest.mark.parametrize("exists,expected", [(True,0),(False,1)])
def test_powershell_wrapper_passes_command_as_one_argument(tmp_path,exists,expected):
    raw=tmp_path/"input"
    if exists:raw.mkdir()
    root=Path(__file__).resolve().parents[1]
    cmd="& ./ops/observability/observe.ps1 batch -Arguments @('--input',$env:TRIAL_INPUT,'--out',$env:TRIAL_OUTPUT,'--config',$env:TRIAL_CONFIG); exit $LASTEXITCODE"
    proc=subprocess.run(["pwsh","-NoProfile","-Command",cmd],cwd=root,timeout=30,capture_output=True,
        env=dict(os.environ,TRIAL_INPUT=str(raw),TRIAL_OUTPUT=str(tmp_path/"out"),
                 TRIAL_CONFIG=str(tmp_path/"missing.yaml"),TGEMS_OTEL_FIXTURE="1",TGEMS_OTEL_ENDPOINT="forbidden"))
    assert proc.returncode==expected and (b"No CSV files" if exists else b"Input dir not found") in proc.stderr


@pytest.mark.skipif(not shutil.which("pwsh"),reason="PowerShell Core not installed")
def test_ps_no_telemetry_restores_caller_setting():
    root=Path(__file__).resolve().parents[1]
    script="""
    function python { if ($env:TGEMS_OTEL_ENABLED -ne '0') { throw 'not disabled' }; $global:LASTEXITCODE=7 }
    $env:TGEMS_OTEL_ENABLED='1'
    & ./ops/observability/observe.ps1 validate -NoTelemetry
    if ($LASTEXITCODE -ne 7 -or $env:TGEMS_OTEL_ENABLED -ne '1') { exit 1 }
    exit 0
    """
    result=subprocess.run(["pwsh","-NoProfile","-Command",script],cwd=root,timeout=20,capture_output=True)
    assert result.returncode==0
