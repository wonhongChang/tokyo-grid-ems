"""Local-only atomic status and process exclusion for one shared shadow volume."""
import os
from pathlib import Path
import uuid

from .evidence import encode
from .storage import workspace


def immutable_bytes(path, content):
    path = workspace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = workspace(path.with_name('.tmp-' + uuid.uuid4().hex))
    try:
        with temporary.open('xb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        try:
            # CreateHardLink on Windows needs extended paths for SHA-addressed
            # files whose absolute destination exceeds the legacy MAX_PATH.
            source = '\\\\?\\' + str(temporary) if os.name == 'nt' else temporary
            destination = '\\\\?\\' + str(path) if os.name == 'nt' else path
            os.link(source, destination)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError('Conflicting immutable shadow artifact')
    finally:
        temporary.unlink(missing_ok=True)
    return path


def immutable_json(path, value):
    return immutable_bytes(path, encode(value))


def atomic_json(path, value):
    path = workspace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = workspace(path.with_name(path.name + '.tmp'))
    with temporary.open('wb') as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class WorkerLock:
    """OS lock survives stale lock files but is released when a process dies."""
    def __init__(self, root):
        self.path = workspace(Path(root) / '.worker.lock')
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.stream.write(b'0'); self.stream.flush()
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close(); self.stream = None
            raise RuntimeError('Another worker owns this shadow workspace') from None
        return self

    def __exit__(self, *args):
        if self.stream is not None:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
