import subprocess

import pytest

from scripts import publish_data_branch as pub
from scripts import restore_public_from_data_branch as restore


def git(cwd, *args):
    return subprocess.check_output(["git", *args],cwd=cwd,text=True).strip()


def test_interleaved_writer_refuses_stale_restore_and_push(tmp_path, monkeypatch):
    remote, host, local = (tmp_path/n for n in ("remote","host","local"))
    git(tmp_path,"init","--bare",str(remote))
    git(tmp_path,"clone",str(remote),str(host))
    git(host,"switch","-c","data")
    git(host,"config","user.name","fixture")
    git(host,"config","user.email","fixture@example.invalid")
    (host/"status.json").write_text("{}")
    git(host,"add",".")
    git(host,"commit","-m","base")
    git(host,"push","origin","HEAD:data")
    git(tmp_path,"clone","-b","data",str(remote),str(local))
    git(local,"config","user.name","fixture")
    git(local,"config","user.email","fixture@example.invalid")
    public=local/"web"/"public"
    for mod in (restore,pub):
        monkeypatch.setattr(mod,"REPO_ROOT",local)
        monkeypatch.setattr(mod,"PUBLIC_DIR",public)
    receipt=tmp_path/"base"
    restore.restore(receipt)
    base=receipt.read_text()
    assert base==git(host,"rev-parse","HEAD")
    (public/"status.json").write_text('{"source":"windows"}')
    (host/"status.json").write_text('{"source":"newer"}')
    git(host,"commit","-am","intervening")
    git(host,"push","origin","HEAD:data")
    with pytest.raises(RuntimeError,match="since restore"):
        pub.publish(skip_validation=True,base=base)
    git(local,"commit","--allow-empty","-m","racing local output")
    with pytest.raises(RuntimeError,match="advanced"):
        pub._push_with_retry(local,base)
    assert git(remote,"show","data:status.json")=='{"source":"newer"}'
    receipt2=tmp_path/"fresh"
    restore.restore(receipt2)
    (public/"status.json").write_text('{"source":"fresh"}')
    pub.publish(skip_validation=True,base=receipt2.read_text())
    assert git(remote,"rev-parse","data^")==receipt2.read_text() and git(remote,"show","data:status.json")=='{"source":"fresh"}'
