"""Advisory parallel predictions and revision-aware finalized aggregation only."""
import json
from datetime import datetime
from pathlib import Path
import time

from . import CONTRACT
from .evidence import JST, closest, encode, features, number, sha, timestamp
from .evaluation import report, transitions
from .model import load, predict
from .storage import exclusive_json, workspace


def _now():
    return datetime.now(JST)


def capture(snapshot_path, snapshot_sha, model_path, identity_sha, output):
    out = workspace(output)
    b = Path(snapshot_path).read_bytes()
    if sha(b) != snapshot_sha:
        raise ValueError("Snapshot hash mismatch")
    snapshot = json.loads(b)
    booster, identity = load(model_path, identity_sha)
    if snapshot['date'] <= identity['trainingEnd']:
        raise ValueError("Shadow target must be after model training period")
    rows = list(features(snapshot))
    predictions = predict(booster, rows, identity['spec'])
    name = sha(encode([snapshot_sha, identity_sha]))
    path = out / 'runs' / snapshot['date'] / (name + '.json')
    captured_at = timestamp(json.loads(path.read_bytes())['recordedAt']) if path.exists() else _now()
    for r, p in zip(rows, predictions):
        r.update(challenger=p, actual=None, actual_state='unavailable', source_sha=snapshot_sha,
                 feature_identity=CONTRACT, model_identity=identity['modelSha256'], model_identity_sha=identity_sha,
                 forecast_basis='same-run recorded post; not published forecast',
                 native_interval=None, training_end=identity['trainingEnd'],
                 prospective_at_shadow_capture=timestamp(r['target']) > captured_at)
    result = {'schemaVersion': 'intraday-shadow/1.0.0', 'issuedAt': snapshot['generatedAt'],
              'date': snapshot['date'], 'recordedAt': captured_at.isoformat(),
              'captureDelayMinutes': (captured_at - timestamp(snapshot['generatedAt'])).total_seconds() / 60,
              'sourceSha256': snapshot_sha, 'modelIdentity': identity,
              'modelIdentitySha256': identity_sha, 'rows': rows, 'productionPromotion': False,
              'servingPolicyAttested': False, 'predictionInterval': 'unavailable; point correction only'}
    exclusive_json(path, result)
    return {'path': str(path), 'sha256': sha(encode(result)), 'rows': len(rows), 'productionChanged': False}


def aggregate(output, actual_root, state_file):
    """Recompute numeric daily/band/cumulative reports as finalized labels arrive.

    Each label revision gets a separate immutable report; prediction records stay
    unchanged. Provisional and missing hours do not enter finalized metrics.
    """
    out = workspace(output)
    state_bytes = Path(state_file).read_bytes()
    state = json.loads(state_bytes)
    finalized = set(state.get('okDates', []))
    runs = sorted((out / 'runs').glob('*/*.json'))
    groups, identities, excluded, actual_refs, run_refs = {}, {}, [], {}, []
    for path in runs:
        b = path.read_bytes()
        run = json.loads(b)
        if run.get('schemaVersion') != 'intraday-shadow/1.0.0':
            raise ValueError("Unknown shadow record contract")
        run_refs.append({'path': str(path.relative_to(out)), 'sha256': sha(b)})
        day = run['date']
        actual_path = Path(actual_root) / (day + '.json')
        actual = {}
        label_state = 'unavailable'
        if actual_path.exists():
            ab = actual_path.read_bytes()
            data = json.loads(ab)
            if data.get('date') != day:
                raise ValueError("Actual date mismatch")
            label_state = 'finalized' if day in finalized else 'provisional'
            actual_refs[day] = {'sha256': sha(ab), 'state': label_state}
            actual = {timestamp(r['ts']).hour: number(r.get('actualMw')) for r in data.get('series', [])
                      if r.get('actualSource') != 'tepco_forecast_fallback'}
        key = run['modelIdentitySha256']
        identities[key] = run['modelIdentity']
        for r in run['rows']:
            row = dict(r, actual=actual.get(r['hour']), actual_state=label_state)
            groups.setdefault(key, []).append(row)
            if label_state != 'finalized' or row['actual'] is None or not row.get('prospective_at_shadow_capture'):
                excluded.append({'date': day, 'hour': row['hour'], 'issue': row['issued_at'],
                                 'modelIdentitySha256': key, 'reason': 'retrospective_capture' if not row.get('prospective_at_shadow_capture') else label_state if row['actual'] is not None else 'missing_actual'})
    evaluations = {}
    for key, rows in groups.items():
        pairs = [(r['date'], r['issued_at'], r['hour']) for r in rows]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate model issue-target population")
        prospective = [r for r in rows if r.get('prospective_at_shadow_capture')]
        retrospective = [r for r in rows if not r.get('prospective_at_shadow_capture')]
        finalized_rows = [r for r in prospective if r['actual_state'] == 'finalized' and r['actual'] is not None]
        daily = {}
        for day in sorted({r['date'] for r in finalized_rows}):
            rr = [r for r in finalized_rows if r['date'] == day]
            daily[day] = report(rr, [r['challenger'] for r in rr])
        evaluations[key] = {'identity': identities[key], 'cumulative': report(prospective, [r['challenger'] for r in prospective]),
                            'retrospectiveCapture': report(retrospective, [r['challenger'] for r in retrospective]),
                            'daily': daily, 'transitions': transitions(prospective, [r['challenger'] for r in prospective]),
                            'finalizedRows': len(finalized_rows), 'finalizedClosestTargets': len(closest(finalized_rows))}
    result = {'schemaVersion': 'intraday-shadow-evaluation/1.0.0', 'stateSha256': sha(state_bytes),
              'actualReferences': actual_refs, 'runReferences': run_refs, 'models': evaluations,
              'exclusions': excluded, 'promotionAuthorization': False, 'productionChanged': False}
    key = sha(encode(result))
    path = out / 'evaluations' / (key + '.json')
    exclusive_json(path, result)
    return {'path': str(path), 'sha256': key, 'models': len(evaluations), 'exclusions': len(excluded)}


def watch(snapshot_root, model_path, identity_sha, output, actual_root, state_file, seconds=300, cycles=None):
    """Optional separate local worker; no scheduler registration or paid calls.

    Source synchronization is external. New files are read-only inputs. The long
    sleep happens inside Python, not repeated reasoning-model polling.
    """
    workspace(output)
    completed, failed = set(), set()
    captured_dates = set()
    last_actual_revision = None
    cycle = 0
    while cycles is None or cycle < cycles:
        new_capture = False
        for path in sorted(Path(snapshot_root).glob('*/*.json')):
            if path.name == 'index.json':
                continue
            b = path.read_bytes(); h = sha(b)
            if h in completed or h in failed:
                continue
            try:
                result = capture(path, h, model_path, identity_sha, output)
                completed.add(h)
                captured_dates.add(Path(result['path']).parent.name)
                new_capture = True
            except (ValueError, KeyError, OSError) as exc:
                failed.add(h)
                print(json.dumps({'state': 'unavailable', 'snapshotSha256': h, 'reason': str(exc)}), flush=True)
        # Hash labels as well: revisions can occur without a change to okDates.
        actual_paths = [Path(actual_root) / (d + '.json') for d in sorted(captured_dates)]
        revision = sha(encode({'state': sha(Path(state_file).read_bytes()),
                              'actuals': {p.name: sha(p.read_bytes()) for p in actual_paths if p.exists()}}))
        if revision != last_actual_revision or new_capture:
            print(json.dumps(aggregate(output, actual_root, state_file)), flush=True)
            last_actual_revision = revision
        cycle += 1
        if cycles is None or cycle < cycles:
            time.sleep(max(60, seconds))
