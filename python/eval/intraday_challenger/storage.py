"""All new artifacts are restricted to an explicit ignored research workspace."""
from pathlib import Path

from .evidence import encode

REPO_ROOT = Path(__file__).resolve().parents[3]


def workspace(path):
    root = Path(path).resolve()
    allowed = REPO_ROOT.resolve() / 'data/intraday_challenger'
    if allowed.resolve() != allowed:
        raise ValueError("Output workspace root is redirected")
    if root == allowed or not root.is_relative_to(allowed):
        raise ValueError("Output must be a named workspace under data/intraday_challenger")
    return root


def exclusive_json(path, value):
    """Immutable prediction records. Identical re-execution is idempotent."""
    path = Path(path)
    content = encode(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("Conflicting immutable artifact: " + str(path))
    return path
