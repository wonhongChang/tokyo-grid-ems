import json
from datetime import date, timedelta
from pathlib import Path
import pytest
import yaml

from python.etl import run_batch as rb
from python.forecast import d1_component as cp
from python.forecast.rolling_interval_calibration import build_lead_conformal_profile, serving_policy_fingerprint

DAY=date(2026,11,30)
ISSUE='2026-11-29T17:10:00+09:00'
def put(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),encoding='utf8')
def load_cfg():
    return yaml.safe_load((Path(__file__).resolve().parents[1]/'config.yaml').read_text(encoding='utf8'))
def fixtures(out):
    cfg=load_cfg()
    assert serving_policy_fingerprint(cfg)==cp.BASE
    cfg['d1_component_trial']=dict(policy=cp.FINGERPRINT,targets=[str(DAY)],receipt_dir=str(out.parent/(out.name+'-proof')))
    raw=[rb.HourlyForecast(f'{DAY}T{h:02d}:00:00+09:00',10000+h,9100+h,11000+h,8100+h,12000+h) for h in range(24)]
    base=[cp.shift(v,200) for v in raw]
    build=rb.ForecastBuildResult(base,'lgbm_quantile_q50',{'raw_lgbm':raw,'pre_calibration':base},
        {'sameRegimeDayLevelCalibration':{'applied':True,'historyDates':['2026-11-16','2026-11-17','2026-11-18']}})
    put(out/'.lgbm_model_meta.json',{'artifactSha256':cp.ARTIFACT})
    orig=dict(generatedAt='2026-11-29T01:00:00+09:00',targetDate=str(DAY),model={'artifactSha256':cp.ARTIFACT},
              servingPolicyFingerprint=cp.BASE,origin={'type':'day_ahead_first_publish','immutable':True})
    put(out/cp.origin_path(DAY),orig)
    import hashlib
    proof=dict(schema='d1-first-public/1',date=str(DAY),commit='f'*40,publishedBy='2026-11-29T01:02:02+09:00',priorPolicy=cp.BASE,
               originSHA256=hashlib.sha256((out/cp.origin_path(DAY)).read_bytes()).hexdigest())
    put(Path(cfg['d1_component_trial']['receipt_dir'])/(str(DAY)+'.json'),proof)
    return cfg,build

def test_guarded_scopes_and_rollback(tmp_path):
    cfg,b=fixtures(tmp_path)
    y=cp.choose(b,cfg,DAY,ISSUE,tmp_path)
    assert y.forecasts[0].forecast_mw==10000 and b.forecasts[0].forecast_mw==10200
    assert cp.choose(b,cfg,DAY,str(DAY)+'T00:03:00+09:00',tmp_path) is b
    assert cp.choose(b,cfg,DAY+timedelta(days=1),ISSUE,tmp_path) is b
    assert cp.choose(b,{},DAY,ISSUE,tmp_path) is b
    put(tmp_path/'.lgbm_model_meta.json',{'artifactSha256':'other'})
    assert cp.choose(b,cfg,DAY,ISSUE,tmp_path) is b

def test_absent_future_or_wrong_publication_receipt_keeps_incumbent(tmp_path):
    cfg,b=fixtures(tmp_path)
    path=Path(cfg['d1_component_trial']['receipt_dir'])/(str(DAY)+'.json')
    valid=json.loads(path.read_text())
    for invalid in [dict(valid,originSHA256='1'*64),dict(valid,date='2026-11-24'),dict(valid,publishedBy=ISSUE)]:
        put(path,invalid)
        assert cp.choose(b,cfg,DAY,ISSUE,tmp_path) is b
    path.unlink()
    assert cp.choose(b,cfg,DAY,ISSUE,tmp_path) is b

def test_windows_transport_matches_public_lf_bytes_only(tmp_path):
    import hashlib
    cfg,b=fixtures(tmp_path)
    origin=tmp_path/cp.origin_path(DAY)
    public=origin.read_bytes()+b'\n'
    receipt=Path(cfg['d1_component_trial']['receipt_dir'])/(str(DAY)+'.json')
    proof=json.loads(receipt.read_text())
    put(receipt,dict(proof,originSHA256=hashlib.sha256(public).hexdigest()))
    origin.write_bytes(public.replace(b'\n',b'\r\n'))
    assert cp.choose(b,cfg,DAY,ISSUE,tmp_path) is not b
    origin.write_bytes(origin.read_bytes()+b' ')
    assert cp.choose(b,cfg,DAY,ISSUE,tmp_path) is b

def test_switch_outside_model_config_and_explicit_off(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.delenv(cp.SWITCH,raising=False)
    base=load_cfg();assert cp.with_trial(base) is base
    trial=dict(policy=cp.FINGERPRINT,targets=[str(DAY)],receipt_dir='/not-allowed')
    put(cp.RECEIPTS/'trial.json',trial)
    assert cp.requested(cp.with_trial(base),DAY) and 'd1_component_trial' not in base
    assert 'receipt_dir' not in cp.with_trial(base)['d1_component_trial']
    assert serving_policy_fingerprint(cp.with_trial(base))==serving_policy_fingerprint(base)==cp.BASE
    monkeypatch.setenv(cp.SWITCH,'{"targets":[]}');assert not cp.requested(cp.with_trial(base),DAY)
    monkeypatch.setenv(cp.SWITCH,'invalid');assert cp.with_trial(base) is base

def test_publication_snapshot_and_interval_ownership(tmp_path):
    cfg,b=fixtures(tmp_path);true=cp.choose(b,cfg,DAY,ISSUE,tmp_path)
    meta=true.metadata['d1PointPolicy']
    stock=rb.build_forecast_json(DAY,b.forecasts,cfg,b.model_name,out_dir=tmp_path,generated_at=ISSUE)
    active=rb.build_forecast_json(DAY,true.forecasts,cfg,b.model_name,out_dir=tmp_path,generated_at=ISSUE,d1_policy=meta)
    assert active['servingPolicyFingerprint']!=stock['servingPolicyFingerprint']
    assert active['peak']['forecastMw']==stock['peak']['forecastMw']-200
    for x,y in zip(active['series'],stock['series']):
        assert x['intervalReferenceForecastMw']==y['forecastMw']
        for k in ['forecastMw','p95LowerMw','p95UpperMw','p99LowerMw','p99UpperMw']:
            assert x[k]==pytest.approx(y[k]-200)
    path=rb._write_forecast_snapshot(tmp_path,DAY,true.forecasts,cfg,true.model_name,ISSUE,'intraday',False,true.stages,true.metadata)
    snap=json.loads(path.read_text(encoding='utf8'))
    assert snap['series']==active['series'] and snap['peak']==active['peak']
    assert snap['forecastBuild']['series'][0]['forecastMwByStage']['raw_lgbm']==10000
    assert snap['forecastBuild']['series'][0]['forecastMwByStage']['incumbent_pre_calibration']==10200
    assert cp.interval_role(snap,cp.BASE)=='intervalReferenceForecastMw'
    snap['d1PointPolicy']['fingerprint']='other'
    assert cp.interval_role(snap,cp.BASE) is None

def test_next_day_interval_profile_remains_byte_equivalent(tmp_path):
    normal=tmp_path/'normal';trial=tmp_path/'trial'
    cfg,b=fixtures(normal);cfg_trial,_=fixtures(trial)
    for out in [normal,trial]:
        put(out/'.etl_state.json',{'okDates':[str(DAY)]})
        put(out/'actual'/f'{DAY}.json',{'series':[{'ts':p.ts,'actualMw':12000} for p in b.forecasts]})
        chosen=cp.choose(b,cfg_trial,DAY,ISSUE,out) if out==trial else b
        rb._write_forecast_snapshot(out,DAY,chosen.forecasts,cfg,b.model_name,ISSUE,'intraday',False,chosen.stages,chosen.metadata)
    d=DAY+timedelta(days=3);elapsed=str(d)+'T08:00:00+09:00'
    ctrl=build_lead_conformal_profile(normal,d,cfg,elapsed,cp.ARTIFACT)
    alt=build_lead_conformal_profile(trial,d,cfg,elapsed,cp.ARTIFACT)
    assert ctrl['selectedSamples']==24 and ctrl==alt

def test_delayed_midnight_freezes_only_already_observed_previous_public_forecast(tmp_path):
    cfg,b=fixtures(tmp_path)
    y=cp.choose(b,cfg,DAY,ISSUE,tmp_path)
    active=rb.build_forecast_json(DAY,y.forecasts,cfg,y.model_name,out_dir=tmp_path,generated_at=ISSUE,d1_policy=y.metadata['d1PointPolicy'])
    put(tmp_path/'forecast'/f'{DAY}.json',active)
    # First D0 on time: no observation, all future native stock is identical.
    a,_=rb._freeze_observed_forecast_hours(tmp_path,DAY,b.forecasts,b.model_name)
    assert a==b.forecasts
    # A missed first D0: the already-public past slot cannot be silently rewritten.
    put(tmp_path/'actual'/f'{DAY}.json',{'series':[{'ts':a[0].ts,'actualMw':10100}]})
    late,_=rb._freeze_observed_forecast_hours(tmp_path,DAY,b.forecasts,b.model_name)
    assert late[0].forecast_mw==active['series'][0]['forecastMw'] and late[1:]==b.forecasts[1:]
