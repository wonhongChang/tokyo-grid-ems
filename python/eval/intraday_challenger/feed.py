"""Standalone Git data-feed shadow worker; never writes the production checkout.

Uses a private bare repository and ignored content-addressed input cache. There is
no scheduler/service registration. Run in a user-owned terminal for its lifetime.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from .evidence import encode, sha, timestamp
from .shadow import aggregate, capture, _now, _model
from .storage import exclusive_json, workspace


def _git(directory, *args):
    result = subprocess.run(['git', '--git-dir', str(directory), *args], capture_output=True, timeout=180)
    if result.returncode:
        raise OSError('Isolated Git data fetch/read failed: ' + result.stderr.decode(errors='replace')[:500])
    return result.stdout


def sync(remote, root, start_date):
    out = workspace(root)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', start_date):
        raise ValueError('ISO start date required')
    if not remote.startswith('https://github.com/') or '@' in remote or '?' in remote or '#' in remote:
        raise ValueError('Credential-free GitHub HTTPS remote required')
    cache = workspace(out / 'feed')
    bare = workspace(cache / 'repository.git')
    if not bare.exists():
        _git(bare, 'init', '--bare', str(bare))
    _git(bare, 'fetch', '--depth=1', remote, 'refs/heads/data:refs/heads/shadow-data')
    revision = _git(bare, 'rev-parse', 'refs/heads/shadow-data').decode().strip()
    prefix = 'reports/internal/operational-calibration/snapshots/'
    paths = _git(bare, 'ls-tree', '-r', '--name-only', revision, '--', prefix, 'actual/', '.etl_state.json').decode().splitlines()
    selected = []
    for path in paths:
        if path == '.etl_state.json':
            selected.append(path)
        elif re.fullmatch(r'actual/\d{4}-\d{2}-\d{2}\.json', path) and path[7:17] >= start_date:
            selected.append(path)
        elif re.fullmatch(re.escape(prefix) + r'\d{4}-\d{2}-\d{2}/[^/]+\.json', path):
            if path[len(prefix):len(prefix)+10] >= start_date and not path.endswith('/index.json'):
                selected.append(path)
    references, snapshots = {}, []
    actual_root = workspace(cache / 'actual')
    actual_root.mkdir(parents=True, exist_ok=True)
    present_actuals = {Path(p).name for p in selected if p.startswith('actual/')}
    for stale in actual_root.glob('*.json'):
        if stale.name not in present_actuals:
            workspace(stale).unlink()
    for path in selected:
        b = _git(bare, 'show', revision + ':' + path)
        value = json.loads(b)
        h = sha(b)
        source = workspace(cache / 'sources' / (h + '.json'))
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            with source.open('xb') as stream:
                stream.write(b)
        elif source.read_bytes() != b:
            raise ValueError('Cached source hash mismatch')
        references[path] = {'sha256': h, 'revision': revision, 'cache': str(source.relative_to(out))}
        if path.startswith(prefix):
            snapshots.append((source, h))
        elif path.startswith('actual/'):
            # Mutable label view is confined to the ignored feed; originals remain
            # content-addressed and each evaluated revision is immutable.
            workspace(actual_root / Path(path).name).write_bytes(b)
        else:
            workspace(cache / 'state.json').write_bytes(b)
    if '.etl_state.json' not in references:
        raise ValueError('Data revision has no ETL state; cannot infer finalization')
    record = {'revision': revision, 'sources': references, 'startDate': start_date, 'productionChanged': False}
    exclusive_json(cache / 'revisions' / (sha(encode(record)) + '.json'), record)
    return snapshots, actual_root, cache / 'state.json', revision


def watch(remote, model_root, identity_sha, output, start_date, seconds=300, cycles=None):
    out = workspace(output)
    _, identity, _ = _model(model_root, identity_sha)
    if start_date <= identity['trainingEnd']:
        raise ValueError('Feed start must follow training end')
    done, failures = set(), set()
    previous_evaluation_input = None
    cycle = 0
    while cycles is None or cycle < cycles:
        try:
            sources, actual_root, state, revision = sync(remote, out, start_date)
            for source, h in sources:
                if h in done or h in failures:
                    continue
                try:
                    result = capture(source, h, model_root, identity_sha, out)
                    done.add(h)
                    run = json.loads(Path(result['path']).read_bytes())
                    print(json.dumps(dict(result, dataRevision=revision,
                          prospective=sum(bool(r['prospective_at_shadow_capture']) for r in run['rows']))), flush=True)
                except (ValueError, KeyError, OSError) as exc:
                    failures.add(h)
                    print(json.dumps({'state':'unavailable','snapshotSha256':h,'reason':str(exc)}), flush=True)
            signature = sha(encode({'state':sha(state.read_bytes()), 'runs':sorted(done),
                       'actuals':{p.name:sha(p.read_bytes()) for p in sorted(actual_root.glob('*.json'))}}))
            if signature != previous_evaluation_input:
                print(json.dumps(aggregate(out, actual_root, state)), flush=True)
                previous_evaluation_input = signature
            status = {'state':'cycle_complete', 'recordedAt':_now().isoformat(), 'revision':revision,
                      'capturedSnapshots':len(done), 'unavailableSnapshots':len(failures),
                      'productionChanged':False, 'schedulerChanged':False}
            exclusive_json(out/'worker-cycles'/(sha(encode(status))+'.json'),status)
            print(json.dumps(status),flush=True)
        except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({'state':'unavailable','reason':str(exc),'productionChanged':False}),flush=True)
            if cycles is not None:
                raise
        cycle += 1
        if cycles is None or cycle < cycles:
            time.sleep(max(60, seconds))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--remote',required=True)
    p.add_argument('--model-root',required=True)
    p.add_argument('--identity-sha',required=True)
    p.add_argument('--output-root',required=True)
    p.add_argument('--start-date',required=True)
    p.add_argument('--interval-seconds',type=int,default=300)
    p.add_argument('--cycles',type=int)
    a=p.parse_args()
    try:
        watch(a.remote,a.model_root,a.identity_sha,a.output_root,a.start_date,a.interval_seconds,a.cycles)
    except (ValueError,KeyError,OSError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'state':'unavailable','reason':str(exc),'productionChanged':False}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
