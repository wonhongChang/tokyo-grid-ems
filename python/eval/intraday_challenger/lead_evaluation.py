"""Fixed lead bins and matched cross-issue stability, distinct from target shape."""
import numpy as np

from .evidence import closest, timestamp
from .evaluation import BANDS, comparison

LEAD_BUCKETS = ((0, 30), (30, 60), (60, 120), (120, 180), (180, 360), (360, None))


def revisions(records, predictions):
    if len(records) != len(predictions):
        raise ValueError('Paired prediction length mismatch')
    groups = {}
    for r, p in zip(records, predictions):
        if r['lead_minutes'] > 0:
            groups.setdefault((r['date'], r['hour']), []).append((r, p))
    baseline, candidate, references = [], [], []
    for rows in groups.values():
        rows.sort(key=lambda x: x[0]['issued_at'])
        for (a, p), (b, q) in zip(rows, rows[1:]):
            gap = (timestamp(b['issued_at']) - timestamp(a['issued_at'])).total_seconds() / 60
            if 0 < gap <= 120:
                baseline.append(abs(b['champion'] - a['champion']))
                candidate.append(abs(q - p))
                references.append({'date': a['date'], 'hour': a['hour'], 'previous': a['issued_at'], 'issue': b['issued_at']})
            elif gap == 0:
                raise ValueError('Duplicate issue-target revision')
    def describe(values):
        return {'mean': float(np.mean(values)), 'p95': float(np.quantile(values, .95)),
                'max': float(max(values))} if values else None
    return {'n': len(baseline), 'champion': describe(baseline), 'challenger': describe(candidate),
            'population': 'same-target adjacent positive issues, gap <=120 minutes', 'pairs': references}


def lead_report(records, predictions):
    if len(records) != len(predictions):
        raise ValueError('Paired prediction length mismatch')
    index = {id(r): i for i, r in enumerate(records)}
    def summarize(rows):
        p = [predictions[index[id(r)]] for r in rows]
        c = comparison(rows, p) if rows else None
        return {'metrics': c, 'revision': revisions(rows, p)}
    result = {'bucketsMinutes': LEAD_BUCKETS, 'groups': {}}
    for lo, hi in LEAD_BUCKETS:
        selected = [r for r in records if lo < r['lead_minutes'] and (hi is None or r['lead_minutes'] <= hi)]
        key = f'({lo},{hi if hi is not None else "inf"}]'
        groups = {'overall': selected, 'business': [r for r in selected if not r['features']['non_business']],
                  'non_business': [r for r in selected if r['features']['non_business']]}
        groups.update({name: [r for r in selected if lo_h <= r['hour'] <= hi_h]
                       for name, (lo_h, hi_h) in BANDS.items()})
        result['groups'][key] = {g: summarize(rows) for g, rows in groups.items()}
    result['closest'] = summarize(closest(records))
    result['all'] = summarize(records)
    return result
