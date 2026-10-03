import copy
import json
from pathlib import Path

import numpy as np
import pytest

from python.eval.intraday_challenger import CONTRACT
from python.eval.intraday_challenger.evidence import FEATURES, closest, dataset, encode, features, frame, implementation_sha, read_sealed, sha
from python.eval.intraday_challenger.evaluation import comparison, metrics, report, transitions
from python.eval.intraday_challenger.experiment import acceptance, gates, prepare, run, split
from python.eval.intraday_challenger.model import CANDIDATES, load, predict, save, train
from python.eval.intraday_challenger.shadow import aggregate, capture, watch
from python.eval.intraday_challenger import storage


def snapshot(day='2026-10-05', issue_hour=10, cutoff=9):
    return {'date': day, 'generatedAt': f'{day}T{issue_hour:02d}:30:00+09:00', 'model': 'recorded',
            'correction': {'lastObservedHour': cutoff, 'baseAdjustmentMw': 30},
            'hourlyDiagnostics': [{'hour': h, 'ts': f'{day}T{h:02d}:00:00+09:00',
                'actualMw': 20000 + 100 * h, 'actualSource': 'observed',
                'forecastMwByStage': {'raw_lgbm': 20200 + 150 * h},
                'preCalibrationForecastMw': 20250 + 150 * h, 'postCalibrationForecastMw': 20100 + 150 * h,
                'lag24DeltaMw': 100, 'recentSameBusinessTypeDeltaMw': 110} for h in range(24)]}


def records(day='2026-10-05'):
    rr = list(features(snapshot(day)))
    for r in rr:
        r.update(actual=r['raw'] + 70, actual_state='finalized', source_sha='abc')
    return rr


def sealed_fixture(tmp_path):
    def store(value):
        b = encode(value); h = sha(b); p = tmp_path / 'sources' / (h + '.json')
        p.parent.mkdir(exist_ok=True); p.write_bytes(b)
        return {'path': 'sources/' + p.name, 'sha256': h, 'bytes': len(b)}
    s = snapshot()
    ref = dict(store(s), date=s['date'], issuedAt=s['generatedAt'])
    a = {'date': s['date'], 'series': [{'ts': r['ts'], 'actualMw': r['actualMw']} for r in s['hourlyDiagnostics']]}
    actual = dict(store(a), state='finalized', date=s['date'])
    m = {'asOf': '2026-10-05T20:00:00+09:00', 'runs': [ref], 'actuals': {s['date']: actual}}
    b = encode(m); (tmp_path / 'manifest.json').write_bytes(b)
    return m, sha(b)


def test_future_actual_values_and_weather_never_enter_features():
    s = snapshot()
    before = list(features(s))
    for r in s['hourlyDiagnostics']:
        if r['hour'] > 9:
            r['actualMw'] = 999999
        r.update(humidityPct=99999, tempC=-99999, tepcoForecastMw=999999)
    assert list(features(s)) == before
    assert set(before[0]['features']) == set(FEATURES)


def test_completed_hour_and_recorded_cutoff_both_required():
    s = snapshot(cutoff=15)
    r = list(features(s))[0]
    assert r['actual_cutoff'] == 9
    assert r['feature_observed_hours'] == list(range(10))
    s['correction']['lastObservedHour'] = 6
    assert list(features(s))[0]['actual_cutoff'] == 6


def test_observed_fallback_and_gaps_not_treated_as_observations():
    s = snapshot()
    s['hourlyDiagnostics'][8]['actualSource'] = 'tepco_forecast_fallback'
    r = list(features(s))[0]
    assert 8 not in r['feature_observed_hours']
    assert r['features']['actual_delta_1'] is None
    assert r['features']['raw_residual_2'] is None


def test_no_cutoff_no_observation_context():
    s = snapshot(); s['correction']['lastObservedHour'] = None
    r = list(features(s))[0]
    assert r['actual_cutoff'] is None
    assert r['features']['latest_actual'] is None
    assert r['features']['observed_count'] == 0


@pytest.mark.parametrize('day,expected,returned', [('2026-10-03',1,0),('2026-10-04',1,0),('2026-10-05',0,1),('2026-09-22',1,0)])
def test_calendar_context(day, expected, returned):
    f = records(day)[0]['features']
    assert f['non_business'] == expected
    assert f['business_return'] == returned


@pytest.mark.parametrize('hour', [2, 8, 14, 20])
def test_all_time_bands_and_positive_leads(hour):
    s = snapshot(issue_hour=hour, cutoff=hour - 1)
    rr = list(features(s))
    assert min(x['hour'] for x in rr) == hour + 1
    assert all(x['lead_minutes'] > 0 for x in rr)
    assert len({x['lead_minutes'] for x in rr}) == len(rr)


def test_timestamp_and_duplicate_hour_rejected():
    s = snapshot(); s['hourlyDiagnostics'].append(copy.deepcopy(s['hourlyDiagnostics'][0]))
    with pytest.raises(ValueError, match='Duplicate'): list(features(s))
    s = snapshot(); s['hourlyDiagnostics'][0]['ts'] = '2026-10-04T00:00:00+09:00'
    with pytest.raises(ValueError, match='mismatch'): list(features(s))
    s = snapshot(); s['generatedAt'] = '2026-10-05T10:30:00'
    with pytest.raises(ValueError, match='Timezone'): list(features(s))


def test_dataset_labels_are_separate_and_future_labels_null(tmp_path):
    m, h = sealed_fixture(tmp_path)
    rr = dataset(tmp_path, h)
    assert rr[-1]['actual'] is None
    assert rr[0]['actual'] == 21100
    assert 'actual' not in rr[0]['features']
    assert rr[0]['actual_sha'] == m['actuals']['2026-10-05']['sha256']
    assert rr[0]['model_artifact'] is None and rr[0]['serving_policy'] is None
    assert rr[0]['source_pointer'].startswith('/hourlyDiagnostics/')
    assert encode(rr) == encode(dataset(tmp_path, h))


def test_dataset_source_manifest_and_vintage_hashes(tmp_path):
    m, h = sealed_fixture(tmp_path)
    with pytest.raises(ValueError, match='manifest hash'): dataset(tmp_path, 'bad')
    path = tmp_path / m['runs'][0]['path']; path.write_bytes(b'{}')
    with pytest.raises(ValueError, match='Source hash'): dataset(tmp_path, h)


def test_input_traversal_rejected(tmp_path):
    with pytest.raises(ValueError, match='outside'): read_sealed(tmp_path, {'path': '../.env', 'sha256': 'x'})


def test_source_identity_survives_git_line_ending_conversion_only(tmp_path):
    lf=tmp_path/'lf.py';crlf=tmp_path/'crlf.py'
    lf.write_bytes(b'x = 1\ny = 2\n');crlf.write_bytes(b'x = 1\r\ny = 2\r\n')
    assert implementation_sha(lf)==implementation_sha(crlf)
    assert sha(lf.read_bytes())!=sha(crlf.read_bytes())
    crlf.write_bytes(b'x = 3\r\ny = 2\r\n')
    assert implementation_sha(lf)!=implementation_sha(crlf)


def test_snapshot_after_asof_and_duplicate_vintage_rejected(tmp_path):
    m,h=sealed_fixture(tmp_path)
    m['asOf']='2026-10-05T09:00:00+09:00';(tmp_path/'manifest.json').write_bytes(encode(m))
    with pytest.raises(ValueError,match='after experiment'):dataset(tmp_path,sha(encode(m)))
    m['asOf']='2026-10-05T20:00:00+09:00';m['runs'].append(m['runs'][0]);(tmp_path/'manifest.json').write_bytes(encode(m))
    with pytest.raises(ValueError,match='Duplicate issue'):dataset(tmp_path,sha(encode(m)))


def test_dataset_does_not_read_environment_or_modify_sources(tmp_path,monkeypatch):
    m,h=sealed_fixture(tmp_path); (tmp_path/'.env').write_text('secret sentinel')
    before={p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    original=Path.read_bytes
    reads=[]
    def track(path):
        reads.append(path)
        if path.name=='.env': raise AssertionError('Secret access')
        return original(path)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'read_bytes',track)
        dataset(tmp_path,h)
    assert all(original(p)==b for p,b in before.items())
    assert not any(p.name=='.env' for p in reads)


def test_closest_preserves_exact_population():
    a, b = records()[0], copy.deepcopy(records()[0]); b['lead_minutes'] = 15
    c = records()[1]; c['lead_minutes'] = 121
    assert closest([a,b,c]) == [b]


def test_missing_features_use_native_missingness_not_final_actual():
    rr = records(); rr[0]['features'].pop('latest_actual')
    assert np.isnan(frame(rr).iloc[0]['latest_actual'])


@pytest.mark.parametrize('name', ['L1','L2','L3'])
def test_train_serialization_determinism_and_contract(tmp_path, name):
    rr = records() + records('2026-10-06') + records('2026-10-07') + records('2026-10-08')
    booster = train(rr, name)
    directory = tmp_path / name
    identity = save(booster, directory, name, rr, 'input')
    ih = sha((directory/'identity.json').read_bytes())
    loaded, meta = load(directory, ih)
    assert identity == meta
    assert predict(booster, rr, CANDIDATES[name]) == predict(loaded, rr, CANDIDATES[name])
    assert predict(booster, rr, CANDIDATES[name]) == predict(train(rr,name), rr, CANDIDATES[name])
    with pytest.raises(ValueError, match='identity hash'): load(directory, 'wrong')
    (directory/'model.txt').write_bytes(b'broken')
    with pytest.raises(ValueError, match='artifact hash'): load(directory, ih)


def test_provisional_or_missing_labels_cannot_train():
    rr = records(); rr[0]['actual_state'] = 'provisional'
    with pytest.raises(ValueError, match='finalized'): train(rr, 'L1')
    rr = records(); rr[0]['actual'] = None
    with pytest.raises(ValueError, match='finalized'): train(rr, 'L1')


def test_metrics_arithmetic_and_population_validation():
    m = metrics([100,200],[110,180])
    assert m['mae'] == 15 and m['bias'] == -5 and m['wape_pct'] == 10
    assert m['rmse'] == pytest.approx(np.sqrt(250))
    assert metrics([0],[1])['wape_pct'] is None
    with pytest.raises(ValueError): metrics([1,2],[1])
    with pytest.raises(ValueError): metrics([1],[np.nan])


def test_regression_distribution_and_date_counts():
    rr = records()[:3]
    for r in rr: r.update(actual=100,champion=110)
    x = comparison(rr,[100,130,110])
    assert (x['improved'],x['worsened'],x['unchanged']) == (1,1,1)
    assert x['regression_p95'] == 20 and x['max_improvement'] == 10
    assert x['date_losses'] == 1
    with pytest.raises(ValueError): comparison(rr,[100])


def test_report_keeps_provisional_and_missing_separate():
    rr = records()[:3]; rr[1]['actual_state']='provisional'; rr[2]['actual']=None
    r = report(rr,[x['raw'] for x in rr])
    assert r['all_positive:finalized']['overall']['champion']['n'] == 1
    assert r['all_positive:provisional']['overall']['champion']['n'] == 1


def test_transitions_do_not_bridge_gaps_or_run_vintages():
    rr = records()[:3]; rr[1]['issued_at'] = '2026-10-05T11:00:00+09:00'
    assert transitions(rr,[r['raw'] for r in rr])['n'] == 0
    assert transitions(records(),[r['raw'] for r in records()])['n'] == len(records())-1


def test_chronological_partitions_and_missingness():
    periods={'train':['2026-10-05','2026-10-05'],'validation':['2026-10-06','2026-10-06'],'holdout':['2026-10-07','2026-10-07']}
    rr=records()+records('2026-10-06')+records('2026-10-07')
    groups=split(rr,periods)
    assert {r['date'] for r in groups['train']} == {'2026-10-05'}
    periods['holdout'][0]='2026-10-06'
    with pytest.raises(ValueError,match='overlap'): split(rr,periods)
    periods['holdout']=['2026-10-09','2026-10-10']
    with pytest.raises(ValueError,match='Empty'): split(rr,periods)


@pytest.mark.parametrize('path',['web/public/forecast','data/models','notes/private','data/intraday_challenger/../models'])
def test_output_isolation(tmp_path,monkeypatch,path):
    monkeypatch.setattr(storage,'REPO_ROOT',tmp_path)
    with pytest.raises(ValueError,match='Output'): storage.workspace(tmp_path/path)
    assert storage.workspace(tmp_path/'data/intraday_challenger/trial') == tmp_path/'data/intraday_challenger/trial'


def shadow_setup(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'REPO_ROOT',tmp_path)
    import python.eval.intraday_challenger.shadow as module
    from python.eval.intraday_challenger.evidence import timestamp
    monkeypatch.setattr(module,'_now',lambda:timestamp('2026-10-05T10:31:00+09:00'))
    model=tmp_path/'model'; rr=records('2026-10-01')*4
    save(train(rr,'L2'),model,'L2',rr,'frozen')
    ih=sha((model/'identity.json').read_bytes())
    s=snapshot(); source=tmp_path/'snapshot.json'; source.write_bytes(encode(s))
    out=tmp_path/'data/intraday_challenger/shadow'
    return source,model,ih,out


def test_redirected_workspace_root_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'REPO_ROOT',tmp_path)
    nominal=tmp_path/'data/intraday_challenger';original=Path.resolve
    def redirected(path,*args,**kwargs):
        if path==nominal:return tmp_path/'web/public'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'resolve',redirected)
    with pytest.raises(ValueError,match='redirected'): storage.workspace(nominal/'trial')


def test_shadow_immutable_idempotent_and_production_untouched(tmp_path,monkeypatch):
    source,model,ih,out=shadow_setup(tmp_path,monkeypatch)
    production=tmp_path/'web/public/forecast/2026-10-05.json'; production.parent.mkdir(parents=True);production.write_bytes(b'unchanged')
    h=sha(source.read_bytes()); a=capture(source,h,model,ih,out); b=capture(source,h,model,ih,out)
    assert a==b and production.read_bytes()==b'unchanged'
    rows=json.loads(Path(a['path']).read_bytes())['rows']
    assert all(r['actual'] is None for r in rows)
    assert all(r['model_identity'] and r['feature_identity']==CONTRACT for r in rows)
    with pytest.raises(ValueError): capture(source,h,model,ih,production.parent)


def test_shadow_finalization_and_revisions_not_prediction_overwrite(tmp_path,monkeypatch):
    source,model,ih,out=shadow_setup(tmp_path,monkeypatch)
    a=capture(source,sha(source.read_bytes()),model,ih,out); prediction_bytes=Path(a['path']).read_bytes()
    actual=tmp_path/'actual'; actual.mkdir(); day='2026-10-05'
    labels={'date':day,'series':[{'ts':x['ts'],'actualMw':x['actualMw']} for x in snapshot()['hourlyDiagnostics']]}
    (actual/(day+'.json')).write_bytes(encode(labels)); state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[]}))
    provisional=aggregate(out,actual,state); j=json.loads(Path(provisional['path']).read_bytes())
    assert next(iter(j['models'].values()))['finalizedRows']==0
    state.write_bytes(encode({'okDates':[day]}))
    finalized=aggregate(out,actual,state);j=json.loads(Path(finalized['path']).read_bytes())
    assert next(iter(j['models'].values()))['finalizedRows']>0
    assert next(iter(j['models'].values()))['daily'][day]
    labels['series'][11]['actualMw']+=10;(actual/(day+'.json')).write_bytes(encode(labels))
    revision=aggregate(out,actual,state)
    assert revision['path']!=finalized['path']
    assert Path(a['path']).read_bytes()==prediction_bytes
    assert aggregate(out,actual,state)==revision


def test_shadow_rejects_training_period(tmp_path,monkeypatch):
    source,model,ih,out=shadow_setup(tmp_path,monkeypatch)
    source.write_bytes(encode(snapshot('2026-10-01')))
    with pytest.raises(ValueError,match='after model training'):capture(source,sha(source.read_bytes()),model,ih,out)


def test_shadow_different_models_do_not_mix_populations(tmp_path,monkeypatch):
    source,model,ih,out=shadow_setup(tmp_path,monkeypatch)
    capture(source,sha(source.read_bytes()),model,ih,out)
    other=tmp_path/'other';rr=records('2026-10-01')*4
    save(train(rr,'L1'),other,'L1',rr,'frozen');oh=sha((other/'identity.json').read_bytes())
    capture(source,sha(source.read_bytes()),other,oh,out)
    actual=tmp_path/'actual';actual.mkdir(); state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[]}))
    assert aggregate(out,actual,state)['models']==2


def test_worker_long_sleep_and_unchanged_inputs_not_reaggregated(tmp_path,monkeypatch):
    source,model,ih,out=shadow_setup(tmp_path,monkeypatch)
    root=tmp_path/'snapshots'; target=root/'2026-10-05'/'run.json';target.parent.mkdir(parents=True);target.write_bytes(source.read_bytes())
    actual=tmp_path/'actual';actual.mkdir();state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[]}))
    import python.eval.intraday_challenger.shadow as module
    sleep=[]; calls=[]; original=module.aggregate
    monkeypatch.setattr(module.time,'sleep',lambda n:sleep.append(n))
    def tracked(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(module,'aggregate',tracked)
    watch(root,model,ih,out,actual,state,seconds=300,cycles=2)
    assert sleep==[300] and len(calls)==1


def test_retrospective_capture_not_counted_as_live_confirmation(tmp_path,monkeypatch):
    source,model,ih,out=shadow_setup(tmp_path,monkeypatch)
    from python.eval.intraday_challenger.evidence import timestamp
    import python.eval.intraday_challenger.shadow as module
    monkeypatch.setattr(module,'_now',lambda:timestamp('2026-10-06T00:00:00+09:00'))
    capture(source,sha(source.read_bytes()),model,ih,out)
    actual=tmp_path/'actual';actual.mkdir();day='2026-10-05'
    (actual/(day+'.json')).write_bytes(encode({'date':day,'series':[{'ts':x['ts'],'actualMw':x['actualMw']} for x in snapshot()['hourlyDiagnostics']]}))
    state=tmp_path/'state.json';state.write_bytes(encode({'okDates':[day]}))
    r=aggregate(out,actual,state);j=json.loads(Path(r['path']).read_bytes())
    m=next(iter(j['models'].values()))
    assert m['finalizedRows']==0
    assert m['retrospectiveCapture']['all_positive:finalized']['overall']['champion']['n']>0


def test_reproducible_sealed_experiment_and_dataset_tampering(tmp_path):
    inputs=tmp_path/'inputs';inputs.mkdir(); m,h=sealed_fixture(inputs)
    for day in ['2026-10-06','2026-10-07']:
        s=snapshot(day); b=encode(s); sh=sha(b);(inputs/'sources'/(sh+'.json')).write_bytes(b)
        m['runs'].append({'path':'sources/'+sh+'.json','sha256':sh,'date':day,'issuedAt':s['generatedAt']})
        a={'date':day,'series':[{'ts':x['ts'],'actualMw':x['actualMw']} for x in s['hourlyDiagnostics']]}
        b=encode(a); ah=sha(b);(inputs/'sources'/(ah+'.json')).write_bytes(b)
        m['actuals'][day]={'path':'sources/'+ah+'.json','sha256':ah,'state':'finalized','date':day}
    m['asOf']='2026-10-08T10:00:00+09:00';(inputs/'manifest.json').write_bytes(encode(m))
    periods={'train':['2026-10-05','2026-10-05'],'validation':['2026-10-06','2026-10-06'],'holdout':['2026-10-07','2026-10-07']}
    out=tmp_path/'experiment';prepare(inputs,sha(encode(m)),out,periods)
    ih=sha((out/'PREREGISTRATION.json').read_bytes());result=run(out,ih)
    assert result['status'] in ('RETAIN CHALLENGER','PROMOTE TO SHADOW')
    assert len(result['results'])==3
    with pytest.raises(ValueError,match='already executed'):run(out,ih)
    with pytest.raises(ValueError,match='already exists'):prepare(inputs,sha(encode(m)),out,periods)
    other=tmp_path/'tamper';prepare(inputs,sha(encode(m)),other,periods)
    h=sha((other/'PREREGISTRATION.json').read_bytes());(other/'dataset.jsonl').write_bytes(b'{}\n')
    with pytest.raises(ValueError,match='dataset hash'):run(other,h)
