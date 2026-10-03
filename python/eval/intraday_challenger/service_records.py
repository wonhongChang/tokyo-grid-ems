"""Immutable multi-model captures; live eligibility is not historical issue lead."""
import json
from pathlib import Path

from .evidence import encode, features, number, sha, timestamp
from .service_feed import source_bytes
from .service_io import immutable_json as exclusive_json
from .storage import workspace

CAPTURE_CONTRACT = 'intraday-multi-shadow-capture/1.0.0'
LIVE_POLICY = 'intraday-shadow-live-eligibility/1.0.0'


def read_runs(out):
    runs = []
    for path in sorted((out / 'predictions').glob('*.json')):
        b = workspace(path).read_bytes()
        if sha(b) != path.stem:
            raise ValueError('Immutable prediction record hash mismatch')
        run = json.loads(b)
        key = run['identitySha256']
        if (run['contract'] != CAPTURE_CONTRACT or run['identitySha256'] != key
                or sha(encode(run['modelIdentity'])) != key):
            raise ValueError('Stored model identity mismatch')
        runs.append((run, str(path.relative_to(out)).replace('\\', '/'), sha(b)))
    return runs


def eligibility(row, entry, active_since, captured_at, delay, max_delay):
    reasons = []
    prospective = timestamp(row['target']) > captured_at
    delayed = delay > max_delay / 60
    if not prospective:
        reasons.append('retrospective_at_capture')
    if delayed:
        reasons.append('delayed_capture')
    if timestamp(row['issued_at']) < max(timestamp(entry['shadowActivatedAt']), timestamp(active_since)):
        reasons.append('issue_precedes_active_membership')
    if row['date'] <= entry['trainingCutoff']:
        reasons.append('training_period')
    if any(lo <= row['date'] <= hi for lo, hi in entry['researchDateRanges']):
        reasons.append('research_used_date')
    return {'targetTiming': 'prospective' if prospective else 'retrospective',
            'captureStatus': 'delayed' if delayed else 'prospective' if prospective else 'retrospective',
            'prospective_at_shadow_capture': prospective, 'independentEligible': not reasons,
            'independentExclusions': reasons, 'liveEligibilityPolicy': LIVE_POLICY,
            'maxIndependentCaptureDelaySeconds': max_delay}


def capture_shared(out, source, active, membership, registry_sha, now, max_delay, existing, seen_issues=None, clock=None):
    """Parse and reconstruct once; model inference never sees the later actual feed."""
    pending = [(entry, model) for entry, model in active
               if (entry['identitySha256'], source['sha256']) not in existing]
    if not pending:
        return []
    snapshot = json.loads(source_bytes(out, source))
    if snapshot['date'] != source['sourcePath'].split('/')[-2]:
        raise ValueError('Snapshot path/date mismatch')
    issued = timestamp(snapshot['generatedAt'])
    if issued > now:
        raise ValueError('Future issue timestamp rejected')
    rows = list(features(snapshot))
    pointers = {int(r['hour']): i for i, r in enumerate(snapshot['hourlyDiagnostics'])}
    results = []
    for entry, (_, identity, forecast) in pending:
        key = entry['identitySha256']
        pair = (key, issued.isoformat())
        if seen_issues is not None and pair in seen_issues:
            results.append({'state':'unavailable','identitySha256':key, 'errorType':'DuplicateIssueVintage'})
            continue
        if snapshot['date'] <= entry['trainingCutoff']:
            results.append({'state':'not_applicable','identitySha256':key,
                            'reason':'snapshot_overlaps_training_period','sourceSha256':source['sha256']})
            continue
        try:
            predictions = forecast(rows)
            if len(predictions) != len(rows) or any(number(v) is None for v in predictions):
                raise ValueError('Invalid challenger prediction population')
        except (ValueError, KeyError, RuntimeError, TypeError) as exc:
            results.append({'state':'unavailable', 'identitySha256':key, 'errorType':type(exc).__name__})
            continue
        completed_at = clock() if clock is not None else now
        if completed_at < now:
            raise ValueError('Capture completion clock moved backwards')
        delay = (completed_at - issued).total_seconds() / 60
        captured = []
        for row, value in zip(rows, predictions):
            timing = eligibility(row, entry, membership[key]['activeSince'], completed_at, delay, max_delay)
            captured.append(dict(row, challenger=float(value), actual=None, actual_state='unavailable',
                source_sha=source['sha256'], source_pointer='/hourlyDiagnostics/' + str(pointers[row['hour']]),
                source_revision=source['revision'], model_identity=entry['combinedFingerprint'],
                model_identity_sha=key, feature_identity=entry['featureSchemaIdentity'],
                training_end=entry['trainingCutoff'], native_interval=None,
                capture_lead_minutes=(timestamp(row['target']) - completed_at).total_seconds()/60,
                recorded_at=completed_at.isoformat(), capture_delay_minutes=delay, **timing))
        record = {'contract': CAPTURE_CONTRACT, 'identitySha256': key, 'modelIdentity': identity,
                  'membership': entry, 'activeSince': membership[key]['activeSince'],
                  'registrySha256': registry_sha, 'source': source, 'issuedAt': issued.isoformat(),
                  'recordedAt': completed_at.isoformat(), 'captureDelayMinutes': delay, 'rows': captured,
                  'championReference': {'basis': 'same-run recorded post, not published',
                       'artifactIdentity': None, 'servingPolicyIdentity': None,
                       'state': 'historical champion artifact/policy unattested'},
                  'productionPromotion': False, 'predictionInterval': 'unavailable; point correction only'}
        content_hash = sha(encode(record))
        target = workspace(out / 'predictions' / (content_hash + '.json'))
        exclusive_json(target, record)
        existing.add((key, source['sha256']))
        if seen_issues is not None:
            seen_issues.add(pair)
        results.append({'identitySha256': key, 'path': str(target.relative_to(out)),
                        'recordSha256': content_hash, 'rows': len(captured), 'delayMinutes': delay,
                        'prospective': sum(r['prospective_at_shadow_capture'] for r in captured),
                        'independentEligible': sum(r['independentEligible'] for r in captured)})
    return results
