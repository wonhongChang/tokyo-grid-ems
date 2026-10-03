"""Public Git data ingestion into an isolated shadow-only content-addressed cache."""
import json
import os
from pathlib import Path
import re
import subprocess

from .evidence import encode, sha
from .service_io import immutable_bytes, immutable_json as exclusive_json
from .storage import workspace

PREFIX = 'reports/internal/operational-calibration/snapshots/'


def git(directory, *args):
    # No inherited credential helpers, host HOME, hooks, proxy keys, or git config.
    env = {'PATH': os.environ.get('PATH', ''), 'GIT_TERMINAL_PROMPT': '0',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_CONFIG_COUNT': '3', 'GIT_CONFIG_KEY_0': 'credential.helper', 'GIT_CONFIG_VALUE_0': '',
           'GIT_CONFIG_KEY_1': 'core.hooksPath', 'GIT_CONFIG_VALUE_1': os.devnull,
           'GIT_CONFIG_KEY_2': 'http.followRedirects', 'GIT_CONFIG_VALUE_2': 'false'}
    if os.name == 'nt':
        env['SYSTEMROOT'] = os.environ['SYSTEMROOT']
    result = subprocess.run(['git', '--git-dir', str(directory), *args], env=env,
                            capture_output=True, timeout=180)
    if result.returncode:
        # Never reflect remote/server stderr (which may contain credentials) into logs.
        raise OSError('Isolated public Git operation failed: ' + args[0] + ', exit ' + str(result.returncode))
    return result.stdout


def source_bytes(out, ref):
    path = workspace(Path(out) / ref['cache'])
    b = path.read_bytes()
    if sha(b) != ref['sha256']:
        raise ValueError('Content-addressed source hash mismatch')
    return b


def sync(remote, out, start_date, previous=None):
    from datetime import date
    date.fromisoformat(start_date)
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', remote):
        raise ValueError('Only credential-free public GitHub repository URLs are allowed')
    out = workspace(out)
    bare = workspace(out / 'feed/repository.git')
    if not bare.exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        git(bare, 'init', '--bare', str(bare))
    git(bare, 'fetch', '--depth=1', remote, 'refs/heads/data:refs/heads/shadow-data')
    revision = git(bare, 'rev-parse', 'refs/heads/shadow-data').decode().strip()
    if not re.fullmatch('[0-9a-f]{40,64}', revision):
        raise ValueError('Invalid data revision')
    if previous and previous['revision'] == revision and previous['startDate'] == start_date:
        return previous, False
    tree = git(bare, 'ls-tree', '-r', revision, '--', PREFIX, 'actual/', '.etl_state.json').decode().splitlines()
    refs = {}
    for line in tree:
        header, path = line.split('\t', 1)
        _, kind, blob = header.split()
        if kind != 'blob':
            continue
        selected = path == '.etl_state.json'
        selected |= bool(re.fullmatch(r'actual/\d{4}-\d{2}-\d{2}\.json', path) and path[7:17] >= start_date)
        selected |= bool(re.fullmatch(re.escape(PREFIX) + r'\d{4}-\d{2}-\d{2}/[A-Za-z0-9_.+\-]+\.json', path)
                         and path[len(PREFIX):len(PREFIX)+10] >= start_date and not path.endswith('/index.json'))
        if not selected:
            continue
        old = previous.get('sources', {}).get(path) if previous else None
        if old and old['gitBlob'] == blob:
            refs[path] = dict(old, revision=revision)
            continue
        b = git(bare, 'show', revision + ':' + path)
        json.loads(b)
        h = sha(b)
        target = workspace(out / 'feed/sources' / (h + '.json'))
        immutable_bytes(target, b)
        refs[path] = {'sha256': h, 'gitBlob': blob, 'revision': revision,
                      'cache': str(target.relative_to(out)).replace('\\', '/'), 'sourcePath': path}
    manifest = {'revision': revision, 'sources': refs, 'startDate': start_date,
                'contract': 'intraday-shadow-feed/1.0.0', 'productionChanged': False}
    exclusive_json(workspace(out / 'feed/revisions' / (sha(encode(manifest)) + '.json')), manifest)
    return manifest, True
