"""Advisory parallel predictions and revision-aware finalized aggregation only."""
import json
from datetime import datetime
from pathlib import Path
import time

from . import CONTRACT
from .evidence import JST, closest, encode, features, number, sha, timestamp
from .evaluation import report, transitions
from .lead_evaluation import lead_report, revisions
from .model import load, predict
from .storage import exclusive_json, workspace


def _now():
    return datetime.now(JST)


def _model(model_path, identity_sha):
    b = (Path(model_path) / 'identity.json').read_bytes()
    if sha(b) != identity_sha:
        raise ValueError('Model identity hash mismatch')
    if json.loads(b).get('contract') == 'intraday-lead-research/1.0.0':
        from .lead_model import load as lead_load, predict as lead_predict
        model, identity = lead_load(model_path, identity_sha)
        return model, identity, lambda rows: lead_predict(model, rows)
    model, identity = load(model_path, identity_sha)
    return model, identity, lambda rows: predict(model, rows, identity['spec'])


def capture(snapshot_path, snapshot_sha, model_path, identity_sha, output):
    out = workspace(output)
    b = Path(snapshot_path).read_bytes()
    if sha(b) != snapshot_sha:
        raise ValueError("Snapshot hash mismatch")
    snapshot = json.loads(b)
    booster, identity, forecast = _model(model_path, identity_sha)
    if snapshot['date'] <= identity['trainingEnd']:
        raise ValueError("Shadow target must be after model training period")
    rows = list(features(snapshot))
    predictions = forecast(rows)
    name = sha(encode([snapshot_sha, identity_sha]))
    path = out / 'runs' / snapshot['date'] / (name + '.json')
    if path.exists():
        previous = json.loads(path.read_bytes())
        if previous['sourceSha256'] != snapshot_sha or previous['modelIdentitySha256'] != identity_sha:
            raise ValueError('Existing capture identity mismatch')
        return {'path': str(path), 'sha256': sha(path.read_bytes()), 'rows': len(previous['rows']), 'productionChanged': False}
    captured_at = _now()
    if timestamp(snapshot['generatedAt']) > captured_at:
        raise ValueError('Source issue time is in the future')
    model_fingerprint = identity.get('modelSha256') or sha(encode(identity['artifacts']))
    source_indices = {int(row['hour']): i for i, row in enumerate(snapshot['hourlyDiagnostics'])}
    for r, p in zip(rows, predictions):
        r.update(challenger=p, actual=None, actual_state='unavailable', source_sha=snapshot_sha,
                 feature_identity=identity['contract'], model_identity=model_fingerprint, model_identity_sha=identity_sha,
                 forecast_basis='same-run recorded post; not published forecast',
                 source_pointer='/hourlyDiagnostics/' + str(source_indices[r['hour']]),
                 native_interval=None, training_end=identity['trainingEnd'],
                 capture_lead_minutes=(timestamp(r['target'])-captured_at).total_seconds()/60,
                 prospective_at_shadow_capture=timestamp(r['target']) > captured_at)
    result = {'schemaVersion': 'intraday-shadow/1.1.0', 'issuedAt': snapshot['generatedAt'],
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
        if run.get('schemaVersion') not in ('intraday-shadow/1.0.0', 'intraday-shadow/1.1.0'):
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
        if sha(encode(run['modelIdentity'])) != key:
            raise ValueError('Stored model identity hash mismatch')
        identities[key] = run['modelIdentity']
        for r in run['rows']:
            fingerprint = run['modelIdentity'].get('modelSha256') or sha(encode(run['modelIdentity']['artifacts']))
            if r.get('model_identity_sha') != key or r.get('model_identity') != fingerprint:
                raise ValueError('Stored row model identity mismatch')
            value = actual.get(r['hour'])
            effective_state = label_state if value is not None else 'unavailable'
            champion_error = r['champion'] - value if value is not None else None
            challenger_error = r['challenger'] - value if value is not None else None
            row = dict(r, actual=value, actual_state=effective_state,
                       actual_source_sha=actual_refs.get(day, {}).get('sha256'),
                       champion_error_mw=champion_error, challenger_error_mw=challenger_error,
                       error_delta_mw=abs(challenger_error)-abs(champion_error) if value is not None else None,
                       signed_error_delta_mw=challenger_error-champion_error if value is not None else None)
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
        finalized_days = sorted({r['date'] for r in finalized_rows})
        business_days = sorted({r['date'] for r in finalized_rows if not r['features']['non_business']})
        non_business_days = sorted({r['date'] for r in finalized_rows if r['features']['non_business']})
        counts = {'totalProspectivePairs': len(prospective), 'prospectiveClosestTargets': len(closest(prospective)),
                  'finalizedPairs': len(finalized_rows), 'finalizedClosestTargets': len(closest(finalized_rows)),
                  'finalizedDates': len(finalized_days), 'businessDates': len(business_days), 'nonBusinessDates': len(non_business_days)}
        sample_ready = counts['finalizedDates'] >= 14 and counts['businessDates'] >= 8 and counts['nonBusinessDates'] >= 4 and \
            counts['finalizedPairs'] >= 300 and counts['finalizedClosestTargets'] >= 150
        daily = {}
        for day in sorted({r['date'] for r in finalized_rows}):
            rr = [r for r in finalized_rows if r['date'] == day]
            daily[day] = report(rr, [r['challenger'] for r in rr])
        evaluations[key] = {'identity': identities[key], 'cumulative': report(prospective, [r['challenger'] for r in prospective]),
                            'retrospectiveCapture': report(retrospective, [r['challenger'] for r in retrospective]),
                            'daily': daily, 'transitions': transitions(prospective, [r['challenger'] for r in prospective]),
                            'finalizedRows': len(finalized_rows), 'finalizedClosestTargets': len(closest(finalized_rows)),
                            'counts': counts, 'finalizedDates': finalized_days, 'joinedRows': rows,
                            'leadAnalysis': lead_report(finalized_rows, [r['challenger'] for r in finalized_rows]),
                            'revisionStability': revisions(prospective, [r['challenger'] for r in prospective]),
                            'sampleReadiness': sample_ready, 'promotionReady': False,
                            'limitations': ['sample readiness is not promotion approval', 'native intervals unavailable',
                                            'historical champion artifact/policy unattested']}
    result = {'schemaVersion': 'intraday-shadow-evaluation/1.1.0', 'stateSha256': sha(state_bytes),
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
