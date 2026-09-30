"""Offline design prototype. No ETL, forecasting, model, network or review integration."""
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

VERSION='review-bundle/0.2.0-design'
JST=timezone(timedelta(hours=9))
TARGET=32768
TOP=3
BANDS=[(0,5),(6,10),(11,15),(16,18),(19,23)]
SELECTION=dict(leadExclusive=0,leadInclusive=120,bands=BANDS,topN=TOP,deltaRequiresContiguous=True)
METHODS={
 'published':dict(basis='published_at_scope_revision',errorSign='forecast_minus_actual',pairing='same_target',unit='MW'),
 'advance':dict(basis='same_capture_minimum_positive_lead',lead=[0,120],tepcoIssuedAt=None,issuanceEquality='unknown_capture_only'),
 'stages':dict(basis='same_run_raw_pre_post',lead=[0,120],selection='minimum_positive_lead',joinSeconds=120,joinToleranceMw=.2),
 'retrospective':dict(basis='nonpositive_lead_stage',notInterchangeableWith='stages'),
 'interval':dict(basis='nearest_retained_interval_snapshot',lead=[0,120],independentOfStageAndAdvancePopulation=True),
 'candidate':dict(basis='all_recorded_issue_target_pairs',nearestSelection=False,allChangedPairsRetained=True),
 'followup':dict(basis='separate_revision_delta',neverOverwritePrimary=True),
 'metadata':dict(basis='recorded_only',missingNotFalse=True)}

def enc(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def read(p):return json.loads(Path(p).read_bytes())
def at(x,p):
    for k in p.split('/')[1:]:
        k=k.replace('~1','/').replace('~0','~');x=x[int(k)] if isinstance(x,list) else x[k]
    return x
def ref(source,pointer=''):return dict(source=source,pointer=pointer)
def state(status='available',code='OK',sampleCount=None,denominator=None,expectedPopulation=None,
          observedPopulation=None,expectedSource=None,expectedHash=None,pointer=None,missingLocator=None):
    return dict(status=status,code=code,sampleCount=sampleCount,denominator=denominator,
        expectedPopulation=expectedPopulation,observedPopulation=observedPopulation,
        expectedSource=expectedSource,expectedHash=expectedHash,pointer=pointer,missingLocator=missingLocator)

class EvidenceError(Exception):
    def __init__(self,s):self.state=s;super().__init__(s['code'])

def fail(code,**kw):raise EvidenceError(state('unavailable',code,**kw))
def ts(value,date=None):
    try:
        t=datetime.fromisoformat(value)
        if t.utcoffset() is None:fail('NAIVE_TIMESTAMP',missingLocator=str(value))
        t=t.astimezone(JST)
    except (TypeError,ValueError):fail('INVALID_TIMESTAMP',missingLocator=str(value))
    if date and t.date().isoformat()!=date:
        fail('FILE_DATE_MISMATCH',expectedPopulation={'date':date},observedPopulation={'date':t.date().isoformat()})
    return t

def metrics(rows,column='forecast'):
    e=[r[column]-r['actual'] for r in rows];den=math.fsum(r['actual'] for r in rows)
    if not e:return dict(n=0,mae=None,rmse=None,wapePct=None,bias=None,maxAbsError=None)
    return dict(n=len(e),mae=round(math.fsum(map(abs,e))/len(e),3),rmse=round(math.sqrt(math.fsum(v*v for v in e)/len(e)),3),
        wapePct=round(100*math.fsum(map(abs,e))/den,3) if den else None,bias=round(math.fsum(e)/len(e),3),maxAbsError=round(max(map(abs,e)),3))

class Loader:
    def __init__(self,inventory):
        self.inventory=inventory;self.cache={};self.events=[];self.requests=Counter()
        self.identity=(VERSION,sha(Path(__file__).read_bytes()),sha(enc(SELECTION)))
    def get(self,key):
        self.requests[key]+=1;e=self.inventory.get(key)
        if not e:fail('SOURCE_NOT_REGISTERED',expectedSource=key,missingLocator=key)
        p=Path(e['frozen'])
        try:
            stat=p.stat(); stamp=(stat.st_size,stat.st_mtime_ns)
            ck=(e['sha256'],*self.identity)
            previous=self.cache.get(ck)
            if previous and previous['path']==str(p) and previous['stamp']==stamp:return previous['value']
            raw=p.read_bytes()
        except FileNotFoundError:fail('RETENTION_LOSS',expectedSource=key,expectedHash=e['sha256'],missingLocator=str(p))
        except OSError:fail('SOURCE_IO_ERROR',expectedSource=key,expectedHash=e['sha256'],missingLocator=str(p))
        self.events.append(dict(source=key,bytes=len(raw),sha256=sha(raw)))
        if sha(raw)!=e['sha256']:fail('SOURCE_HASH_MISMATCH',expectedSource=key,expectedHash=e['sha256'],missingLocator=str(p))
        try:v=json.loads(raw)
        except (ValueError,UnicodeError):fail('INVALID_JSON',expectedSource=key,expectedHash=e['sha256'])
        self.cache[ck]=dict(value=v,path=str(p),stamp=stamp)
        return v
    def resolve(self,key,pointer=''):
        try:return dict(state=state(),value=at(self.get(key),pointer),provenance=[ref(key,pointer)])
        except EvidenceError as e:return dict(state=e.state,value=None,provenance=[ref(key,pointer)])
        except (KeyError,IndexError,TypeError,ValueError):
            return dict(state=state('unavailable','MISSING_POINTER',expectedSource=key,
                expectedHash=self.inventory.get(key,{}).get('sha256'),pointer=pointer,missingLocator=pointer),value=None,provenance=[ref(key,pointer)])
    def measurement(self):
        counts=Counter(e['source'] for e in self.events)
        return dict(uniqueSourceFiles=len(counts),readEvents=len(self.events),sourceBytesRead=sum(e['bytes'] for e in self.events),
            repeatedSourceReads=sum(n-1 for n in counts.values()),getRequests=sum(self.requests.values()),
            cacheIdentity=list(self.identity),scope='actual content reads; excludes stat, imports, output writes and fixture verification')

def pair_actual_forecast(actual,forecast,date,ak,fk):
    amap={};ex=[]
    for i,r in enumerate(actual['series']):
        t=ts(r['ts'],date).isoformat()
        if t in amap:fail('DUPLICATE_TIMESTAMP',expectedSource=ak,pointer=f'/series/{i}',missingLocator=t)
        amap[t]=(i,r)
    seen=set();rows=[]
    for i,f in enumerate(forecast['series']):
        t=ts(f['ts'],date).isoformat();h=ts(t).hour
        if t in seen:fail('DUPLICATE_TIMESTAMP',expectedSource=fk,pointer=f'/series/{i}',missingLocator=t)
        seen.add(t);ai,a=amap.get(t,(None,{}));v=a.get('actualMw')
        source=a.get('actualSource');code=None
        if 'fallback' in str(source):code='FALLBACK_NOT_OBSERVED'
        elif not finite(v) or v<=0:code='MISSING_OR_INVALID_ACTUAL'
        elif not finite(f.get('forecastMw')):code='MISSING_OR_INVALID_FORECAST'
        ar=ref(ak,f'/series/{ai}') if ai is not None else None
        if code:ex.append(dict(hour=h,code=code,actualRef=ar,forecastRef=ref(fk,f'/series/{i}')));continue
        rows.append(dict(hour=h,ts=t,actual=v,forecast=f['forecastMw'],error=round(f['forecastMw']-v,3),actualRef=ar,forecastRef=ref(fk,f'/series/{i}')))
    return sorted(rows,key=lambda r:r['hour']),ex

def shape(rows):
    transitions=[];runs=[]
    for r in rows:
        e=r['forecast']-r['actual'];sign=1 if e>0 else -1 if e<0 else 0
        if runs and runs[-1][1]+1==r['hour'] and runs[-1][2]==sign:runs[-1][1]=r['hour']
        else:runs.append([r['hour'],r['hour'],sign])
    for a,b in zip(rows,rows[1:]):
        if b['hour']!=a['hour']+1:continue
        ad=b['actual']-a['actual'];fd=b['forecast']-a['forecast']
        transitions.append(dict(fromHour=a['hour'],toHour=b['hour'],actualDelta=round(ad,3),forecastDelta=round(fd,3),deltaError=round(fd-ad,3),opposingSigns=ad*fd<0))
    return dict(signRuns=runs,transitions=transitions,operationalImportance=None)

class Builder:
    def __init__(self,manifest,out,loader=None):
        self.manifest=manifest;self.out=Path(out);self.loader=loader or Loader(manifest['inputs'])
        self.facts=[];self.factIndex={};self.sections=[];self.dayIndex={};self.notices=[];self.dayData={};self.families=Counter()
    def write(self,path,obj):
        raw=enc(obj);p=self.out/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        return dict(path=path,sha256=sha(raw),bytes=len(raw),pointer='')
    def names(self,cap,prefix):return sorted(k for k in self.loader.inventory if k.startswith(cap+':'+prefix) and not k.endswith('/index.json'))
    def fact(self,scope,date,kind,method,value,n=None,provenance=None,s=None,identity=None,detail=None):
        self.families[kind]+=1;id=scope+':'+(date or 'scope')+':'+kind
        fact=dict(id=id,scope=scope,date=date,kind=kind,state=s or state(sampleCount=n),
            population=dict(id=id+':population',method=method,n=n,identity=identity,scope=scope,date=date),
            value=value,provenance=provenance or [],detailRef=detail)
        if fact['state']['status']!='available':self.notices.append(dict(fact=id,scope=scope,code=fact['state']['code'],state=fact['state']))
        self.facts.append(fact);return fact
    def unavailable_day(self,scope,date,error):
        self.fact(scope,date,'day_error','published',None,s=error.state)
    def prepare_day(self,scope,date):
        sid,cap=scope['id'],scope['captureKey'];ak=cap+':actual/'+date+'.json';fk=cap+':forecast/'+date+'.json'
        try:a=self.loader.get(ak);f=self.loader.get(fk);rows,ex=pair_actual_forecast(a,f,date,ak,fk)
        except EvidenceError as e:self.unavailable_day(sid,date,e);return
        ident=dict(artifact=f.get('model',{}).get('artifactSha256'),policy=f.get('servingPolicyFingerprint'),revision=scope['revision'])
        rawActualHours=[ts(r['ts'],date).hour for r in a['series'] if finite(r.get('actualMw')) and r['actualMw']>0 and 'fallback' not in str(r.get('actualSource',''))]
        denom=math.fsum(r['actual'] for r in rows)
        paired_state=state(sampleCount=len(rows),denominator=denom,expectedPopulation={'hours':24},observedPopulation={'hours':[r['hour'] for r in rows]}) if rows else state('unavailable','NO_OBSERVED_PAIRS',sampleCount=0,denominator=0,expectedPopulation={'hours':24},observedPopulation={'hours':[]},expectedSource=ak)
        detail=dict(rows=rows,excluded=ex,advance=[],stages=[],interval=[],shape=shape(rows))
        facts=[]
        def add(kind,method,value,n=None,provenance=None,s=None):
            identity=ident if method=='published' else dict(publishedContext=ident,membershipIdentity='see_detail_rows_and_run_index',compatibility='not_assumed')
            v=self.fact(sid,date,kind,method,value,n,provenance,s,identity);facts.append(v);return v
        add('coverage','published',dict(asOf=scope['asOf'],finalizedThrough=scope['finalizedThrough'],finalized=date<=scope['finalizedThrough'] and len(rawActualHours)==24,
            observedHours=len(rawActualHours),pairedHours=len(rows),missingHours=sorted(set(range(24))-set(rawActualHours)),excluded=ex),len(rows),[ref(ak),ref(fk)],paired_state)
        add('metrics','published',metrics(rows),len(rows),[ref(ak),ref(fk)],paired_state)
        add('bands','published',[dict(hours=[lo,hi],**metrics([r for r in rows if lo<=r['hour']<=hi])) for lo,hi in BANDS],len(rows),[ref(ak),ref(fk)],paired_state)
        ranked=sorted(rows,key=lambda r:(-abs(r['error']),r['hour']));keep={r['hour'] for r in ranked[:TOP]}
        pos=max(rows,key=lambda r:r['error'])['hour'] if rows else None;neg=min(rows,key=lambda r:r['error'])['hour'] if rows else None
        keep.update([pos,neg]);detail['allRankedRows']=ranked
        add('misses','published',dict(rows=[{k:r[k] for k in ['hour','actual','forecast','error']} for r in rows if r['hour'] in keep],positiveMaxHour=pos,negativeMaxHour=neg,totalRows=len(rows),omittedRows=sum(r['hour'] not in keep for r in rows)),len(rows),[ref(ak),ref(fk)],paired_state)
        tr=detail['shape']['transitions'];peak=max(tr,key=lambda r:abs(r['deltaError'])) if tr else None
        add('shape','published',dict(signRuns=detail['shape']['signRuns'],transitionCount=len(tr),opposingSignCount=sum(r['opposingSigns'] for r in tr),largestMismatch=peak,operationalImportance=None),len(rows),[ref(ak),ref(fk)],paired_state)
        actual={r['hour']:r['actual'] for r in rows};runs=[];indexRows=[]
        columns=['target','hour','run','leadMinutes','basis','stageAvailability','intervalAvailable','pointer']
        def run(source,obj,kind,issued,rootPointer=''):
            model=obj.get('model')
            artifact=model.get('artifactSha256',obj.get('artifactSha256')) if isinstance(model,dict) else obj.get('artifactSha256')
            i=len(runs);runs.append(dict(source=source,kind=kind,issuedAt=issued,runId=obj.get('runId'),
                runIdentityStatus='recorded' if obj.get('runId') else 'source_hash_plus_pointer_not_execution_id',
                sourceHash=self.loader.inventory[source]['sha256'],rootPointer=rootPointer,
                artifact=artifact,modelLabel=model if isinstance(model,str) else None,policy=obj.get('servingPolicyFingerprint')))
            return i
        selected={};ledgerKey=cap+':reports/internal/forecast-vintages/'+date+'.json'
        try:
            ledger=self.loader.get(ledgerKey)
            for si,snap in enumerate(ledger['snapshots']):
                ri=run(ledgerKey,snap,'capture',snap['capturedAt'],f'/snapshots/{si}')
                for i,r in enumerate(snap['series']):
                    target=ts(r['ts'],date);lead=(target-ts(snap['capturedAt'])).total_seconds()/60;h=target.hour
                    ptr=f'/snapshots/{si}/series/{i}'
                    indexRows.append([target.isoformat(),h,ri,lead,'advance' if lead>0 else 'retrospective_capture',None,False,ptr])
                    if h in actual and 0<lead<=120 and finite(r.get('modelForecastMw')) and finite(r.get('tepcoForecastMw')):
                        if h not in selected or lead<selected[h]['lead']:
                            selected[h]=dict(hour=h,actual=actual[h],forecast=r['modelForecastMw'],tepco=r['tepcoForecastMw'],lead=lead,capturedAt=snap['capturedAt'],sourceRef=ref(ledgerKey,ptr),sourceIdentity={k:runs[ri][k] for k in ['artifact','policy']})
            pairs=sorted(selected.values(),key=lambda r:r['hour']);st=state(sampleCount=len(pairs)) if pairs else state('unavailable','NO_ADVANCE_PAIRS',sampleCount=0,denominator=0,expectedSource=ledgerKey)
        except EvidenceError as e:pairs=[];st=e.state
        detail['advance']=pairs
        add('advance','advance',dict(model=metrics(pairs),tepco=metrics(pairs,'tepco'),issuanceEquality='unknown_capture_only'),len(pairs),[ref(ledgerKey)],st)
        stages={};allStage={};bad=[]
        for key in self.names(cap,f'reports/internal/operational-calibration/snapshots/{date}/'):
            try:c=self.loader.get(key);issued=ts(c['generatedAt']);ri=run(key,c,'calibration',c['generatedAt'])
            except EvidenceError as e:bad.append(e.state);continue
            for i,r in enumerate(c.get('hourlyDiagnostics',[])):
                target=ts(r['ts'],date);h=target.hour;lead=(target-issued).total_seconds()/60;s=r.get('forecastMwByStage') or {}
                available=dict(raw=finite(s.get('raw_lgbm')),pre=finite(s.get('pre_calibration')),post=finite(r.get('postCalibrationForecastMw')))
                ptr=f'/hourlyDiagnostics/{i}';indexRows.append([target.isoformat(),h,ri,lead,'stages' if lead>0 else 'retrospective',available,False,ptr])
                allStage[(key,h)]=r
                if h in actual and 0<lead<=120 and all(available.values()) and (h not in stages or lead<stages[h]['lead']):
                    stages[h]=dict(hour=h,actual=actual[h],raw=s['raw_lgbm'],pre=s['pre_calibration'],post=r['postCalibrationForecastMw'],lead=lead,
                        generatedAt=c['generatedAt'],stageValues=s,carryover=r.get('residualCarryover'),terminal=r.get('terminalAdjustments'),
                        actualSlope=r.get('sameDayActualSlopeMw'),sourceRef=ref(key,ptr),contextRef=ref(key,'/correction'),sourceIdentity={k:runs[ri][k] for k in ['artifact','policy']})
        ss=sorted(stages.values(),key=lambda r:r['hour']);detail['stages']=ss
        for r in ss:
            r['calibrationDelta']=round(r['post']-r['pre'],3);r['absErrorDelta']=round(abs(r['post']-r['actual'])-abs(r['pre']-r['actual']),3)
        stageState=state(sampleCount=len(ss)) if ss else state('unavailable','NO_USABLE_ADVANCE_STAGE',sampleCount=0,expectedPopulation={'basis':'stages','lead':[0,120]},observedPopulation={'usableStageRows':0})
        add('stages','stages',dict(raw=metrics([dict(actual=r['actual'],forecast=r['raw']) for r in ss]),post=metrics([dict(actual=r['actual'],forecast=r['post']) for r in ss]),
            worsenedHours=[r['hour'] for r in ss if r['absErrorDelta']>0],improvedHours=[r['hour'] for r in ss if r['absErrorDelta']<0],
            largestAdjustments=[{k:r[k] for k in ['hour','raw','pre','post','calibrationDelta','absErrorDelta']} for r in sorted(ss,key=lambda r:(-abs(r['calibrationDelta']),r['hour']))[:TOP]],
            missingSourceStates=bad),len(ss),[r['sourceRef'] for r in ss],stageState)
        noon=stages.get(12);pr={r['hour']:r for r in rows};noonValue=None
        if noon and 11 in pr and 12 in pr:
            key=noon['sourceRef']['source'];eleven=allStage.get((key,11));twelve=allStage.get((key,12))
            if eleven and twelve:
                noonValue=dict(actualDelta=round(pr[12]['actual']-pr[11]['actual'],3),publishedDelta=round(pr[12]['forecast']-pr[11]['forecast'],3),
                    rawDelta=round(twelve['forecastMwByStage']['raw_lgbm']-eleven['forecastMwByStage']['raw_lgbm'],3),sameRun=noon['generatedAt'])
        add('noon_context','stages',noonValue,2 if noonValue else 0,[noon['sourceRef']] if noon else [],None if noonValue else state('unavailable','NO_SAME_RUN_NOON_CONTEXT',sampleCount=0))
        ints={}
        for key in self.names(cap,f'forecast_snapshots/{date}/'):
            try:snap=self.loader.get(key);issued=ts(snap['generatedAt']);ri=run(key,snap,'interval',snap['generatedAt'])
            except EvidenceError as e:bad.append(e.state);continue
            group=(snap.get('intervalCalibration',{}).get('servedTarget') or {}).get('detailsByHour',{})
            for i,r in enumerate(snap.get('series',[])):
                target=ts(r['ts'],date);h=target.hour;lead=(target-issued).total_seconds()/60
                valid=all(finite(r.get(k)) for k in ['forecastMw','p95LowerMw','p95UpperMw','p99LowerMw','p99UpperMw'])
                indexRows.append([target.isoformat(),h,ri,lead,'interval',None,valid,f'/series/{i}'])
                if valid and h in actual and 0<lead<=120 and (h not in ints or lead<ints[h]['lead']):
                    ints[h]=dict(hour=h,lead=lead,actual=actual[h],forecast=r['forecastMw'],lo=r['p95LowerMw'],hi=r['p95UpperMw'],lo99=r['p99LowerMw'],hi99=r['p99UpperMw'],calibration=group.get(str(h)),sourceRef=ref(key,f'/series/{i}'),sourceIdentity={k:runs[ri][k] for k in ['artifact','policy']})
        iv=sorted(ints.values(),key=lambda r:r['hour']);detail['interval']=iv
        profile=f.get('intervalCalibration');detail['intervalProfile']=profile
        add('interval','interval',dict(n=len(iv),covered=sum(r['lo']<=r['actual']<=r['hi'] for r in iv),meanWidth=round(sum(r['hi']-r['lo'] for r in iv)/len(iv),3) if iv else None,
            orderingErrors=sum(not r['lo99']<=r['lo']<=r['forecast']<=r['hi']<=r['hi99'] for r in iv),
            applicationCounts=dict(Counter((r['calibration'] or {}).get('application') or 'unavailable' for r in iv)),
            profile={k:profile.get(k) for k in ['availability','selectedSamples','excludedSnapshots','minimumSamples','minimumHistoryDays','historyCutoffExclusive','servingPolicyFingerprint']} if profile else None),len(iv),[ref(fk,'/intervalCalibration')],
            None if iv else state('unavailable','NO_USABLE_INTERVAL_POPULATION',sampleCount=0))
        weatherKey=cap+':reports/internal/operational-calibration/'+date+'.json'
        try:
            w=self.loader.get(weatherKey);humid=sum(finite(r.get('humidityPct')) for r in w['hourlyDiagnostics'])
            add('weather','metadata',dict(latestRun=w['generatedAt'],humidityFiniteHours=humid,issueTimeWeatherSource=None,reason='not_serialized_in_retained_calibration',cacheCaptured=False),None,[ref(weatherKey)],state('partial','WEATHER_SOURCE_NOT_RECORDED'))
        except EvidenceError as e:add('weather','metadata',None,None,[ref(weatherKey)],e.state)
        index=dict(schemaVersion=VERSION,type='run_index',scope=sid,date=date,columns=columns,runs=runs,rows=indexRows,
            allAlternativeRunsRetained=True,missingSources=bad)
        detailRef=self.write(f'details/{sid}/{date}.json',detail)
        indexRef=self.write(f'indexes/{sid}/{date}.json',index)
        for fact in facts:fact['detailRef']=detailRef
        self.dayIndex[sid+':'+date]=dict(scope=sid,date=date,indexRef=indexRef,detailRef=detailRef,alternativeRows=len(indexRows))
        self.dayData[(sid,date)]=dict(actual=a,forecast=f,rows=rows,details=detail,identity=ident)
    def followup(self,scope):
        sid=scope['id'];parent=scope['parentScope'];changes=[]
        for (s,date),data in self.dayData.items():
            if s!=sid or (parent,date) not in self.dayData:continue
            old=self.dayData[(parent,date)];before={r['ts']:r.get('actualMw') for r in old['actual']['series']}
            revisions=[];added=[]
            for r in data['actual']['series']:
                prev=before.get(r['ts']);now=r.get('actualMw')
                if prev!=now:
                    rec=dict(hour=ts(r['ts']).hour,before=prev if prev is None or finite(prev) else None,after=now if now is None or finite(now) else None)
                    if prev is not None and not finite(prev):rec['invalidBeforeValue']=str(prev)
                    if now is not None and not finite(now):rec['invalidAfterValue']=str(now)
                    (added if prev is None and now is not None else revisions).append(rec)
            changes.append(dict(date=date,addedActuals=added,revisedActuals=revisions,primaryIdentity=old['identity'],followupIdentity=data['identity'],
                beforeFinalizedThrough=next(x['finalizedThrough'] for x in self.manifest['scopes'] if x['id']==parent),afterFinalizedThrough=scope['finalizedThrough'],
                intervalBefore=old['forecast'].get('intervalCalibration'),intervalAfter=data['forecast'].get('intervalCalibration'),
                primaryActual=ref(next(s['captureKey'] for s in self.manifest['scopes'] if s['id']==parent)+':actual/'+date+'.json'),followupActual=ref(scope['captureKey']+':actual/'+date+'.json')))
        d=self.write(f'details/{sid}/changes.json',changes)
        self.fact(sid,None,'changes','followup',dict(parentScope=parent,dates=[dict(date=r['date'],addedActualHours=[v['hour'] for v in r['addedActuals']],revisedActualHours=[v['hour'] for v in r['revisedActuals']],policyChanged=r['primaryIdentity']['policy']!=r['followupIdentity']['policy'],artifactChanged=r['primaryIdentity']['artifact']!=r['followupIdentity']['artifact']) for r in changes]),detail=d)
    def candidate(self,scope):
        key='candidate:lift_replay.json';sid=scope['id'];d=self.loader.get(key);rows=[];changed=[];degraded=[]
        for i,r in enumerate(d.get('rows',[])):
            ptr=f'/rows/{i}';record=dict(r,sourceRef=ref(key,ptr))
            if all(finite(r.get(k)) for k in ['baseline','candidate','actual']):
                record.update(baselineAbsError=round(abs(r['baseline']-r['actual']),3),candidateAbsError=round(abs(r['candidate']-r['actual']),3))
                record['absErrorDelta']=round(record['candidateAbsError']-record['baselineAbsError'],3)
                if r['candidate']!=r['baseline']:
                    changed.append(record)
                    if record['absErrorDelta']>0:degraded.append(record)
            rows.append(record)
        fields=['candidateArtifactSha256','baselineArtifactSha256','trainingCutoff','development','holdout','methodology','gates']
        metadata={k:dict(state=state() if d.get(k) is not None else state('unavailable','FIELD_NOT_RECORDED',expectedSource=key,pointer='/'+k),value=d.get(k)) for k in fields}
        mismatches=[]
        for k,expected in scope.get('expectedIdentity',{}).items():
            actual=d.get(k)
            if actual is not None and actual!=expected:mismatches.append(dict(field=k,expected=expected,observed=actual))
        gates=d.get('gates');failedGates=None if gates is None else [g for g in gates if g.get('passed') is False or g.get('status')=='failed']
        detail=dict(schemaVersion=VERSION,type='candidate_detail',rows=rows,changedPairs=changed,degradedPairs=degraded,
            degradedSegments=[dict(date=r['day'],targetHour=r['hour'],issuedAt=r['at'],absErrorDelta=r['absErrorDelta'],sourceRef=r['sourceRef']) for r in degraded],metadata=metadata,
            failedGates=failedGates,identityMismatches=mismatches,baselineChecks=d.get('checks'),recordedKeys=sorted(d),
            historicalDecisionRef=ref('candidate:decision.md'),oldInvalidQ13='v0.1 invalid oracle preserved; use Q13-v02 exact issue/target')
        dr=self.write('details/candidate/validation.json',detail)
        index=self.write('indexes/candidate/pairs.json',dict(schemaVersion=VERSION,type='candidate_index',selection='all_recorded_pairs_no_nearest_filter',
            rows=[dict(issueTime=r['at'],targetDate=r['day'],targetHour=r['hour'],lead=r['lead'],sourceRef=r['sourceRef'],changed=r['baseline']!=r['candidate']) for r in rows]))
        missing=[k for k in fields if d.get(k) is None]
        s=state('incompatible','CANDIDATE_IDENTITY_MISMATCH') if mismatches else state('partial','INCOMPLETE_CANDIDATE_PROVENANCE') if missing else state()
        self.fact(sid,None,'candidate_validation','candidate',dict(metadata=metadata,missingFields=missing,failedGates=failedGates,
            changedPairCount=len(changed),changedPairRefs=[r['sourceRef'] for r in changed],degradedPairCount=len(degraded),degradedPairRefs=[r['sourceRef'] for r in degraded],identityMismatches=mismatches,
            validationComplete=False if missing or mismatches else None,notPromotionAuthorization=True,indexRef=index),len(rows),[ref(key)],s,detail=dr)
    def governance(self):
        pk='extra:metrics/model_promotion.json';rk='extra:metrics/operational_replay.json'
        p=self.loader.get(pk);r=self.loader.get(rk)
        dr=self.write('details/primary/governance.json',dict(promotion=p,replay=r))
        self.fact('primary',None,'governance','metadata',dict(promotionStatus=p.get('status'),promotionReason=p.get('reason'),replayMethodology=r.get('methodology'),replayPeriod=r.get('period'),candidateValidation=None),provenance=[ref(pk),ref(rk)],detail=dr)
    def emit(self):
        # All facts have permanent, independently addressable records before any
        # initial-size decision. Overflow changes packaging, not selection.
        grouped={}
        for fact in self.facts:grouped.setdefault((fact['scope'],fact['date']),[]).append(fact)
        for (scope,date),ff in sorted(grouped.items(),key=lambda x:str(x[0])):
            section=self.write(f'sections/{scope}/{date or "scope"}.json',dict(schemaVersion=VERSION,type='fact_section',facts=ff))
            self.sections.append(dict(scope=scope,date=date,ref=section,factCount=len(ff)))
            for i,f in enumerate(ff):self.factIndex[f['id']]=dict(section,pointer=f'/facts/{i}')
        catalog=self.write('fact-index.json',dict(schemaVersion=VERSION,type='fact_index',facts=self.factIndex))
        dateIndex=self.write('date-index.json',dict(schemaVersion=VERSION,type='date_index',dates=self.dayIndex))
        sourceIndex=self.write('source-index.json',dict(schemaVersion=VERSION,type='source_index',sources={k:dict(path=e['frozen'],sha256=e['sha256'],bytes=e['bytes'],logicalId=k) for k,e in self.loader.inventory.items()}))
        noticesRef=self.write('notices.json',dict(schemaVersion=VERSION,type='mandatory_notices',notices=self.notices))
        focus={s['id']:max([d for ss,d in self.dayData if ss==s['id']],default=None) for s in self.manifest['scopes']}
        initial=[f for f in self.facts if f['date'] is None or f['date']==focus.get(f['scope'])]
        manifest=self.write('section-manifest.json',dict(schemaVersion=VERSION,type='section_manifest',sections=self.sections,
            allFactIds=[f['id'] for f in self.facts],mandatoryNoticesRef=noticesRef,totalFacts=len(self.facts),scopeIds=[s['id'] for s in self.manifest['scopes']]))
        header=dict(schemaVersion=VERSION,type='review_bundle',scopes=self.manifest['scopes'],methods=METHODS,
            bounds=dict(topN=TOP,initialTargetBytes=TARGET),factIndexRef=catalog,dateIndexRef=dateIndex,sourceIndexRef=sourceIndex,
            mandatoryNotices=dict(count=len(self.notices),codes=dict(Counter(n['code'] for n in self.notices)),ref=noticesRef,allMustRemainReachable=True),
            sectionManifestRef=manifest,promotionAuthorization=False,operationalDecision=None,
            scopeComparison='No automatic compatibility across basis/population/artifact/policy/as-of',facts=initial,overflow=False)
        if len(enc(header))>TARGET:
            chunks=[];batch=[]
            def flush(batch):
                if not batch:return
                payload=dict(schemaVersion=VERSION,type='initial_chunk',facts=batch)
                r=self.write(f'chunks/{len(chunks):04}.json',payload)
                chunks.append(dict(ref=r,factIds=[f['id'] for f in batch],oversizedSingleRecord=r['bytes']>TARGET))
            for f in initial:
                if batch and len(enc(dict(schemaVersion=VERSION,type='initial_chunk',facts=batch+[f])))>TARGET:flush(batch);batch=[]
                batch.append(f)
            flush(batch)
            cm=self.write('chunk-manifest.json',dict(schemaVersion=VERSION,type='chunk_manifest',chunks=chunks,
                allFactIds=[f['id'] for f in initial],allNoticeRef=noticesRef,complete=True))
            header.update(facts=[],overflow=True,chunkManifestRef=cm)
        if len(enc(header))>TARGET:
            # Pathological header growth is explicitly paged too, with no facts
            # dropped and mandatory notices still directly linked.
            full=self.write('header-context.json',header)
            header=dict(schemaVersion=VERSION,type='paged_review_bundle',overflow=True,headerContextRef=full,
                mandatoryNoticesRef=noticesRef,sectionManifestRef=manifest,factIndexRef=catalog,dateIndexRef=dateIndex,
                sourceIndexRef=sourceIndex,bounds=dict(topN=TOP,initialTargetBytes=TARGET),promotionAuthorization=False)
        self.write('review_bundle.json',header)
    def build(self):
        started=time.perf_counter()
        for scope in self.manifest['scopes']:
            if scope['role']=='candidate_validation':self.candidate(scope);continue
            cap=scope['captureKey'];dates=[k.split('/')[-1][:-5] for k in self.names(cap,'actual/')]
            for date in dates:
                try:self.prepare_day(scope,date)
                except EvidenceError as e:self.unavailable_day(scope['id'],date,e)
            if scope['role']=='followup':self.followup(scope)
        self.governance();self.emit()
        return dict(self.loader.measurement(),preparationSeconds=time.perf_counter()-started,
            calculationFamilies=dict(self.families),initialBytes=(self.out/'review_bundle.json').stat().st_size)

class Resolver:
    """Test-only selective resolver with explicit read/return accounting."""
    def __init__(self,out,loader):
        self.out=Path(out);self.loader=loader;self.cache={};self.readEvents=[];self.returns=[]
        self.root=read(self.out/'review_bundle.json');self.initialBytes=(self.out/'review_bundle.json').stat().st_size
    def local(self,r):
        p=(self.out/r['path']).resolve()
        if not p.is_relative_to(self.out.resolve()):fail('PATH_OUTSIDE_BUNDLE',missingLocator=r['path'])
        if str(p) not in self.cache:
            try:raw=p.read_bytes()
            except FileNotFoundError:fail('RETENTION_LOSS',expectedSource=r['path'],expectedHash=r.get('sha256'),missingLocator=r['path'])
            if sha(raw)!=r['sha256']:fail('SOURCE_HASH_MISMATCH',expectedSource=r['path'],expectedHash=r['sha256'])
            self.readEvents.append(dict(path=r['path'],bytes=len(raw)));self.cache[str(p)]=json.loads(raw)
        try:return at(self.cache[str(p)],r.get('pointer',''))
        except (KeyError,IndexError,TypeError,ValueError):fail('MISSING_POINTER',expectedSource=r['path'],expectedHash=r['sha256'],pointer=r.get('pointer'),missingLocator=r.get('pointer'))
    def emit_result(self,q,r,fn):
        try:value=fn();result=dict(state=state(),value=value,locator=r)
        except EvidenceError as e:result=dict(state=e.state,value=None,locator=r)
        self.returns.append(dict(question=q,locator=r,bytes=len(enc(result)),sha256=sha(enc(result))))
        return result
    def fact(self,id,pointer='',q=None):
        def get():
            catalog=self.local(self.root['factIndexRef'])
            if id not in catalog['facts']:fail('FACT_NOT_REGISTERED',missingLocator=id)
            f=self.local(catalog['facts'][id])
            try:return at(f,pointer)
            except (KeyError,IndexError,TypeError,ValueError):fail('MISSING_POINTER',missingLocator=id+'#'+pointer,pointer=pointer)
        return self.emit_result(q,id+'#'+pointer,get)
    def detail(self,id,pointer,q=None):
        def get():
            catalog=self.local(self.root['factIndexRef'])
            if id not in catalog['facts']:fail('FACT_NOT_REGISTERED',missingLocator=id)
            r=self.local(catalog['facts'][id])['detailRef']
            if not r:fail('DETAIL_NOT_RECORDED',missingLocator=id)
            return self.local(dict(r,pointer=pointer))
        return self.emit_result(q,id+'#detail'+pointer,get)
    def source(self,key,pointer='',q=None):
        result=self.loader.resolve(key,pointer)
        self.returns.append(dict(question=q,locator=key+'#'+pointer,bytes=len(enc(result)),sha256=sha(enc(result))))
        return result
