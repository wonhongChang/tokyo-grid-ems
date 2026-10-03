"""Explicit research/shadow CLI. Never called by ETL or serving."""
import argparse
import json
from pathlib import Path

from .evidence import sha
from .experiment import prepare, run
from .shadow import aggregate, capture, watch
from .storage import workspace


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'train-replay', 'shadow-capture', 'shadow-evaluate', 'shadow-watch'])
    p.add_argument('--output-root', required=True)
    p.add_argument('--input-root')
    p.add_argument('--input-sha')
    p.add_argument('--periods', help='JSON with train/validation/holdout [start,end] ranges')
    p.add_argument('--registration-sha')
    p.add_argument('--snapshot')
    p.add_argument('--snapshot-sha')
    p.add_argument('--snapshots-root')
    p.add_argument('--model-root')
    p.add_argument('--identity-sha')
    p.add_argument('--actual-root')
    p.add_argument('--state-file')
    p.add_argument('--interval-seconds', type=int, default=300)
    p.add_argument('--cycles', type=int)
    a = p.parse_args()
    required = {'prepare': ['input_root', 'input_sha', 'periods'], 'train-replay': ['registration_sha'],
                'shadow-capture': ['snapshot', 'snapshot_sha', 'model_root', 'identity_sha'],
                'shadow-evaluate': ['actual_root', 'state_file'],
                'shadow-watch': ['snapshots_root', 'model_root', 'identity_sha', 'actual_root', 'state_file']}
    for key in required[a.command]:
        if not getattr(a, key):
            p.error('--' + key.replace('_', '-') + ' is required')
    try:
        out = workspace(a.output_root)
        if a.command == 'prepare':
            result = prepare(a.input_root, a.input_sha, out, json.loads(a.periods))
            result = {'registrationSha256': sha((out / 'PREREGISTRATION.json').read_bytes()), 'counts': result['counts']}
        elif a.command == 'train-replay':
            result = run(out, a.registration_sha)
            result = {'selected': result['selected'], 'status': result['status'], 'resultsPath': str(out / 'RESULTS.json')}
        elif a.command == 'shadow-capture':
            result = capture(a.snapshot, a.snapshot_sha, a.model_root, a.identity_sha, out)
        elif a.command == 'shadow-evaluate':
            result = aggregate(out, a.actual_root, a.state_file)
        else:
            watch(a.snapshots_root, a.model_root, a.identity_sha, out, a.actual_root, a.state_file, a.interval_seconds, a.cycles)
            return
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'state': 'unavailable', 'reason': str(exc), 'productionChanged': False}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
