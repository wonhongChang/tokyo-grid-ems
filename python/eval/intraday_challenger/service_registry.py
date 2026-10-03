"""Versioned shadow membership, distinct from model and serving identities."""
import json
from datetime import date
from pathlib import Path
import re

import lightgbm

from .evidence import encode, sha, timestamp
from .shadow import _model
from .service_io import immutable_json as exclusive_json
from .storage import workspace

REGISTRY_CONTRACT = 'intraday-shadow-registry/1.0.0'
ACTIVE_LIMIT = 3
STATUSES = {'ACTIVE', 'PAUSED', 'RETIRED'}


def input_path(root, relative):
    root = Path(root).resolve(strict=True)
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError('Unsafe registry input path')
    if any(p.startswith('.env') or p in ('.git','.codex','.ssh','notes','auth.json') for p in rel.parts):
        raise ValueError('Secret/history inputs are forbidden')
    path = (root / rel).resolve(strict=True)
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Registry input outside read-only root')
    return path


def fingerprint(identity):
    return identity.get('modelSha256') or sha(encode(identity['artifacts']))


def feature_identity(identity):
    return sha(encode({'contract': identity['contract'], 'features': identity['features'],
                       'gateFeatures': identity.get('gateFeatures', [])}))


def read_registry(input_root, filename, now):
    content = input_path(input_root, filename).read_bytes()
    value = json.loads(content)
    if (set(value) != {'contract','version','championReference','challengers'}
            or value.get('contract') != REGISTRY_CONTRACT or type(value.get('version')) is not int or value['version'] < 1):
        raise ValueError('Invalid registry contract/version')
    entries = value.get('challengers')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Explicit challenger membership required')
    if sum(e.get('status') == 'ACTIVE' for e in entries) > ACTIVE_LIMIT:
        raise ValueError('Active challenger limit exceeded; propose retirement manually, never delete history')
    keys = set()
    for entry in entries:
        if set(entry) != {'modelName','modelVersion','identitySha256','combinedFingerprint','artifactPath',
                          'featureSchemaIdentity','trainingDatasetIdentity','trainingCutoff','shadowActivatedAt',
                          'status','researchDateRanges','historicalQualification','legacyEvidence'}:
            raise ValueError('Registry membership fields mismatch')
        key = entry['identitySha256']
        if not re.fullmatch('[0-9a-f]{64}', key) or key in keys:
            raise ValueError('Duplicate/invalid challenger identity')
        keys.add(key)
        if entry['status'] not in STATUSES or not entry.get('modelName') or not entry.get('modelVersion'):
            raise ValueError('Invalid model name/version/status')
        activation = timestamp(entry['shadowActivatedAt'])
        if activation > now or activation.date() <= date.fromisoformat(entry['trainingCutoff']):
            raise ValueError('Activation must be after training and not in the future')
        root = input_path(input_root, entry['artifactPath'])
        identity_bytes = input_path(input_root, str(Path(entry['artifactPath'])/'identity.json')).read_bytes()
        if sha(identity_bytes) != key:
            raise ValueError('Registry model identity hash mismatch')
        identity = json.loads(identity_bytes)
        if (entry['combinedFingerprint'] != fingerprint(identity)
                or entry['featureSchemaIdentity'] != feature_identity(identity)
                or entry['trainingDatasetIdentity'] != identity.get('datasetSha256', identity.get('inputManifestSha256'))
                or entry['trainingCutoff'] != identity['trainingEnd']):
            raise ValueError('Registry/model metadata mismatch')
        if lightgbm.__version__ != identity['lightgbmVersion']:
            raise ValueError('Native LightGBM runtime version mismatch')
        if 'artifacts' in identity:
            artifacts = {kind + '.txt': h for kind, h in identity['artifacts'].items()}
        else:
            artifacts = {'model.txt': identity['modelSha256']}
        for filename, h in artifacts.items():
            p = input_path(input_root, str(Path(entry['artifactPath']) / filename))
            if sha(p.read_bytes()) != h:
                raise ValueError('Registry native artifact hash mismatch')
        if not entry['researchDateRanges']:
            raise ValueError('Research exclusion ranges required')
        for period in entry['researchDateRanges']:
            if len(period) != 2 or date.fromisoformat(period[0]) > date.fromisoformat(period[1]):
                raise ValueError('Invalid research exclusion range')
        qualification = entry['historicalQualification']
        if qualification.get('state') != 'passed_for_shadow_only':
            raise ValueError('Historical shadow qualification required; not production approval')
        qbytes = input_path(input_root, qualification['path']).read_bytes()
        if sha(qbytes) != qualification['sha256']:
            raise ValueError('Qualification evidence hash mismatch')
        q = json.loads(qbytes)
        gates = q.get('gates', {}).get(identity['candidate'], {})
        if (not gates or not all(v is True for v in gates.values()) or q.get('productionPromotion') is not False
                or q.get('datasetSha256') != entry['trainingDatasetIdentity']):
            raise ValueError('Qualification gates/input identity are not confirmed')
        for legacy in entry.get('legacyEvidence', []):
            if sha(input_path(input_root, legacy['path']).read_bytes()) != legacy['sha256']:
                raise ValueError('Legacy evidence hash mismatch')
    return value, sha(content)


def adopt_registry(out, registry, registry_sha, previous, memberships, now):
    """Metadata for a model identity cannot be retroactively changed on re-admission."""
    if previous is not None and previous != registry:
        if registry['version'] <= previous['version']:
            raise ValueError('Registry updates require a higher version')
        before = {e['identitySha256']: e for e in previous['challengers']}
        after = {e['identitySha256']: e for e in registry['challengers']}
        if not set(before).issubset(after):
            raise ValueError('Registry must retain retired/paused identities')
        for key, old in before.items():
            if {k: v for k, v in old.items() if k != 'status'} != {k: v for k, v in after[key].items() if k != 'status'}:
                raise ValueError('Identity membership metadata is immutable')
    members = dict(memberships)
    for e in registry['challengers']:
        key = e['identitySha256']
        prior = members.get(key)
        if prior is None or prior['status'] != e['status']:
            members[key] = {'status': e['status'], 'effectiveAt': now.isoformat(),
                            'activeSince': max(timestamp(e['shadowActivatedAt']), now).isoformat()
                            if e['status'] == 'ACTIVE' else None}
    exclusive_json(workspace(out / 'registry-history' / (registry_sha + '.json')), registry)
    return members


def load_active(input_root, registry, cache):
    active = []
    for entry in registry['challengers']:
        if entry['status'] == 'ACTIVE':
            key = entry['identitySha256']
            if key not in cache:
                cache[key] = _model(input_path(input_root, entry['artifactPath']), key)
            active.append((entry, cache[key]))
    return active
