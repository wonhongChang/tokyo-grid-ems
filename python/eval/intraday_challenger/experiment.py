"""Chronological fit/select/evaluate pipeline with sealed preregistration."""
import json
from pathlib import Path

import numpy as np

from .evidence import closest, dataset, encode, implementation_sha, sha
from .evaluation import comparison, metrics, report, transitions
from .model import CANDIDATES, PARAMS, predict, save, train


def split(rows, periods):
    names = ("train", "validation", "holdout")
    for name in names:
        if periods[name][0] > periods[name][1]:
            raise ValueError("Reversed date range")
    if not periods['train'][1] < periods['validation'][0] <= periods['validation'][1] < periods['holdout'][0]:
        raise ValueError("Chronological partitions overlap")
    groups = {name: [r for r in rows if periods[name][0] <= r['date'] <= periods[name][1]
                    and r['actual_state'] == 'finalized' and r['actual'] is not None] for name in names}
    if any(not v for v in groups.values()):
        raise ValueError("Empty finalized partition")
    return groups


def acceptance(rows):
    rr = closest(rows)
    e = np.abs([r['champion'] - r['actual'] for r in rr])
    if not len(e):
        raise ValueError("Missing baseline tail population")
    return {"mae_ratio_max": .95, "rmse_ratio_max": 1.02, "date_wins_at_least_losses": True,
            "bias_absolute_allowance_mw": float(np.quantile(e, .50) * .1),
            "band_regime_mae_degradation_allowance_mw": float(np.quantile(e, .50) * .25),
            "regression_p95_max_mw": float(np.quantile(e, .90)),
            "max_regression_mw": float(np.quantile(e, .99)),
            "catastrophic_error_reference_mw": float(np.quantile(e, .99)),
            "catastrophic_frequency_allowance": .01, "transition_delta_mae_ratio_max": 1.1,
            "correction_step_p95_max_mw": float(np.quantile(e, .95)),
            "scope": "research shadow acceptance only; not production promotion thresholds",
            "rationale": "5% mean gain; 2% RMSE tolerance; tail/band allowances scaled to train champion error quantiles, not failed dates"}


def gates(rows, predictions, r, t, criteria):
    checks = {}
    for pop in ('all_positive:finalized', 'closest_0_120:finalized'):
        overall = r[pop]['overall']
        if overall is None:
            checks[pop + ':available'] = False
            continue
        c, p = overall['champion'], overall['challenger']
        checks[pop + ':mae_wape'] = p['mae'] <= c['mae'] * criteria['mae_ratio_max']
        checks[pop + ':rmse'] = p['rmse'] <= c['rmse'] * criteria['rmse_ratio_max']
        checks[pop + ':bias'] = abs(p['bias']) <= abs(c['bias']) + criteria['bias_absolute_allowance_mw']
        checks[pop + ':date_wins'] = overall['date_wins'] >= overall['date_losses']
        checks[pop + ':regression_p95'] = overall['regression_p95'] <= criteria['regression_p95_max_mw']
        checks[pop + ':max_regression'] = overall['max_regression'] <= criteria['max_regression_mw']
        for name in ('night', 'morning', 'midday', 'afternoon', 'evening', 'business', 'non_business'):
            group = r[pop][name]
            checks[pop + ':' + name] = None if group is None else group['challenger']['mae'] <= group['champion']['mae'] + criteria['band_regime_mae_degradation_allowance_mw']
        selected = [i for i, row in enumerate(rows) if row['actual_state'] == 'finalized' and row['actual'] is not None]
        if pop.startswith('closest'):
            ids = {id(x) for x in closest(rows)}
            selected = [i for i in selected if id(rows[i]) in ids]
        ce = np.array([abs(rows[i]['champion'] - rows[i]['actual']) for i in selected])
        pe = np.array([abs(predictions[i] - rows[i]['actual']) for i in selected])
        ref = criteria['catastrophic_error_reference_mw']
        checks[pop + ':catastrophic_frequency'] = bool(np.mean(pe > ref) <= np.mean(ce > ref) + criteria['catastrophic_frequency_allowance'])
    checks['transition_delta'] = None if not t.get('n') else t['challenger_delta_mae'] <= t['champion_delta_mae'] * criteria['transition_delta_mae_ratio_max']
    checks['transition_correction_step'] = None if not t.get('n') else t['correction_step_p95'] <= criteria['correction_step_p95_max_mw']
    return {"checks": checks, "pass": all(v is True for v in checks.values()),
            "failed": [k for k, v in checks.items() if v is False], "inconclusive": [k for k, v in checks.items() if v is None]}


def prepare(root, input_sha, output, periods):
    out = Path(output)
    if (out / 'PREREGISTRATION.json').exists():
        raise ValueError("Preregistration already exists")
    rows = dataset(root, input_sha)
    groups = split(rows, periods)
    out.mkdir(parents=True, exist_ok=True)
    dataset_bytes = b''.join(encode(r) for r in rows)
    registration = {'inputManifestSha256': input_sha, 'datasetSha256': sha(dataset_bytes), 'periods': periods, 'candidates': CANDIDATES,
                    'params': PARAMS, 'acceptance': acceptance(groups['train']),
                    'selection': 'Lowest validation 0.5*all-positive MAE + 0.5*closest MAE among tail-safe candidates; otherwise lowest score retained with failed gates disclosed. No holdout selection.',
                    'trainingWeight': '1 / captures per date/hour', 'holdoutUse': 'Once, after validation selection sealed. No refit after holdout.',
                    'labelAvailability': 'Finalized at research freeze; historical ETL delivery timestamps not attested. Chronological retrospective experiment, not historical deployed model.',
                    'baselineIdentity': 'Recorded same-run post; historical artifact/policy missing, never inferred.',
                    'weather': 'Excluded: issue-time source timestamps not attested.',
                    'counterexamples': [['2026-09-22',20],['2026-09-15',21],['2026-09-26',21],['2026-08-31',12],['2026-09-07',9],
                        ['2026-09-14',9],['2026-09-24',11],['2026-08-28',11],['2026-09-06',22],['2026-09-08',10],['2026-09-11',14],['2026-09-16',14]],
                    'counts': {k: {'rows': len(v), 'dates': len({r['date'] for r in v}), 'closest': len(closest(v))} for k,v in groups.items()},
                    'implementationHashes': {p.name: implementation_sha(p) for p in Path(__file__).parent.glob('*.py')}}
    (out / 'PREREGISTRATION.json').write_bytes(encode(registration))
    (out / 'dataset.jsonl').write_bytes(dataset_bytes)
    return registration


def run(output, registration_sha):
    out = Path(output)
    b = (out / 'PREREGISTRATION.json').read_bytes()
    if sha(b) != registration_sha:
        raise ValueError("Preregistration hash mismatch")
    reg = json.loads(b)
    if reg['candidates'] != CANDIDATES or reg['params'] != PARAMS:
        raise ValueError("Candidate specifications changed")
    for name, h in reg['implementationHashes'].items():
        if implementation_sha(Path(__file__).with_name(name)) != h:
            raise ValueError("Preregistered implementation changed: " + name)
    if (out / 'SELECTION.json').exists():
        raise ValueError("Experiment already executed")
    dataset_bytes = (out / 'dataset.jsonl').read_bytes()
    if sha(dataset_bytes) != reg.get('datasetSha256'):
        raise ValueError("Preregistered dataset hash mismatch")
    rows = [json.loads(x) for x in dataset_bytes.decode('utf-8').splitlines()]
    groups = split(rows, reg['periods'])
    validation = {}
    for name in CANDIDATES:
        booster = train(groups['train'], name)
        save(booster, out / 'validation-models' / name, name, groups['train'], reg['inputManifestSha256'])
        p = predict(booster, groups['validation'], CANDIDATES[name])
        r, t = report(groups['validation'], p), transitions(groups['validation'], p)
        g = gates(groups['validation'], p, r, t, reg['acceptance'])
        score = .5 * r['all_positive:finalized']['overall']['challenger']['mae'] + .5 * r['closest_0_120:finalized']['overall']['challenger']['mae']
        validation[name] = {'report': r, 'transitions': t, 'gates': g, 'selectionScore': score}
    # Prefer candidates that satisfy the preregistered tail limits, not a single failure case.
    safe = [n for n,v in validation.items() if not any('regression' in k or 'catastrophic' in k for k in v['gates']['failed'])]
    selected = min(safe or list(CANDIDATES), key=lambda n: (validation[n]['selectionScore'], n))
    selection = {'candidate': selected, 'validation': validation, 'preregistrationSha256': registration_sha,
                 'holdoutOpened': False, 'tailSafeCandidates': safe}
    (out / 'SELECTION.json').write_bytes(encode(selection))
    results = {}
    fit = groups['train'] + groups['validation']
    for name in CANDIDATES:
        booster = train(fit, name)
        identity = save(booster, out / 'models' / name, name, fit, reg['inputManifestSha256'])
        p = predict(booster, rows, CANDIDATES[name])
        index = {id(r): i for i,r in enumerate(rows)}
        h = groups['holdout']; hp = [p[index[id(x)]] for x in h]
        rr, tt = report(h, hp), transitions(h, hp)
        counterexamples = []
        near = closest([r for r in rows if r['actual'] is not None])
        for day, hour in reg['counterexamples']:
            found = [r for r in near if r['date'] == day and r['hour'] == hour]
            counterexamples.append({'date': day, 'hour': hour, 'partition': next((k for k,(lo,hi) in reg['periods'].items() if lo <= day <= hi), 'other'),
                'state': 'available' if found else 'unavailable',
                'comparison': comparison(found, [p[index[id(x)]] for x in found]) if found else None,
                'independent': reg['periods']['holdout'][0] <= day <= reg['periods']['holdout'][1]})
        live = [r for r in rows if r['date'] > reg['periods']['holdout'][1]]
        results[name] = {'identity': identity, 'holdout': rr, 'transitions': tt, 'gates': gates(h,hp,rr,tt,reg['acceptance']),
                         'provisional': report(live,[p[index[id(x)]] for x in live]), 'counterexamples': counterexamples}
        (out / (name + '-replay.jsonl')).write_bytes(b''.join(encode(dict(r, challenger=pred)) for r,pred in zip(rows,p)))
    status = 'PROMOTE TO SHADOW' if results[selected]['gates']['pass'] else 'RETAIN CHALLENGER'
    result = {'selected': selected, 'status': status, 'preregistrationSha256': registration_sha,
              'selectionSha256': sha((out / 'SELECTION.json').read_bytes()), 'results': results,
              'nativeIntervals': None, 'productionChanged': False,
              'holdoutIndependentOfThisFit': True, 'historicalDatesPreviouslyReviewed': True}
    (out / 'RESULTS.json').write_bytes(encode(result))
    return result
