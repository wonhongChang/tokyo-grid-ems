"""Stage frozen, qualified artifacts for a read-only Docker shadow mount."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from python.eval.intraday_challenger.evidence import encode, sha
from python.eval.intraday_challenger.service import SERVICE_CONTRACT
from python.eval.intraday_challenger.service_io import immutable_bytes, immutable_json
from python.eval.intraday_challenger.service_registry import REGISTRY_CONTRACT, feature_identity, fingerprint
from python.eval.intraday_challenger.shadow import _model, _now
from python.eval.intraday_challenger.storage import workspace


def prepare(model_root, identity_sha, qualification, qualification_sha, deployment_root,
            research_ranges, name, version, legacy_roots=()):
    source = workspace(model_root)
    _, identity, _ = _model(source, identity_sha)
    qualification = workspace(qualification)
    q = qualification.read_bytes()
    if sha(q) != qualification_sha:
        raise ValueError('Qualification hash mismatch')
    result = json.loads(q)
    gates = result.get('gates', {}).get(identity['candidate'], {})
    if not gates or not all(v is True for v in gates.values()) or result.get('productionPromotion') is not False:
        raise ValueError('Recorded historical qualification must pass; this is shadow-only admission')
    if result.get('datasetSha256') != identity.get('datasetSha256', identity.get('inputManifestSha256')):
        raise ValueError('Qualification/training input identity mismatch')
    for lo, hi in research_ranges:
        if date.fromisoformat(lo) > date.fromisoformat(hi):
            raise ValueError('Invalid research exclusion range')
    if not any(lo <= identity['trainingEnd'] <= hi for lo,hi in research_ranges):
        raise ValueError('Research ranges must include the training cutoff and all used review dates')
    out = workspace(deployment_root)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Deployment already exists; registry updates must be deliberate/versioned')
    artifacts = identity.get('artifacts')
    files = ['identity.json'] + ([kind+'.txt' for kind in artifacts] if artifacts else ['model.txt'])
    model_dir = 'models/' + identity_sha
    for filename in files:
        immutable_bytes(out/model_dir/filename, (source/filename).read_bytes())
    immutable_bytes(out/'qualification.json',q)
    legacy = []
    for root in legacy_roots:
        for path in sorted(workspace(root).glob('runs/*/*.json')):
            b = path.read_bytes(); record=json.loads(b)
            if record.get('modelIdentitySha256') != identity_sha:
                raise ValueError('Legacy archive belongs to another identity')
            h = sha(b); relative = 'legacy/' + h + '.json'
            immutable_bytes(out/relative,b)
            if not any(x['sha256']==h for x in legacy):
                legacy.append({'path':relative,'sha256':h,'state':'context-only; not activation-era independent evidence'})
    entry = {'modelName':name,'modelVersion':version,'identitySha256':identity_sha,
             'combinedFingerprint':fingerprint(identity),'artifactPath':model_dir,
             'featureSchemaIdentity':feature_identity(identity),
             'trainingDatasetIdentity':identity.get('datasetSha256',identity.get('inputManifestSha256')),
             'trainingCutoff':identity['trainingEnd'],'shadowActivatedAt':_now().isoformat(),
             'status':'ACTIVE','researchDateRanges':research_ranges,
             'historicalQualification':{'state':'passed_for_shadow_only','path':'qualification.json','sha256':qualification_sha},
             'legacyEvidence':legacy}
    registry = {'contract':REGISTRY_CONTRACT,'version':1,
                'championReference':'same-run recorded post; historical native artifact and serving policy unattested',
                'challengers':[entry]}
    immutable_json(out/'registry.json',registry)
    immutable_json(out/'config.json', {'contract':SERVICE_CONTRACT,
        'remote':'https://github.com/wonhongChang/tokyo-grid-ems.git',
        'startDate':(date.fromisoformat(identity['trainingEnd'])+timedelta(days=1)).isoformat(),
        'registry':'registry.json','pollIntervalSeconds':600,
        'maxIndependentCaptureDelaySeconds':900,'healthMaxLoopAgeSeconds':2100})
    return {'deployment':str(out),'identitySha256':identity_sha,'legacyRecordsPreserved':len(legacy),
            'shadowActivatedAt':entry['shadowActivatedAt'],'productionChanged':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-root',required=True)
    p.add_argument('--identity-sha',required=True)
    p.add_argument('--qualification',required=True)
    p.add_argument('--qualification-sha',required=True)
    p.add_argument('--deployment-root',default='data/intraday_challenger/shadow-deployment')
    p.add_argument('--research-range',nargs=2,action='append',required=True)
    p.add_argument('--name',required=True)
    p.add_argument('--version',required=True)
    p.add_argument('--legacy-root',action='append',default=[])
    a=p.parse_args()
    try:
        print(json.dumps(prepare(a.model_root,a.identity_sha,a.qualification,a.qualification_sha,
            a.deployment_root,a.research_range,a.name,a.version,a.legacy_root)))
    except (ValueError,KeyError,OSError) as exc:
        print(json.dumps({'state':'unavailable','type':type(exc).__name__,'reason':str(exc)}))
        raise SystemExit(2)


if __name__=='__main__':main()
