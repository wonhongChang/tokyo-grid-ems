"""Preregistered chronological research runner, isolated from production."""
import json
from pathlib import Path

import numpy as np

from .evidence import encode, sha
from .evaluation import report, transitions
from .lead_evaluation import LEAD_BUCKETS, lead_report, revisions
from .lead_model import fit, predict, save
from .model import CANDIDATES, predict as l2_predict, train as l2_train
from .storage import exclusive_json, workspace


def partitions(records, folds):
    output, tested = [], set()
    for fold in folds:
        lo, end = fold['train']
        start, hi = fold['test']
        if not lo <= end < start <= hi:
            raise ValueError('Overlapping chronological split')
        train = [r for r in records if lo <= r['date'] <= end and r['actual_state'] == 'finalized' and r['actual'] is not None]
        test = [r for r in records if start <= r['date'] <= hi and r['actual_state'] == 'finalized' and r['actual'] is not None]
        if not train or not test:
            raise ValueError('Empty fold')
        for r in test:
            key = (r['date'], r['issued_at'], r['hour'])
            if key in tested:
                raise ValueError('Duplicate outer-test population')
            tested.add(key)
        output.append((train, test))
    return output


def acceptance(result, reference, criteria, allowance):
    a = result['all_positive:finalized']
    c = result['closest_0_120:finalized']['overall']
    ar = reference['all_positive:finalized']['overall']
    cr = reference['closest_0_120:finalized']['overall']
    overall = a['overall']
    gates = {
        'all_mae': overall['challenger']['mae'] <= overall['champion']['mae'] * criteria['all_mae_ratio_max'],
        'closest_mae': c['challenger']['mae'] <= c['champion']['mae'] * criteria['closest_mae_ratio_max'],
        'all_rmse': overall['challenger']['rmse'] <= overall['champion']['rmse'] * criteria['all_rmse_ratio_max'],
        'closest_rmse': c['challenger']['rmse'] <= c['champion']['rmse'] * criteria['closest_rmse_ratio_max'],
        'closest_daily': c['date_wins'] >= c['date_losses'],
        'all_regression_p95': overall['regression_p95'] <= ar['regression_p95'],
        'closest_regression_p95': c['regression_p95'] <= cr['regression_p95'],
        'all_max_regression': overall['max_regression'] <= ar['max_regression'],
        'closest_max_regression': c['max_regression'] <= cr['max_regression'],
    }
    gates['bands_regimes'] = all(v is None or v['challenger']['mae'] <= v['champion']['mae'] + allowance
        for k, v in a.items() if k in ('night','morning','midday','afternoon','evening','business','non_business'))
    return gates


def run(dataset_path, registration_path, registration_sha, output, code_revision):
    out = workspace(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Research output already exists')
    rb = Path(registration_path).read_bytes()
    if sha(rb) != registration_sha:
        raise ValueError('Preregistration hash mismatch')
    registration = json.loads(rb)
    db = Path(dataset_path).read_bytes()
    if sha(db) != registration['frozenDatasetSha256']:
        raise ValueError('Frozen dataset hash mismatch')
    if registration['leadBucketsMinutes'] != [list(x) for x in LEAD_BUCKETS]:
        raise ValueError('Preregistered lead bins mismatch')
    records = [json.loads(line) for line in db.splitlines() if line]
    folds = partitions(records, registration['folds'])
    predictions = {name: [] for name in ('L2','L4','L5')}
    test_rows, fold_results, replay = [], [], []
    allowance = float(np.median([abs(r['champion'] - r['actual']) for r in folds[0][0]]) * .25)
    for i, (training, testing) in enumerate(folds):
        baseline = l2_train(training, 'L2')
        values = {'L2': l2_predict(baseline, testing, CANDIDATES['L2'])}
        identities = {}
        for name in ('L4', 'L5'):
            model = fit(training, name)
            identities[name] = save(model, out / 'models' / f'fold-{i+1}' / name, training, sha(db), code_revision)
            values[name] = predict(model, testing)
        fr = {'fold': i + 1, 'trainDates': registration['folds'][i]['train'],
              'testDates': registration['folds'][i]['test'], 'trainRows': len(training), 'testRows': len(testing),
              'identity': identities, 'results': {n: report(testing, p) for n, p in values.items()}}
        fold_results.append(fr)
        for j, r in enumerate(testing):
            replay.append(dict(r, fold=i+1, predictions={n: p[j] for n,p in values.items()}))
        test_rows.extend(testing)
        for name in predictions:
            predictions[name].extend(values[name])
    evaluations = {name: report(test_rows, p) for name, p in predictions.items()}
    stability = {name: revisions(test_rows, p) for name, p in predictions.items()}
    gates = {}
    criteria = registration['acceptance']
    for name in ('L4', 'L5'):
        g = acceptance(evaluations[name], evaluations['L2'], criteria, allowance)
        g['fold_closest'] = all(f['results'][name]['closest_0_120:finalized']['overall']['challenger']['mae'] <=
             f['results'][name]['closest_0_120:finalized']['overall']['champion']['mae'] * criteria['each_fold_closest_mae_ratio_max']
             for f in fold_results)
        for metric in ('mean', 'p95'):
            g['revision_' + metric] = stability[name]['challenger'] is not None and stability['L2']['challenger'] is not None and \
                stability[name]['challenger'][metric] <= stability['L2']['challenger'][metric]
        gates[name] = g
    eligible = [name for name in ('L4','L5') if all(gates[name].values())]
    selected = min(eligible, key=lambda n:(evaluations[n]['closest_0_120:finalized']['overall']['challenger']['mae'],
                                          evaluations[n]['all_positive:finalized']['overall']['challenger']['mae'])) if eligible else 'L2'
    result = {'contract': registration['contract'], 'registrationSha256': registration_sha,
              'datasetSha256': sha(db), 'method': 'expanding chronological outer tests; historical already seen',
              'baseline': 'recorded same-run post; not published; champion policy/artifact unattested',
              'L2Reference': 'refitted independently within each fold; not frozen deployed L2',
              'folds': fold_results, 'results': evaluations, 'gates': gates, 'selected': selected,
              'status': f'PROMOTE {selected} TO SHADOW' if selected != 'L2' else 'REJECT NEW CANDIDATES, KEEP L2',
              'bandRegimeAllowanceMw': allowance, 'revision': stability,
              'leadAnalysis': {name: lead_report(test_rows, p) for name,p in predictions.items()},
              'transitions': {name: transitions(test_rows,p) for name,p in predictions.items()},
              'nativeIntervals': None, 'productionPromotion': False, 'limitations': registration['limitations']}
    exclusive_json(out/'PREREGISTRATION.json', registration)
    (out/'replay.jsonl').write_bytes(b''.join(encode(r) for r in replay))
    exclusive_json(out/'RESULTS.json', result)
    return result
