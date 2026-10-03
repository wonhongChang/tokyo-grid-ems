"""Real local Git transport regressions; no network or production refs."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from python.eval.intraday_challenger import service_feed as feed, storage


@pytest.mark.parametrize('update', ['advance', 'rewrite'])
def test_shallow_feed_refreshes_private_ref_and_preserves_revision_evidence(tmp_path, monkeypatch, update):
    monkeypatch.setattr(storage, 'REPO_ROOT', tmp_path)
    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    out = tmp_path / 'data/intraday_challenger/live'

    def source_git(*args):
        result = subprocess.run([
            'git', '-c', 'core.hooksPath=' + os.devnull,
            '-c', 'user.name=Shadow regression', '-c', 'user.email=shadow@example.invalid',
            '-C', str(upstream), *args,
        ], capture_output=True, check=True, timeout=30)
        return result.stdout.decode().strip()

    source_git('init', '-b', 'data')
    actual = upstream / 'actual/2026-10-04.json'
    actual.parent.mkdir()

    def commit_revision(value):
        actual.write_text(json.dumps({'date': '2026-10-04', 'series': [], 'revision': value}), encoding='utf-8')
        source_git('add', '--', 'actual/2026-10-04.json')
        source_git('commit', '-m', 'fixture revision ' + str(value))
        return source_git('rev-parse', 'HEAD')

    initial = commit_revision(0)
    remote = 'https://github.com/example/shadow-feed-regression.git'
    original_git = feed.git
    fetches = []

    def local_transport(directory, *args):
        assert Path(directory).is_relative_to(out)
        if args[0] == 'fetch':
            assert args[1:3] == ('--depth=1', remote)
            fetches.append(args)
            args = (*args[:2], upstream.as_uri(), *args[3:])
        return original_git(directory, *args)

    monkeypatch.setattr(feed, 'git', local_transport)
    first, changed = feed.sync(remote, out, '2026-10-04')
    assert changed and first['revision'] == initial
    old_bytes = {p: p.read_bytes() for p in (out / 'feed/sources').glob('*.json')}
    old_manifests = {p: p.read_bytes() for p in (out / 'feed/revisions').glob('*.json')}
    if update == 'advance':
        commit_revision(1)
        latest = commit_revision(2)
    else:
        source_git('checkout', '--orphan', 'replacement')
        latest = commit_revision(2)
        source_git('branch', '-M', 'data')

    second, changed = feed.sync(remote, out, '2026-10-04', first)
    assert changed and second['revision'] == latest != initial
    ref = second['sources']['actual/2026-10-04.json']
    assert json.loads(feed.source_bytes(out, ref))['revision'] == 2
    assert all(p.read_bytes() == b for p, b in old_bytes.items())
    assert all(p.read_bytes() == b for p, b in old_manifests.items())
    assert len(list((out / 'feed/revisions').glob('*.json'))) == 2
    unchanged, changed = feed.sync(remote, out, '2026-10-04', second)
    assert not changed and unchanged == second
    bare = out / 'feed/repository.git'
    assert original_git(bare, 'for-each-ref', '--format=%(refname)').decode().splitlines() == ['refs/heads/shadow-data']
    assert all(args[-1] == '+refs/heads/data:refs/heads/shadow-data' for args in fetches)
    assert source_git('rev-parse', 'refs/heads/data') == latest
