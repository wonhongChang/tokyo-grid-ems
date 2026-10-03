"""Experimental lead-aware error and chronological learned-blend models.

Kept separate from the frozen L1/L2/L3 implementation and feature identity.
"""
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .evidence import FEATURES, encode, implementation_sha, sha
from .model import CANDIDATES, PARAMS, predict as l2_predict, train as l2_train

CONTRACT = 'intraday-lead-research/1.0.0'
INTERACTIONS = ('raw_residual_mean', 'post_residual_mean', 'raw_residual_trend',
                'slope_disagreement', 'post_minus_pre', 'actual_delta_mean')
EXTRA = ('lead_log', 'lead_sqrt', 'observed_fraction', 'age_to_lead') + tuple(
    name + '_lead_scaled' for name in INTERACTIONS)
GATE = ('predicted_correction', 'abs_predicted_correction', 'scaled_predicted_correction')
GATE_PARAMS = dict(PARAMS, objective='regression', n_estimators=100,
                   num_leaves=6, min_child_samples=60, reg_lambda=20)


def scale(records):
    lead = np.array([r['lead_minutes'] for r in records], float)
    if not np.isfinite(lead).all() or (lead <= 0).any():
        raise ValueError('Only finite positive leads are supported')
    return np.sqrt(1 + lead / 60)


def frame(records, corrections=None):
    scales = scale(records)
    rows = []
    for r, s in zip(records, scales):
        f = r['features']
        lead = r['lead_minutes']
        row = {name: f.get(name) for name in FEATURES}
        observed = f.get('observed_count')
        issue_hour = f.get('issue_hour')
        age = f.get('observation_age_minutes')
        row.update(lead_log=float(np.log1p(lead / 60)), lead_sqrt=float(s),
                   observed_fraction=observed / max(1, issue_hour) if observed is not None and issue_hour is not None else None,
                   age_to_lead=age / (60 + lead) if age is not None else None)
        row.update({name + '_lead_scaled': f.get(name) / s if f.get(name) is not None else None
                    for name in INTERACTIONS})
        rows.append(row)
    names = FEATURES + EXTRA
    if corrections is not None:
        if len(corrections) != len(records) or not np.isfinite(corrections).all():
            raise ValueError('Finite paired corrections required')
        names += GATE
        for row, correction, s in zip(rows, corrections, scales):
            row.update(predicted_correction=float(correction), abs_predicted_correction=float(abs(correction)),
                       scaled_predicted_correction=float(correction / s))
    return pd.DataFrame(rows, columns=names, dtype=float)


def weights(records):
    counts = {}
    for r in records:
        k = (r['date'], r['hour'])
        counts[k] = counts.get(k, 0) + 1
    return np.array([1 / counts[(r['date'], r['hour'])] for r in records])


def finalized(records):
    if not records or any(r['actual_state'] != 'finalized' or r['actual'] is None for r in records):
        raise ValueError('Only finalized labels may train')


def fit(records, name):
    finalized(records)
    dates = sorted({r['date'] for r in records})
    if name == 'L4':
        target = np.array([r['actual'] - r['champion'] for r in records]) / scale(records)
        model = lgb.LGBMRegressor(**PARAMS)
        model.fit(frame(records), target, sample_weight=weights(records))
        return {'candidate': name, 'error': model.booster_, 'gate': None, 'oof': []}
    if name != 'L5' or len(dates) <= 8:
        raise ValueError('L5 requires more than eight training dates')
    oof, corrections, provenance = [], [], []
    for start in range(8, len(dates), 3):
        train_dates = set(dates[:start])
        test_dates = set(dates[start:start + 3])
        training = [r for r in records if r['date'] in train_dates]
        testing = [r for r in records if r['date'] in test_dates]
        model = l2_train(training, 'L2')
        predicted = l2_predict(model, testing, CANDIDATES['L2'])
        oof.extend(testing)
        corrections.extend(p - r['champion'] for r, p in zip(testing, predicted))
        provenance.append({'trainingEnd': max(train_dates), 'testStart': min(test_dates),
                           'testEnd': max(test_dates), 'rows': len(testing)})
    d = np.asarray(corrections)
    remaining = np.array([r['actual'] - r['champion'] for r in oof])
    # Optimal bounded weight is a training label, never an inference input.
    target = np.clip(np.divide(remaining, d, out=np.zeros_like(d), where=d != 0), 0, 1)
    gate = lgb.LGBMRegressor(**GATE_PARAMS)
    gate.fit(frame(oof, d), target, sample_weight=weights(oof))
    return {'candidate': name, 'error': l2_train(records, 'L2'), 'gate': gate.booster_, 'oof': provenance}


def predict(model, records, return_weights=False):
    if not records:
        return ([], []) if return_weights else []
    if model['candidate'] == 'L4':
        delta = model['error'].predict(frame(records), num_threads=2) * scale(records)
        blend = np.ones(len(records))
    else:
        delta = np.asarray(l2_predict(model['error'], records, CANDIDATES['L2'])) - np.array([r['champion'] for r in records])
        blend = np.clip(model['gate'].predict(frame(records, delta), num_threads=2), 0, 1)
    values = [float(r['champion'] + w * d) for r, w, d in zip(records, blend, delta)]
    return (values, blend.tolist()) if return_weights else values


def save(model, directory, records, dataset_sha, revision):
    p = Path(directory)
    if p.exists() and any(p.iterdir()):
        raise ValueError('Model output already exists')
    p.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for kind in ('error', 'gate'):
        if model[kind] is not None:
            content = model[kind].model_to_string().encode()
            (p / (kind + '.txt')).write_bytes(content)
            artifacts[kind] = sha(content)
    identity = {'contract': CONTRACT, 'candidate': model['candidate'], 'artifacts': artifacts,
                'features': list(FEATURES + EXTRA), 'gateFeatures': list(GATE),
                'params': PARAMS, 'gateParams': GATE_PARAMS, 'oof': model['oof'],
                'datasetSha256': dataset_sha, 'trainingStart': min(r['date'] for r in records),
                'trainingEnd': max(r['date'] for r in records), 'codeRevision': revision,
                'implementationSha256': implementation_sha(__file__),
                'baseImplementationSha256': implementation_sha(Path(__file__).with_name('model.py')),
                'featureImplementationSha256': implementation_sha(Path(__file__).with_name('evidence.py')),
                'lightgbmVersion': lgb.__version__, 'productionPromotion': False}
    (p / 'identity.json').write_bytes(encode(identity))
    return identity


def load(directory, identity_sha):
    p = Path(directory)
    b = (p / 'identity.json').read_bytes()
    if sha(b) != identity_sha:
        raise ValueError('Model identity hash mismatch')
    identity = json.loads(b)
    if identity['contract'] != CONTRACT or identity['candidate'] not in ('L4', 'L5'):
        raise ValueError('Candidate contract mismatch')
    for field, file in (('implementationSha256', __file__),
                        ('baseImplementationSha256', Path(__file__).with_name('model.py')),
                        ('featureImplementationSha256', Path(__file__).with_name('evidence.py'))):
        if identity[field] != implementation_sha(file):
            raise ValueError('Implementation hash mismatch')
    if identity['features'] != list(FEATURES + EXTRA) or identity['gateFeatures'] != list(GATE):
        raise ValueError('Feature contract mismatch')
    model = {'candidate': identity['candidate'], 'error': None, 'gate': None, 'oof': identity['oof']}
    expected = {'error'} if model['candidate'] == 'L4' else {'error', 'gate'}
    if set(identity['artifacts']) != expected or identity['params'] != PARAMS or identity['gateParams'] != GATE_PARAMS:
        raise ValueError('Model contract mismatch')
    for kind, h in identity['artifacts'].items():
        b = (p / (kind + '.txt')).read_bytes()
        if sha(b) != h:
            raise ValueError('Model artifact hash mismatch')
        model[kind] = lgb.Booster(model_str=b.decode())
    return model, identity
