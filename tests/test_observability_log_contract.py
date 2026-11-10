"""Black-box log contracts, applicable to both frozen and proposed implementations."""
import json
import os
import time

import pytest

from python.observability.local_log import LocalLog


def drain(sink):
    sink.done.set()
    sink.thread.join(2)
    assert not sink.thread.is_alive()


def contents(folder):
    names=["events.3.jsonl","events.2.jsonl","events.1.jsonl","events.jsonl"]
    return [json.loads(line) for name in names if (folder/name).exists()
            for line in (folder/name).read_text().splitlines()]


def test_burst_and_rotation_match_individual_writes(tmp_path):
    burst=LocalLog(tmp_path/"burst",limit=100)
    serial=LocalLog(tmp_path/"serial",limit=100)
    events=[{"stage":"model.predict","seq":i} for i in range(83)]
    for event in events:burst.put(event)
    drain(burst)
    drain(serial)
    for event in events:serial.write(event)
    def inventory(root):
        return {p.name:p.read_bytes() for p in root.glob("events*.jsonl")}
    assert inventory(burst.root)==inventory(serial.root)
    assert contents(burst.root)==events[-len(contents(burst.root)):]


def test_pending_records_drain_before_close(tmp_path):
    sink=LocalLog(tmp_path)
    events=[{"stage":"forecast.issue","seq":i} for i in range(120)]
    for event in events:sink.put(event)
    drain(sink)
    assert contents(tmp_path)==events


def test_linked_destination_never_writes_outside(tmp_path):
    sink=LocalLog(tmp_path/"events")
    drain(sink)
    sink.root.mkdir(exist_ok=True)
    external=tmp_path/"external"
    external.write_bytes(b"unchanged")
    try:(sink.root/"events.jsonl").symlink_to(external)
    except OSError:pytest.skip("symlink creation unavailable")
    sink.write({"stage":"input.quality"})
    assert external.read_bytes()==b"unchanged"


def test_retention_and_day_boundary(tmp_path):
    sink=LocalLog(tmp_path);drain(sink)
    sink.write({"seq":1})
    os.utime(tmp_path/"events.jsonl",(time.time()-86400,)*2)
    sink.write({"seq":2})
    assert json.loads((tmp_path/"events.1.jsonl").read_text())=={"seq":1}
    os.utime(tmp_path/"events.1.jsonl",(time.time()-9*86400,)*2)
    sink.write({"seq":3})
    assert contents(tmp_path)==[{"seq":2},{"seq":3}]


def test_one_lock_denial_does_not_discard_the_rest(monkeypatch,tmp_path):
    if os.name=="nt":
        import msvcrt as backend
        name="locking"
    else:
        import fcntl as backend
        name="flock"
    original=getattr(backend,name);attempts=[]
    def deny_once(*a):
        attempts.append(1)
        if len(attempts)==1:raise BlockingIOError(13,"one synthetic denial")
        return original(*a)
    monkeypatch.setattr(backend,name,deny_once)
    sink=LocalLog(tmp_path)
    for i in range(16):sink.put({"seq":i})
    drain(sink)
    assert contents(tmp_path)==[{"seq":i} for i in range(1,16)]
