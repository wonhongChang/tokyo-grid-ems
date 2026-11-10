"""One private bounded JSONL sink; the producer never performs file I/O."""
import json
import os
from pathlib import Path
from queue import Queue, Full, Empty
from threading import Thread, Event
import time

ROOT = Path(__file__).resolve().parents[2] / "logs" / "observability"


class LocalLog:
    def __init__(self, root=ROOT, limit=8 * 1024 * 1024):
        self.root, self.limit = root, limit
        self.queue = Queue(256)
        self.done = Event()
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def put(self, event):
        try:
            self.queue.put_nowait(event)
        except Full:
            pass

    def _run(self):
        while not self.done.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=.05)
            except Empty:
                continue
            try:
                self.write(event)
            except Exception:
                pass

    def write(self, event):
        # OS releases this nonblocking lock even on abrupt process exit.
        root = self.root
        if root.resolve() != root.absolute():
            return
        root.mkdir(parents=True, exist_ok=True)
        paths = [root / name for name in ("events.jsonl", "events.1.jsonl", "events.2.jsonl", "events.3.jsonl")]
        lock = root / "writer.lock"
        if any(p.resolve() != p.absolute() for p in [*paths, lock]):
            return
        with lock.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for p in paths:
                if p.exists() and p.stat().st_mtime < time.time() - 7 * 86400:
                    p.unlink()
            line = json.dumps(event, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
            if paths[0].exists() and (paths[0].stat().st_size + len(line) > self.limit or
                    int(paths[0].stat().st_mtime // 86400) != int(time.time() // 86400)):
                for src, dest in reversed(list(zip(paths, paths[1:]))):
                    if src.exists():
                        src.replace(dest)
            with paths[0].open("ab") as stream:
                stream.write(line)
