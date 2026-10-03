"""Matched-population numeric comparisons. No serving or promotion authority."""
import numpy as np

from .evidence import closest

BANDS = {"night": (0, 5), "morning": (6, 11), "midday": (12, 13), "afternoon": (14, 17), "evening": (18, 23)}


def metrics(actual, prediction):
    a, p = np.asarray(actual, float), np.asarray(prediction, float)
    if len(a) != len(p) or not len(a) or not np.isfinite(a).all() or not np.isfinite(p).all():
        raise ValueError("Metrics require a finite paired population")
    e = p - a
    return {"n": len(a), "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt(np.mean(e ** 2))),
            "wape_pct": float(100 * np.abs(e).sum() / np.abs(a).sum()) if np.abs(a).sum() else None,
            "bias": float(e.mean()), "p95_abs_error": float(np.quantile(np.abs(e), .95)), "max_abs_error": float(np.abs(e).max())}


def comparison(records, predictions):
    if len(records) != len(predictions) or not records:
        raise ValueError("Paired prediction length mismatch")
    a = np.array([r["actual"] for r in records])
    b = np.array([r["champion"] for r in records])
    p = np.array(predictions)
    delta = np.abs(p - a) - np.abs(b - a)
    worse = delta[delta > 1e-9]
    daily = {}
    for day in sorted({r['date'] for r in records}):
        mask = np.array([r['date'] == day for r in records])
        daily[day] = {"champion": metrics(a[mask], b[mask]), "challenger": metrics(a[mask], p[mask]),
                      "delta_mae": float(delta[mask].mean())}
    return {"champion": metrics(a, b), "challenger": metrics(a, p),
            "improved": int((delta < -1e-9).sum()), "worsened": int((delta > 1e-9).sum()), "unchanged": int((np.abs(delta) <= 1e-9).sum()),
            "regression_p50": float(np.quantile(worse, .50)) if len(worse) else 0.0,
            "regression_p90": float(np.quantile(worse, .90)) if len(worse) else 0.0,
            "regression_p95": float(np.quantile(worse, .95)) if len(worse) else 0.0,
            "max_regression": max(0.0, float(delta.max())), "max_improvement": max(0.0, float(-delta.min())),
            "date_wins": sum(v['delta_mae'] < -1e-9 for v in daily.values()),
            "date_losses": sum(v['delta_mae'] > 1e-9 for v in daily.values()), "daily": daily,
            "worst_regressions": [dict(date=records[i]['date'], hour=records[i]['hour'], issue=records[i]['issued_at'],
                                        source_sha=records[i]['source_sha'], lead=records[i]['lead_minutes'], actual=float(a[i]),
                                        champion=float(b[i]), challenger=float(p[i]), delta_abs_error=float(delta[i]))
                                  for i in np.argsort(-delta)[:10]]}


def report(records, predictions):
    indices = {id(r): i for i, r in enumerate(records)}
    if len(records) != len(predictions):
        raise ValueError("Prediction length mismatch")
    result = {}
    for pop, rows in (("all_positive", records), ("closest_0_120", closest(records))):
        for state in ("finalized", "provisional"):
            selected = [r for r in rows if r['actual_state'] == state and r['actual'] is not None]
            groups = {"overall": selected}
            groups.update({band: [r for r in selected if lo <= r['hour'] <= hi] for band, (lo, hi) in BANDS.items()})
            groups.update({"business": [r for r in selected if not r['features']['non_business']],
                           "non_business": [r for r in selected if r['features']['non_business']],
                           "lead_0_120": [r for r in selected if r['lead_minutes'] <= 120],
                           "lead_120_360": [r for r in selected if 120 < r['lead_minutes'] <= 360],
                           "lead_gt_360": [r for r in selected if r['lead_minutes'] > 360]})
            result[pop + ':' + state] = {g: comparison(rr, [predictions[indices[id(r)]] for r in rr]) if rr else None for g, rr in groups.items()}
    return result


def transitions(records, predictions):
    """Adjacent target changes within the same run, never across vintages."""
    grouped = {}
    for r, pred in zip(records, predictions):
        if r['actual_state'] == 'finalized' and r['actual'] is not None:
            grouped.setdefault((r['date'], r['issued_at']), {})[r['hour']] = (r, pred)
    c_errors, p_errors, correction_steps = [], [], []
    for rows in grouped.values():
        for h, (r, p) in rows.items():
            if h - 1 not in rows:
                continue
            previous, pp = rows[h - 1]
            ad = r['actual'] - previous['actual']
            c_errors.append(abs(r['champion'] - previous['champion'] - ad))
            p_errors.append(abs(p - pp - ad))
            correction_steps.append(abs((p - r['champion']) - (pp - previous['champion'])))
    if not c_errors:
        return {"n": 0, "state": "unavailable"}
    return {"n": len(c_errors), "champion_delta_mae": float(np.mean(c_errors)), "challenger_delta_mae": float(np.mean(p_errors)),
            "correction_step_p95": float(np.quantile(correction_steps, .95)), "correction_step_max": float(max(correction_steps))}
