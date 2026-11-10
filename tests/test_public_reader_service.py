import json
import subprocess
import sys

from python.observability.reader_control import ManagedReader, exclusive


def test_duplicate_rejected_and_lock_released_after_crash(tmp_path):
    command=[sys.executable,"-B","-c",
             "from pathlib import Path;import os,sys;from python.observability.reader_control import exclusive\n"
             "with exclusive(Path(sys.argv[1])):os._exit(7)",str(tmp_path)]
    with exclusive(tmp_path):
        assert subprocess.run(command).returncode==73
    assert subprocess.run(command).returncode==7
    with exclusive(tmp_path):pass


def test_stop_is_scoped_to_one_generation(tmp_path):
    first=ManagedReader(tmp_path)
    (tmp_path/"stop.request").write_bytes(first.instance.encode())
    assert not first.wait(1)
    next_reader=ManagedReader(tmp_path)
    assert next_reader.wait(0)
    next_reader.projected(True,"a"*40)
    good=json.loads((tmp_path/"status.json").read_bytes())
    next_reader.mark("waiting_for_collector")
    during=json.loads((tmp_path/"status.json").read_bytes())
    assert during["state"]=="waiting_for_collector"
    assert during["lastPublicRead"]==good["lastPublicRead"] and during["ticks"]==1


def test_failed_read_does_not_advance_success(tmp_path):
    reader=ManagedReader(tmp_path)
    reader.projected(True,"a"*40)
    previous=reader.last_read
    reader.projected(False,None)
    state=json.loads((tmp_path/"status.json").read_bytes())
    assert state["state"]=="public_read_failed" and state["lastPublicRead"]==previous
    assert state["publicRevision"]=="a"*40
