"""Identity-separated immutable actual revisions; never promotion authorization."""
from datetime import timedelta
import json

from .evidence import closest, encode, number, sha, timestamp
from .evaluation import report, transitions
from .lead_evaluation import lead_report, revisions
from .service_feed import source_bytes
from .service_records import read_runs
from .service_io import immutable_json as exclusive_json
from .storage import workspace

EVALUATION_CONTRACT = 'intraday-multi-shadow-evaluation/1.0.0'
SAMPLE_REQUIREMENTS = {'finalizedDates': 14, 'businessDates': 8, 'nonBusinessDates': 4,
                       'finalizedPairs': 300, 'finalizedClosestTargets': 150}


def evaluate(out, manifest, registry, now, registry_sha):
    refs = manifest['sources']
    state_ref = refs.get('.etl_state.json')
    state = json.loads(source_bytes(out, state_ref)) if state_ref else {}
    finalized = set(state.get('okDates', []))
    actual, actual_refs = {}, {}
    for path, ref in refs.items():
        if not path.startswith('actual/'):
            continue
        day = path[7:17]
        label = json.loads(source_bytes(out, ref))
        if label.get('date') != day:
            raise ValueError('Actual source date mismatch')
        values = {}
        for row in label.get('series', []):
            ts = timestamp(row['ts'])
            if ts.date().isoformat() != day or ts.hour in values:
                raise ValueError('Duplicate/mismatched actual target')
            value = number(row.get('actualMw'))
            values[ts.hour] = (value if row.get('actualSource') != 'tepco_forecast_fallback'
                               and ts + timedelta(hours=1) <= now else None)
        actual[day] = values
        actual_refs[day] = ref
    grouped, run_refs = {}, []
    entries = {e['identitySha256']: e for e in registry['challengers']}
    for run, path, h in read_runs(out):
        key = run['identitySha256']
        if key not in entries:
            raise ValueError('Historical identity missing from registry')
        grouped.setdefault(key, [])
        run_refs.append({'path': path, 'sha256': h})
        for row in run['rows']:
            if row['model_identity_sha'] != key or row['model_identity'] != entries[key]['combinedFingerprint']:
                raise ValueError('Stored prediction identity mismatch')
            value = actual.get(row['date'], {}).get(row['hour'])
            label_state = 'unavailable' if value is None else 'finalized' if row['date'] in finalized and state_ref else 'provisional'
            ce = row['champion'] - value if value is not None else None
            xe = row['challenger'] - value if value is not None else None
            grouped[key].append(dict(row, actual=value, actual_state=label_state,
                actual_source_sha=actual_refs.get(row['date'], {}).get('sha256'),
                actual_source_revision=actual_refs.get(row['date'], {}).get('revision'),
                champion_error_mw=ce, challenger_error_mw=xe,
                champion_absolute_error_mw=abs(ce) if ce is not None else None,
                challenger_absolute_error_mw=abs(xe) if xe is not None else None,
                error_delta_mw=abs(xe)-abs(ce) if value is not None else None))
    results = {}
    for key, rows in grouped.items():
        population = [(r['date'], r['issued_at'], r['hour']) for r in rows]
        if len(population) != len(set(population)):
            raise ValueError('Duplicate identity issue-target population')
        independent = [r for r in rows if r['independentEligible']]
        finalized_rows = [r for r in independent if r['actual_state'] == 'finalized']
        final_dates = sorted({r['date'] for r in finalized_rows})
        counts = {'prospectivePairs': len(independent), 'prospectiveClosestTargets': len(closest(independent)),
                  'finalizedPairs': len(finalized_rows), 'finalizedClosestTargets': len(closest(finalized_rows)),
                  'finalizedDates': len(final_dates),
                  'businessDates': len({r['date'] for r in finalized_rows if not r['features']['non_business']}),
                  'nonBusinessDates': len({r['date'] for r in finalized_rows if r['features']['non_business']})}
        result = {'identitySha256': key, 'membership': entries[key], 'joinedRows': rows,
                  'independentPopulation': 'issue after activation/active epoch; timely capture before target; non-research dates',
                  'cumulative': report(independent, [r['challenger'] for r in independent]),
                  'contextOnly': report([r for r in rows if not r['independentEligible']],
                                        [r['challenger'] for r in rows if not r['independentEligible']]),
                  'counts': counts, 'finalizedDates': final_dates,
                  'leadAnalysis': lead_report(finalized_rows, [r['challenger'] for r in finalized_rows]),
                  'revisionStability': revisions(independent, [r['challenger'] for r in independent]),
                  'transitions': transitions(independent, [r['challenger'] for r in independent]),
                  'sampleRequirements': SAMPLE_REQUIREMENTS,
                  'sampleReadiness': all(counts[k] >= v for k, v in SAMPLE_REQUIREMENTS.items()),
                  'promotionReady': False, 'nativeIntervalValidation': None,
                  'limitations': ['sample readiness is not promotion approval', 'point-only native intervals unavailable',
                                  'champion artifact/serving policy unattested', 'requires explicit future serving-policy version change']}
        results[key] = result
    envelope = {'contract': EVALUATION_CONTRACT, 'sourceRevision': manifest['revision'],
                'actualReferences': actual_refs, 'stateReference': state_ref, 'runReferences': run_refs,
                'registrySha256': registry_sha, 'models': results,
                'productionChanged': False, 'promotionAuthorization': False}
    h = sha(encode(envelope))
    path = workspace(out / 'evaluations' / (h + '.json'))
    exclusive_json(path, envelope)
    summaries = {key: {k: v for k, v in value.items() if k in
                      ('identitySha256','counts','finalizedDates','sampleReadiness','promotionReady','sampleRequirements')}
                 for key, value in results.items()}
    return {'path': str(path.relative_to(out)), 'sha256': h, 'models': summaries}
