"""Local lifecycle for a single public projector. No scheduling or ETL dependencies."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import time
import uuid
from .public_source import traffic

DIRECTORY = Path(__file__).resolve().parents[2] / "logs" / "observability" / "public-reader"


@contextmanager
def exclusive(directory=DIRECTORY):
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "reader.lock"
    if lock.resolve() != lock.absolute():
        raise OSError("linked reader lock")
    with lock.open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(73) from None
        yield  # Closing the OS handle releases ownership even after a crash.


class ManagedReader:
    def __init__(self, directory=DIRECTORY):
        self.directory = directory
        self.instance = uuid.uuid4().hex
        self.started = time.time()
        self.last_read = None
        self.ticks = 0
        self.revision = None

    def mark(self, state):
        requests, body_bytes = traffic()
        data = {"state":state, "pid":os.getpid(), "instance":self.instance,
                "started":self.started, "heartbeat":time.time(), "ticks":self.ticks,
                "lastPublicRead":self.last_read, "publicRevision":self.revision,
                "publicHttpsAttempts":requests, "publicResponseBytes":body_bytes}
        temp = self.directory / "status.tmp"
        if temp.resolve() != temp.absolute():
            raise OSError("linked status file")
        temp.write_text(json.dumps(data, separators=(",",":")), encoding="ascii")
        for attempt in range(3):
            try:
                os.replace(temp, self.directory / "status.json")
                break
            except PermissionError:
                # A Windows status viewer can briefly hold a non-sharing handle.
                if attempt == 2:raise
                time.sleep(.05)

    def projected(self, success, revision):
        self.ticks += 1
        if success:
            self.last_read, self.revision = time.time(), revision
        self.mark("public_read_ok" if success else "public_read_failed")

    def stop_requested(self):
        p = self.directory / "stop.request"
        try:
            if p.resolve() != p.absolute():
                return False
            with p.open("rb") as f:
                return f.read(64).strip() == self.instance.encode("ascii")
        except FileNotFoundError:
            return False

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.stop_requested():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(2, remaining))
        return False

    def collector(self):
        # TCP reachability is only a preflight. Actual delivery is verified in Prometheus.
        try:
            with socket.create_connection(("127.0.0.1", 4318), timeout=1):return True
        except OSError:
            return False
