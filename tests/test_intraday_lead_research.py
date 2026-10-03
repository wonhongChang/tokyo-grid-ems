import copy
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from python.eval.intraday_challenger import feed, storage
from python.eval.intraday_challenger.evidence import encode, sha
from python.eval.intraday_challenger.lead_evaluation import LEAD_BUCKETS, lead_report, revisions
from python.eval.intraday_challenger.lead_model import fit, frame, load, predict, save, scale
from python.eval.intraday_challenger.walk_forward import partitions, run
from python.eval.intraday_challenger.shadow import aggregate, capture
from tests.test_intraday_challenger import records, shadow_setup, snapshot


def training():
    return [r for i in range(14) for r in records((date(2026,9,1)+timedelta(days=i)).isoformat())]


def test_lead_features_and_normalized_target():
    rr=records()[:2]
    rr[0]['lead_minutes']=30; rr[1]['lead_minutes']=180
    f=frame(rr)
    assert scale(rr)==pytest.approx([np.sqrt(1.5),2])
    assert f.iloc[0]['lead_log']==pytest.approx(np.log(1.5))
    assert f.iloc[1]['raw_residual_mean_lead_scaled']==rr[1]['features']['raw_residual_mean']/2
    rr[0]['lead_minutes']=0
    with pytest.raises(ValueError,match='positive'):frame(rr)


def test_no_labels_or_extra_weather_enter_features():
    rr=records(); before=frame(rr).copy()
    for r in rr:r.update(actual=999999,actual_sha='future',expected_label='bad',tepcoForecastMw=999999)
    assert frame(rr).equals(before)
    rr[0]['features']['observation_age_minutes']=None
    assert np.isnan(frame(rr).iloc[0]['age_to_lead'])


@pytest.mark.parametrize('name',['L4','L5'])
def test_serialization_and_deterministic_inference(tmp_path,name):
    rr=training(); m=fit(rr,name); output=tmp_path/name
    save(m,output,rr,'data','revision')
    h=sha((output/'identity.json').read_bytes()); loaded,identity=load(output,h)
    assert predict(m,rr)==predict(loaded,rr)==predict(fit(rr,name),rr)
    assert all(0<=w<=1 for w in predict(m,rr,True)[1])
    assert identity['productionPromotion'] is False
    if name=='L5':assert all(x['trainingEnd']<x['testStart'] for x in identity['oof'])
    with pytest.raises(ValueError,match='identity'):load(output,'wrong')
    (output/'error.txt').write_bytes(b'broken')
    with pytest.raises(ValueError,match='artifact'):load(output,h)


def test_training_requires_finalized_labels_and_oof_dates():
    rr=training(); rr[0]['actual_state']='provisional'
    with pytest.raises(ValueError,match='finalized'):fit(rr,'L4')
    with pytest.raises(ValueError,match='eight'):fit(records(),'L5')


def test_outer_split_integrity_and_population():
    rr=training(); folds=[{'train':['2026-09-01','2026-09-08'],'test':['2026-09-09','2026-09-14']}]
    tr,te=partitions(rr,folds)[0]
    assert max(r['date'] for r in tr)<min(r['date'] for r in te)
    with pytest.raises(ValueError,match='Duplicate'):partitions(rr,folds+folds)
    folds[0]['test'][0]='2026-09-08'
    with pytest.raises(ValueError,match='Overlapping'):partitions(rr,folds)


def test_fixed_buckets_exhaustive_and_boundary_assignment():
    rr=records()[:7]
    for r,lead in zip(rr,[1,30,60,120,180,360,361]):r['lead_minutes']=lead
    report=lead_report(rr,[r['champion'] for r in rr])
    assert report['bucketsMinutes']==LEAD_BUCKETS
    counts=[g['overall']['metrics']['champion']['n'] for g in report['groups'].values()]
    assert counts==[2,1,1,1,1,1] and sum(counts)==len(rr)
    with pytest.raises(ValueError):lead_report(rr,[])


def test_revisions_are_cross_issue_not_cross_target_and_do_not_bridge_gaps():
    a=records()[0]; b=copy.deepcopy(a); b.update(issued_at=a['date']+'T11:00:00+09:00',lead_minutes=10,champion=a['champion']+10)
    r=revisions([a,b],[a['champion'],b['champion']+20])
    assert r['n']==1 and r['champion']['mean']==10 and r['challenger']['mean']==30
    b['issued_at']=a['date']+'T14:00:00+09:00'
    assert revisions([a,b],[1,2])['n']==0


def test_join_rows_counts_and_immutable_revision(tmp_path,monkeypatch):
    source,model,h,out=shadow_setup(tmp_path,monkeypatch)
    c=capture(source,sha(source.read_bytes()),model,h,out)
    actual=tmp_path/'actual';actual.mkdir(); day='2026-10-05'
    label={'date':day,'series':[{'ts':r['ts'],'actualMw':r['actualMw']} for r in snapshot()['hourlyDiagnostics']]}
    path=actual/(day+'.json'); path.write_bytes(encode(label))
    state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[day]}))
    first=aggregate(out,actual,state); data=json.loads(Path(first['path']).read_bytes())
    m=next(iter(data['models'].values())); row=m['joinedRows'][0]
    assert row['actual_source_sha']==sha(path.read_bytes())
    assert row['source_pointer']=='/hourlyDiagnostics/11'
    assert row['error_delta_mw']==abs(row['challenger_error_mw'])-abs(row['champion_error_mw'])
    assert m['counts']['finalizedDates']==1 and m['counts']['businessDates']==1
    assert m['promotionReady'] is False and m['sampleReadiness'] is False
    old=Path(first['path']).read_bytes(); label['series'][11]['actualMw']+=50;path.write_bytes(encode(label))
    second=aggregate(out,actual,state)
    assert first['path']!=second['path'] and Path(first['path']).read_bytes()==old
    assert capture(source,sha(source.read_bytes()),model,h,out)==c


def test_feed_allowlist_and_no_production_writes(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'REPO_ROOT',tmp_path)
    root=tmp_path/'data/intraday_challenger/feed-trial'
    prefix='reports/internal/operational-calibration/snapshots/'
    inputs={prefix+'2026-10-05/run.json':encode(snapshot()),
            'actual/2026-10-05.json':encode({'date':'2026-10-05','series':[]}),
            '.etl_state.json':encode({'okDates':[]}), '.env':b'secret',
            'actual/../../.env':b'secret',prefix+'../../.env':b'secret'}
    opened=[]
    def git(directory,*args):
        assert Path(directory).is_relative_to(root)
        if args[0] in ('init','fetch'):return b''
        if args[0]=='rev-parse':return b'frozen-revision\n'
        if args[0]=='ls-tree':return '\n'.join(inputs).encode()
        path=args[1].split(':',1)[1];opened.append(path);return inputs[path]
    monkeypatch.setattr(feed,'_git',git)
    sources,actual,state,revision=feed.sync('https://github.com/example/repo',root,'2026-10-05')
    assert len(sources)==1 and revision=='frozen-revision' and all('..' not in p and p!='.env' for p in opened)
    assert not (tmp_path/'web/public').exists()
    assert len(list((root/'feed/revisions').glob('*.json')))==1
    feed.sync('https://github.com/example/repo',root,'2026-10-05')
    assert len(list((root/'feed/revisions').glob('*.json')))==1
    with pytest.raises(ValueError):feed.sync('https://token@github.com/example/repo',root,'2026-10-05')
    with pytest.raises(ValueError):feed.sync('https://github.com/example/repo',tmp_path/'web/public','2026-10-05')


def test_feed_revisions_missing_actual_and_no_unchanged_reaggregation(tmp_path,monkeypatch):
    source,model,h,out=shadow_setup(tmp_path,monkeypatch)
    root=out/'feed/actual';root.mkdir(parents=True)
    state=out/'feed/state.json';state.write_bytes(encode({'okDates':[]}))
    sleeps=[];calls=[]
    monkeypatch.setattr(feed,'sync',lambda *args:([(source,sha(source.read_bytes()))],root,state,'fixed'))
    monkeypatch.setattr(feed.time,'sleep',lambda n:sleeps.append(n))
    original=feed.aggregate
    def tracked(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(feed,'aggregate',tracked)
    feed.watch('https://github.com/example/repo',model,h,out,'2026-10-05',300,2)
    assert sleeps==[300] and len(calls)==1


def test_shadow_learned_model_identity_and_isolated_population(tmp_path,monkeypatch):
    source,old,h,out=shadow_setup(tmp_path,monkeypatch)
    capture(source,sha(source.read_bytes()),old,h,out)
    rr=training();new=tmp_path/'lead-model';meta=save(fit(rr,'L5'),new,rr,'dataset','revision')
    nh=sha((new/'identity.json').read_bytes())
    result=capture(source,sha(source.read_bytes()),new,nh,out)
    run=json.loads(Path(result['path']).read_bytes())
    assert run['modelIdentity']['candidate']=='L5'
    assert run['rows'][0]['model_identity']==sha(encode(meta['artifacts']))
    assert run['rows'][0]['feature_identity']=='intraday-lead-research/1.0.0'
    actual=tmp_path/'actual';actual.mkdir();state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[]}))
    evaluated=aggregate(out,actual,state)
    assert evaluated['models']==2


def test_capture_rejects_future_issue_and_aggregate_corrupt_identity(tmp_path,monkeypatch):
    source,model,h,out=shadow_setup(tmp_path,monkeypatch)
    future=snapshot(issue_hour=11);source.write_bytes(encode(future))
    with pytest.raises(ValueError,match='future'):capture(source,sha(source.read_bytes()),model,h,out)
    source.write_bytes(encode(snapshot()));r=capture(source,sha(source.read_bytes()),model,h,out)
    path=Path(r['path']);value=json.loads(path.read_bytes());value['modelIdentity']['trainingEnd']='1999-01-01'
    path.write_bytes(encode(value));actual=tmp_path/'actual';actual.mkdir();state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[]}))
    with pytest.raises(ValueError,match='identity hash'):aggregate(out,actual,state)


def test_research_runner_preregistration_population_and_isolation(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'REPO_ROOT',tmp_path)
    data=tmp_path/'dataset.jsonl';data.write_bytes(b''.join(encode(r) for r in training()))
    registration={'contract':'intraday-lead-research/1.0.0','frozenDatasetSha256':sha(data.read_bytes()),
        'leadBucketsMinutes':[list(x) for x in LEAD_BUCKETS],
        'folds':[{'train':['2026-09-01','2026-09-10'],'test':['2026-09-11','2026-09-14']}],
        'limitations':['historical already seen'],
        'acceptance':{'all_mae_ratio_max':.97,'closest_mae_ratio_max':1.0,
            'all_rmse_ratio_max':1.02,'closest_rmse_ratio_max':1.02,'each_fold_closest_mae_ratio_max':1.10}}
    path=tmp_path/'registration.json';path.write_bytes(encode(registration));h=sha(path.read_bytes())
    out=tmp_path/'data/intraday_challenger/research';source=data.read_bytes()
    with pytest.raises(ValueError,match='Preregistration'):run(data,path,'bad',out,'code')
    result=run(data,path,h,out,'code')
    assert data.read_bytes()==source and not (tmp_path/'web/public').exists()
    assert result['productionPromotion'] is False
    pop=[v['all_positive:finalized']['overall']['champion'] for v in result['results'].values()]
    assert pop[0]==pop[1]==pop[2]
    with pytest.raises(ValueError,match='already exists'):run(data,path,h,out,'code')
