import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from python.eval.intraday_challenger import storage, service, service_feed as feed
from python.eval.intraday_challenger.evidence import encode, features, sha, timestamp
from python.eval.intraday_challenger.model import save, train
from python.eval.intraday_challenger.service_evaluation import evaluate
from python.eval.intraday_challenger.service_io import WorkerLock, atomic_json, immutable_json
from python.eval.intraday_challenger.service_records import capture_shared, eligibility, read_runs
from python.eval.intraday_challenger.service_registry import (REGISTRY_CONTRACT, adopt_registry, feature_identity,
    fingerprint, input_path, load_active, read_registry)
from tests.test_intraday_challenger import records, snapshot

NOW = timestamp('2026-10-05T10:31:00+09:00')


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(service, '_now', lambda: NOW)
    inputs = tmp_path/'inputs'; inputs.mkdir()
    out = tmp_path/'data/intraday_challenger/live'
    entries = []
    for index in range(2):
        rr = records('2026-09-21')
        for row in rr:
            row['actual'] += index*80
        directory = inputs/('model'+str(index))
        m = save(train(rr,'L2'),directory,'L2',rr,sha(encode({'training':index})))
        q = {'productionPromotion':False,'gates':{'L2':{'fixture_gate':True}},'datasetSha256':m['inputManifestSha256']}
        qpath='qualification'+str(index)+'.json'
        (inputs/qpath).write_bytes(encode(q))
        key = sha((directory/'identity.json').read_bytes())
        entries.append({'modelName':'L'+str(index+5), 'modelVersion':'1', 'identitySha256':key,
            'combinedFingerprint':fingerprint(m), 'artifactPath':directory.name,
            'featureSchemaIdentity':feature_identity(m), 'trainingDatasetIdentity':m['inputManifestSha256'],
            'trainingCutoff':m['trainingEnd'], 'shadowActivatedAt':'2026-10-05T10:00:00+09:00',
            'status':'ACTIVE', 'researchDateRanges':[['2026-09-01','2026-10-03']],
            'historicalQualification':{'state':'passed_for_shadow_only','path':qpath,'sha256':sha(encode(q))},
            'legacyEvidence':[]})
    registry = {'contract':REGISTRY_CONTRACT,'version':1,'championReference':'same-run post only; identity unattested',
                'challengers':entries}
    (inputs/'registry.json').write_bytes(encode(registry))
    settings = {'contract':service.SERVICE_CONTRACT,'remote':'https://github.com/example/repo',
        'startDate':'2026-10-04','registry':'registry.json','pollIntervalSeconds':600,
        'maxIndependentCaptureDelaySeconds':900,'healthMaxLoopAgeSeconds':2100}
    (inputs/'config.json').write_bytes(encode(settings))
    return inputs,out,registry


def add_source(out, value, path, revision='a'*40):
    h = sha(encode(value))
    target = out/'feed/sources'/(h+'.json')
    immutable_json(target,value)
    return {'cache':str(target.relative_to(out)).replace('\\','/'), 'sha256':h,
            'revision':revision,'sourcePath':path,'gitBlob':'b'*40}


def captures(env, now=NOW, source=None):
    inputs,out,registry=env
    ref = add_source(out,source or snapshot(),feed.PREFIX+'2026-10-05/run.json')
    active=load_active(inputs,registry,{})
    members={e['identitySha256']:{'activeSince':e['shadowActivatedAt'],'status':'ACTIVE'} for e in registry['challengers']}
    result=capture_shared(out,ref,active,members,sha(encode(registry)),now,900,set())
    return ref,result


def test_registry_identity_and_artifact_separation(env):
    inputs,out,registry=env
    value,h=read_registry(inputs,'registry.json',NOW)
    assert value==registry and h==sha(encode(registry))
    assert len(load_active(inputs,registry,{}))==2
    a,b=registry['challengers']
    assert a['identitySha256']!=b['identitySha256'] and a['combinedFingerprint']!=b['combinedFingerprint']
    (inputs/'model0/model.txt').write_bytes(b'changed')
    with pytest.raises(ValueError,match='artifact'):read_registry(inputs,'registry.json',NOW)


@pytest.mark.parametrize('field', ['combinedFingerprint','featureSchemaIdentity','trainingDatasetIdentity','trainingCutoff'])
def test_registry_metadata_mismatch_rejected(env,field):
    inputs,out,r=env
    r['challengers'][0][field]='2020-01-01' if field=='trainingCutoff' else 'incorrect'
    (inputs/'registry.json').write_bytes(encode(r))
    with pytest.raises(ValueError):read_registry(inputs,'registry.json',NOW)


def test_active_limit_no_auto_retirement_or_deletion(env):
    inputs,out,r=env
    r['challengers']*=2
    before=encode(r); (inputs/'registry.json').write_bytes(before)
    with pytest.raises(ValueError,match='limit'):read_registry(inputs,'registry.json',NOW)
    assert (inputs/'registry.json').read_bytes()==before


def test_immutable_membership_retirement_and_reactivation_epoch(env):
    inputs,out,r=env
    members=adopt_registry(out,r,sha(encode(r)),None,{},NOW)
    updated=copy.deepcopy(r);updated['version']=2;updated['challengers'][0]['status']='RETIRED'
    members=adopt_registry(out,updated,sha(encode(updated)),r,members,NOW+timedelta(minutes=1))
    assert len(load_active(inputs,updated,{}))==1
    changed=copy.deepcopy(updated); changed['version']=3;changed['challengers'][0]['shadowActivatedAt']='2026-10-05T10:01:00+09:00'
    with pytest.raises(ValueError,match='immutable'):adopt_registry(out,changed,'bad',updated,members,NOW)
    removed=copy.deepcopy(updated);removed['version']=3;removed['challengers'].pop()
    with pytest.raises(ValueError,match='retain'):adopt_registry(out,removed,'bad',updated,members,NOW)
    resumed=copy.deepcopy(updated);resumed['version']=3;resumed['challengers'][0]['status']='ACTIVE'
    later=NOW+timedelta(hours=1)
    members=adopt_registry(out,resumed,sha(encode(resumed)),updated,members,later)
    assert members[r['challengers'][0]['identitySha256']]['activeSince']==later.isoformat()
    assert len(list((out/'registry-history').glob('*.json')))==3


def test_multi_capture_parses_shared_features_once_and_never_mutates_source(env,monkeypatch):
    from python.eval.intraday_challenger import service_records
    calls=[];original=service_records.features
    monkeypatch.setattr(service_records,'features',lambda x:(calls.append(1) or original(x)))
    ref,result=captures(env)
    assert len(calls)==1 and len(result)==2
    inputs,out,r=env
    runs=read_runs(out)
    assert len(runs)==2 and len({x[0]['identitySha256'] for x in runs})==2
    assert all(row['independentEligible'] for run,_,_ in runs for row in run['rows'])
    assert all(row['actual'] is None and row['actual_cutoff']==9 for run,_,_ in runs for row in run['rows'])
    assert sha(feed.source_bytes(out,ref))==ref['sha256']


def test_one_identity_failure_does_not_suppress_other_identity(env):
    inputs,out,r=env
    ref=add_source(out,snapshot(),feed.PREFIX+'2026-10-05/run.json')
    active=load_active(inputs,r,{})
    def bad(_):raise ValueError('not echoed')
    active[0]=(active[0][0],(None,active[0][1][1],bad))
    members={e['identitySha256']:{'activeSince':e['shadowActivatedAt']} for e in r['challengers']}
    result=capture_shared(out,ref,active,members,'registry',NOW,900,set())
    assert result[0]['state']=='unavailable' and result[1]['rows']>0 and len(read_runs(out))==1


def test_dedup_survives_restart_and_no_overwrite(env):
    ref,result=captures(env)
    inputs,out,r=env
    before={p:p.read_bytes() for p in (out/'predictions').glob('*.json')}
    existing={(v['identitySha256'],v['source']['sha256']) for v,_,_ in read_runs(out)}
    assert capture_shared(out,ref,load_active(inputs,r,{}),{},'unused',NOW,900,existing)==[]
    assert all(p.read_bytes()==b for p,b in before.items())
    path=next(iter(before))
    with pytest.raises(ValueError,match='Conflicting'):immutable_json(path,{'changed':True})
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='hash'):read_runs(out)


@pytest.mark.parametrize('minutes,status,independent',[(0,'prospective',True),(16,'delayed',False),(190,'delayed',False)])
def test_capture_delay_not_issue_time_prospective_confirmation(env,minutes,status,independent):
    ref,result=captures(env,NOW+timedelta(minutes=minutes))
    run=read_runs(env[1])[0][0]; row=run['rows'][0]
    assert row['captureStatus']==status and row['independentEligible']==independent
    if minutes==190:assert row['targetTiming']=='retrospective'
    assert row['lead_minutes']>0


def test_activation_and_research_dates_exclude_independent_without_discarding_context(env):
    e=env[2]['challengers'][0];row=list(features(snapshot()))[0]
    assert 'issue_precedes_active_membership' in eligibility(row,e,NOW.isoformat(),NOW,1,900)['independentExclusions']
    e['researchDateRanges'].append(['2026-10-05','2026-10-05'])
    assert 'research_used_date' in eligibility(row,e,e['shadowActivatedAt'],NOW,1,900)['independentExclusions']


def test_future_issue_path_and_source_hash_rejected(env):
    inputs,out,r=env
    with pytest.raises(ValueError,match='Future'):captures(env,source=snapshot(issue_hour=11))
    ref=add_source(out,snapshot(),feed.PREFIX+'2026-10-06/run.json')
    with pytest.raises(ValueError,match='path/date'):capture_shared(out,ref,load_active(inputs,r,{}),{},'r',NOW,900,set())
    (out/ref['cache']).write_bytes(b'broken')
    with pytest.raises(ValueError,match='hash'):feed.source_bytes(out,ref)


def test_leakage_future_labels_fallback_and_cutoff(env):
    source=snapshot(cutoff=18)
    for row in source['hourlyDiagnostics'][10:]:row['actualMw']=999999
    source['hourlyDiagnostics'][8]['actualSource']='tepco_forecast_fallback'
    captures(env,source=source)
    row=read_runs(env[1])[0][0]['rows'][0]
    assert row['actual_cutoff']==9 and 8 not in row['feature_observed_hours']
    assert row['features']['latest_actual']!=999999 and row['actual'] is None


def labels(out,final=False,offset=0,include_state=True):
    source=snapshot()
    a={'date':source['date'],'series':[{'ts':r['ts'],'actualMw':r['actualMw']+offset} for r in source['hourlyDiagnostics']]}
    ar=add_source(out,a,'actual/2026-10-05.json',revision='c'*40)
    refs={'actual/2026-10-05.json':ar}
    if include_state:refs['.etl_state.json']=add_source(out,{'okDates':[source['date']] if final else []},'.etl_state.json',revision='c'*40)
    return {'sources':refs,'revision':'c'*40}


def test_immutable_actual_revisions_signed_absolute_errors_readiness_identity(env):
    captures(env);inputs,out,r=env;now=NOW+timedelta(days=1)
    first=evaluate(out,labels(out),r,now,'registry')
    b=(out/first['path']).read_bytes()
    second=evaluate(out,labels(out,True,50),r,now,'registry')
    assert first['sha256']!=second['sha256'] and (out/first['path']).read_bytes()==b
    result=json.loads((out/second['path']).read_bytes())
    assert len(result['models'])==2
    for value in result['models'].values():
        row=value['joinedRows'][0]
        assert row['actual_state']=='finalized'
        assert row['champion_absolute_error_mw']==abs(row['champion_error_mw'])
        assert row['error_delta_mw']==abs(row['challenger_error_mw'])-abs(row['champion_error_mw'])
        assert row['actual_source_revision']=='c'*40
        assert value['counts']['finalizedDates']==1 and not value['sampleReadiness'] and not value['promotionReady']
    assert evaluate(out,labels(out,True,50),r,now,'registry')==second


def test_missing_state_does_not_infer_finalization_and_future_actual_unavailable(env):
    captures(env);inputs,out,r=env
    result=evaluate(out,labels(out,True,include_state=False),r,NOW,'registry')
    data=json.loads((out/result['path']).read_bytes())
    assert all(row['actual_state']=='unavailable' for m in data['models'].values() for row in m['joinedRows'])
    result=evaluate(out,labels(out,True,include_state=False),r,NOW+timedelta(days=1),'registry')
    data=json.loads((out/result['path']).read_bytes())
    assert all(m['counts']['finalizedPairs']==0 for m in data['models'].values())
    assert all(row['actual_state']=='provisional' for m in data['models'].values() for row in m['joinedRows'])


def fake_feed(out, monkeypatch):
    sources={feed.PREFIX+'2026-10-05/run.json':encode(snapshot()), 'actual/2026-10-05.json':encode({'date':'2026-10-05','series':[]}),
             '.etl_state.json':encode({'okDates':[]}), '.env':b'secret','actual/../../.env':b'secret'}
    calls=[]
    def git(directory,*args):
        assert Path(directory).is_relative_to(out)
        calls.append(args)
        if args[0]=='init':
            Path(directory).mkdir(parents=True,exist_ok=True)
            return b''
        if args[0]=='fetch':return b''
        if args[0]=='rev-parse':return b'a'*40
        if args[0]=='ls-tree':return '\n'.join('100644 blob '+sha(b)[:40]+'\t'+p for p,b in sources.items()).encode()
        return sources[args[1].split(':',1)[1]]
    monkeypatch.setattr(feed,'git',git)
    return sources,calls


def test_feed_unchanged_revision_and_blob_reuse_allowlist(env,monkeypatch):
    inputs,out,r=env;sources,calls=fake_feed(out,monkeypatch)
    manifest,changed=feed.sync('https://github.com/example/repo',out,'2026-10-04')
    assert changed and len(manifest['sources'])==3
    count=len(calls)
    again,changed=feed.sync('https://github.com/example/repo',out,'2026-10-04',manifest)
    assert not changed and again==manifest and len(calls)-count==2
    assert all('.env' not in args[-1] for args in calls)
    original=feed.git
    monkeypatch.setattr(feed,'git',lambda d,*args: b'd'*40 if args[0]=='rev-parse' else original(d,*args))
    count=sum(c[0]=='show' for c in calls)
    again,changed=feed.sync('https://github.com/example/repo',out,'2026-10-04',manifest)
    assert changed and sum(c[0]=='show' for c in calls)==count
    sources['actual/2026-10-05.json']=encode({'date':'2026-10-05','series':[],'revision':2})
    monkeypatch.setattr(feed,'git',lambda d,*args: b'e'*40 if args[0]=='rev-parse' else original(d,*args))
    third,_=feed.sync('https://github.com/example/repo',out,'2026-10-04',again)
    assert third['sources']['actual/2026-10-05.json']['sha256']!=again['sources']['actual/2026-10-05.json']['sha256']


def test_worker_no_change_restart_dedup_and_network_recovery(env,monkeypatch,capsys):
    inputs,out,r=env;fake_feed(out,monkeypatch)
    w=service.Worker(inputs,'config.json',out);w.cycle()
    run_count=len(read_runs(out));last=w.status['lastEvaluation']
    w.cycle()
    assert len(read_runs(out))==run_count and w.status['lastEvaluation']==last
    restarted=service.Worker(inputs,'config.json',out);restarted.cycle()
    assert len(read_runs(out))==run_count and restarted.memberships==w.memberships
    original=service.sync
    def bad(*_):raise OSError('SECRET SHOULD NEVER BE LOGGED')
    monkeypatch.setattr(service,'sync',bad);restarted.cycle()
    assert restarted.status['healthState']=='DEGRADED' and service.health(out,NOW)['healthy']
    monkeypatch.setattr(service,'sync',original);restarted.cycle()
    assert restarted.status['healthState']=='HEALTHY'
    assert 'SECRET SHOULD' not in capsys.readouterr().out


def test_process_lock_excludes_second_worker_and_recovers(env):
    out=env[1]
    with WorkerLock(out):
        with pytest.raises(RuntimeError,match='Another worker'):
            with WorkerLock(out):pass
    with WorkerLock(out):pass


def test_health_no_fresh_source_is_not_failure_stale_fatal_inaccessible_are(env):
    out=env[1]
    assert not service.health(out,NOW)['healthy']
    atomic_json(out/'status.json',{'healthState':'HEALTHY','lastLoopAt':NOW.isoformat(),'healthMaxLoopAgeSeconds':2100,
                                 'lastSnapshotDetected':None})
    assert service.health(out,NOW)['healthy']
    assert not service.health(out,NOW+timedelta(seconds=2101))['healthy']
    atomic_json(out/'status.json',{'healthState':'FATAL','lastLoopAt':NOW.isoformat(),'healthMaxLoopAgeSeconds':2100})
    assert not service.health(out,NOW)['healthy']


def test_input_output_traversal_and_secret_roots_blocked(env):
    inputs,out,r=env
    for relative in ('../.env','/etc/passwd','model0/../../.env','.env','.codex/auth.json'):
        with pytest.raises((ValueError,FileNotFoundError)):input_path(inputs,relative)
    with pytest.raises(ValueError):storage.workspace(inputs/'writes')
    with pytest.raises(ValueError):storage.workspace(out/'../../../../web/public')
    with pytest.raises(ValueError):feed.sync('https://key@github.com/example/repo',out,'2026-10-04')
    with pytest.raises(ValueError):service.config(out,'config.json',out)


def test_docker_compose_production_lane_unchanged_and_shadow_isolation():
    import yaml
    root=Path(__file__).parents[1]
    current=yaml.safe_load((root/'docker-compose.yml').read_bytes())
    old=yaml.safe_load(subprocess.check_output(['git','show','HEAD:docker-compose.yml'],cwd=root))
    assert current['services']['etl']==old['services']['etl']
    shadow=current['services']['intraday-shadow']
    assert shadow['read_only'] and shadow['restart']=='unless-stopped'
    assert 'env_file' not in shadow and set(shadow['environment'])=={'TZ'}
    assert len(shadow['volumes'])==2 and shadow['volumes'][0]['read_only']
    dockerfile=(root/'docker/shadow.Dockerfile').read_text()
    assert 'USER 10001:10001' in dockerfile and 'COPY . ' not in dockerfile and 'python/etl' not in dockerfile
    ignore=(root/'docker/shadow.Dockerfile.dockerignore').read_text().splitlines()
    assert ignore[0]=='**' and not any('.env' in p or 'notes' in p or 'data' in p for p in ignore[1:])


def test_same_issue_source_revision_not_double_counted(env):
    inputs,out,r=env
    ref=add_source(out,snapshot(),feed.PREFIX+'2026-10-05/run.json')
    members={e['identitySha256']:{'activeSince':e['shadowActivatedAt']} for e in r['challengers']}
    seen=set();existing=set();active=load_active(inputs,r,{})
    capture_shared(out,ref,active,members,'r',NOW,900,existing,seen)
    changed=snapshot();changed['correction']['baseAdjustmentMw']+=10
    ref2=add_source(out,changed,feed.PREFIX+'2026-10-05/run.json')
    result=capture_shared(out,ref2,active,members,'r',NOW,900,existing,seen)
    assert all(v['errorType']=='DuplicateIssueVintage' for v in result)
    assert len(read_runs(out))==2


def test_live_policy_cannot_change_under_same_evidence_workspace(env,monkeypatch):
    inputs,out,r=env;fake_feed(out,monkeypatch)
    worker=service.Worker(inputs,'config.json',out);worker.cycle()
    config=json.loads((inputs/'config.json').read_bytes());config['maxIndependentCaptureDelaySeconds']=1200
    (inputs/'config.json').write_bytes(encode(config))
    with pytest.raises(ValueError,match='policy'):service.Worker(inputs,'config.json',out)


def test_registry_draft_2020_schema(env):
    jsonschema=pytest.importorskip('jsonschema',reason='optional local dev/test validator, not production dependency')
    schema=json.loads((Path(__file__).parents[1]/'docker/shadow-registry.schema.json').read_bytes())
    jsonschema.Draft202012Validator.check_schema(schema)
    validator=jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())
    validator.validate(env[2])
    broken=copy.deepcopy(env[2]);broken['challengers'][0]['status']='AUTOPROMOTE'
    with pytest.raises(jsonschema.ValidationError):validator.validate(broken)


def test_worker_long_wait_happens_inside_process_and_finite_shutdown(env,monkeypatch):
    fake_feed(env[1],monkeypatch)
    class Stop:
        def __init__(self):self.waits=[]
        def is_set(self):return False
        def wait(self,n):self.waits.append(n)
    stop=Stop()
    w=service.Worker(env[0],'config.json',env[1],stop)
    assert w.run(2)==2 and stop.waits==[600]
    assert w.status['healthState']=='STOPPED'


def test_l5_deployment_bootstrap_validates_gates_and_preserves_sources(env):
    from scripts.prepare_intraday_shadow import prepare
    inputs,out,r=env
    source=out/'source-model';source.mkdir(parents=True)
    for p in (inputs/'model0').glob('*'):(source/p.name).write_bytes(p.read_bytes())
    key=r['challengers'][0]['identitySha256']; identity=json.loads((source/'identity.json').read_bytes())
    q={'gates':{'L2':{'recorded_gate':True}},'productionPromotion':False,
       'datasetSha256':identity['inputManifestSha256']}
    qp=out/'qualification.json';immutable_json(qp,q)
    destination=out/'deployment'
    result=prepare(source,key,qp,sha(encode(q)),destination,[['2026-09-01','2026-10-03']],'L5','1')
    assert result['identitySha256']==key
    assert (destination/'models'/key/'identity.json').read_bytes()==(source/'identity.json').read_bytes()
    with pytest.raises(ValueError,match='already'):prepare(source,key,qp,sha(encode(q)),destination,
                                                          [['2026-09-01','2026-10-03']],'L5','1')
    q['gates']['L2']['recorded_gate']=False
    qp2=out/'failed.json';immutable_json(qp2,q)
    with pytest.raises(ValueError,match='qualification'):prepare(source,key,qp2,sha(encode(q)),out/'bad',
                                                               [['2026-09-01','2026-10-03']],'L5','1')


def test_qualification_failure_is_inconclusive_not_shadow_admission(env):
    inputs,out,r=env
    q={'gates':{'L2':{'recorded_gate':False}},'productionPromotion':False,
       'datasetSha256':r['challengers'][0]['trainingDatasetIdentity']}
    p=inputs/r['challengers'][0]['historicalQualification']['path'];p.write_bytes(encode(q))
    r['challengers'][0]['historicalQualification']['sha256']=sha(encode(q))
    (inputs/'registry.json').write_bytes(encode(r))
    with pytest.raises(ValueError,match='gates'):read_registry(inputs,'registry.json',NOW)


def test_inference_crossing_target_boundary_is_not_prospective_capture(env):
    inputs,out,r=env;source=snapshot()
    source['generatedAt']='2026-10-05T10:59:59+09:00'
    ref=add_source(out,source,feed.PREFIX+'2026-10-05/run.json')
    start=timestamp(source['generatedAt']);end=start+timedelta(seconds=2)
    members={e['identitySha256']:{'activeSince':e['shadowActivatedAt']} for e in r['challengers']}
    capture_shared(out,ref,load_active(inputs,r,{}),members,'r',start,900,set(),clock=lambda:end)
    row=read_runs(out)[0][0]['rows'][0]
    assert row['hour']==11 and row['captureStatus']=='retrospective' and not row['independentEligible']
    assert row['capture_lead_minutes']<0 and row['recorded_at']==end.isoformat()


def test_new_third_identity_keeps_old_membership_and_evidence(env):
    captures(env);inputs,out,r=env
    old={p:p.read_bytes() for p in (out/'predictions').glob('*.json')}
    memberships=adopt_registry(out,r,sha(encode(r)),None,{},NOW)
    rr=records('2026-09-21')
    for row in rr:row['actual']+=160
    model=inputs/'model2';identity=save(train(rr,'L2'),model,'L2',rr,sha(b'third-dataset'))
    entry=copy.deepcopy(r['challengers'][0]);entry.update(modelName='L7',artifactPath='model2',
        identitySha256=sha((model/'identity.json').read_bytes()),combinedFingerprint=fingerprint(identity),
        trainingDatasetIdentity=identity['inputManifestSha256'],shadowActivatedAt=(NOW+timedelta(minutes=1)).isoformat())
    q={'gates':{'L2':{'fixture_gate':True}},'productionPromotion':False,'datasetSha256':identity['inputManifestSha256']}
    (inputs/'q2.json').write_bytes(encode(q));entry['historicalQualification'].update(path='q2.json',sha256=sha(encode(q)))
    updated=copy.deepcopy(r);updated['version']=2;updated['challengers'].append(entry)
    (inputs/'registry.json').write_bytes(encode(updated));read_registry(inputs,'registry.json',NOW+timedelta(minutes=1))
    after=adopt_registry(out,updated,sha(encode(updated)),r,memberships,NOW+timedelta(minutes=1))
    assert all(after[k]==v for k,v in memberships.items())
    existing={(run['identitySha256'],run['source']['sha256']) for run,_,_ in read_runs(out)}
    source=add_source(out,snapshot(),feed.PREFIX+'2026-10-05/run.json')
    result=capture_shared(out,source,load_active(inputs,updated,{}),after,'newregistry',NOW+timedelta(minutes=2),900,existing)
    assert len(result)==1 and result[0]['identitySha256']==entry['identitySha256'] and result[0]['independentEligible']==0
    assert all(p.read_bytes()==b for p,b in old.items()) and len(read_runs(out))==3


def test_newer_training_cutoff_is_not_worker_error_or_inference(env):
    inputs,out,r=env;active=load_active(inputs,r,{})
    newer=copy.deepcopy(active[1][0]);newer['trainingCutoff']='2026-10-05'
    def forbidden(_):raise AssertionError('Training-period prediction must not run')
    active[1]=(newer,(None,active[1][1][1],forbidden))
    source=add_source(out,snapshot(),feed.PREFIX+'2026-10-05/run.json')
    members={e['identitySha256']:{'activeSince':e['shadowActivatedAt']} for e in r['challengers']}
    result=capture_shared(out,source,active,members,'registry',NOW,900,set())
    assert result[0]['rows']>0 and result[1]['state']=='not_applicable' and len(read_runs(out))==1
