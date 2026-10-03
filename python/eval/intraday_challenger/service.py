"""Independent Docker shadow sidecar. No ETL, serving, scheduler, or API calls."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import threading

from .evidence import encode, sha, timestamp
from .service_evaluation import evaluate
from .service_feed import PREFIX, sync
from .service_io import WorkerLock, atomic_json
from .service_records import capture_shared, read_runs
from .service_registry import adopt_registry, input_path, load_active, read_registry
from .shadow import _now
from .storage import exclusive_json, workspace

SERVICE_CONTRACT = 'intraday-shadow-service/1.0.0'


def log(event, **fields):
    print(json.dumps({'event': event, 'at': _now().isoformat(), **fields},
                     ensure_ascii=False, allow_nan=False), flush=True)


def config(input_root, filename, output):
    out = workspace(output)
    inputs = Path(input_root).resolve()
    if out.is_relative_to(inputs) or inputs.is_relative_to(out):
        raise ValueError('Read-only model inputs and writable shadow workspace must be separate')
    value = json.loads(input_path(input_root, filename).read_bytes())
    expected = {'contract','remote','startDate','registry','pollIntervalSeconds',
                'maxIndependentCaptureDelaySeconds','healthMaxLoopAgeSeconds'}
    if set(value) != expected or value['contract'] != SERVICE_CONTRACT:
        raise ValueError('Unsupported shadow configuration')
    for key in ('pollIntervalSeconds','maxIndependentCaptureDelaySeconds','healthMaxLoopAgeSeconds'):
        if type(value[key]) is not int or value[key] <= 0:
            raise ValueError('Positive integer service timing required')
    if value['maxIndependentCaptureDelaySeconds'] < value['pollIntervalSeconds']:
        raise ValueError('Live window shorter than poll interval')
    if value['healthMaxLoopAgeSeconds'] <= value['pollIntervalSeconds'] + 180:
        raise ValueError('Health window must tolerate one blocking Git timeout and normal polling')
    return value


def health(output, now=None):
    try:
        out = workspace(output)
        status = json.loads(workspace(out / 'status.json').read_bytes())
        age = ((now or _now()) - timestamp(status['lastLoopAt'])).total_seconds()
        valid = status['healthState'] in ('HEALTHY', 'DEGRADED') and 0 <= age <= status['healthMaxLoopAgeSeconds']
        return {'healthy': valid, 'healthState': status['healthState'], 'loopAgeSeconds': age,
                'reason': None if valid else 'stale loop, stopped worker, or fatal state'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'healthy': False, 'healthState': 'UNAVAILABLE', 'reason': 'status/workspace inaccessible or invalid'}


class Worker:
    def __init__(self, input_root, config_name, output, stop=None):
        self.input_root = Path(input_root)
        self.out = workspace(output)
        self.settings = config(input_root, config_name, self.out)
        self.stop = stop or threading.Event()
        self.control_path = self.out / 'control.json'
        self.control = json.loads(self.control_path.read_bytes()) if self.control_path.exists() else {}
        self.live_policy = {'contract':'intraday-shadow-live-eligibility/1.0.0',
                            'maxCaptureDelaySeconds':self.settings['maxIndependentCaptureDelaySeconds']}
        if self.control.get('livePolicy') not in (None,self.live_policy):
            raise ValueError('A changed live-eligibility policy requires a new workspace/explicit policy version')
        self.cache = {}
        self.registry = self.control.get('registry')
        self.memberships = self.control.get('memberships', {})
        self.manifest = self.control.get('manifest')
        self.rejected = self.control.get('rejected', {})
        self.detected = set(self.control.get('detectedSnapshots', []))
        self.signature = self.control.get('evaluationSignature')
        old_status = json.loads((self.out / 'status.json').read_bytes()) if (self.out / 'status.json').exists() else {}
        self.status = {**old_status, 'contract': SERVICE_CONTRACT, 'serviceStartTime': _now().isoformat(),
            'lastLoopAt': _now().isoformat(), 'lastSuccessfulGitSync': old_status.get('lastSuccessfulGitSync'),
            'lastSourceRevision': old_status.get('lastSourceRevision'),
            'lastSnapshotDetected': old_status.get('lastSnapshotDetected'),
            'lastProspectivePrediction': old_status.get('lastProspectivePrediction'),
            'lastActualDetected': old_status.get('lastActualDetected'), 'lastEvaluation': old_status.get('lastEvaluation'),
            'activeChallengers': [], 'challengerIdentities': [], 'errorCount': old_status.get('errorCount',0),
            'lastError': old_status.get('lastError'), 'healthState': 'HEALTHY',
            'healthMaxLoopAgeSeconds': self.settings['healthMaxLoopAgeSeconds'],
            'pollIntervalSeconds': self.settings['pollIntervalSeconds'], 'productionChanged': False}
        runs = read_runs(self.out)
        self.existing = {(r['identitySha256'], r['source']['sha256']) for r, _, _ in runs}
        self.seen_issues = {(r['identitySha256'],r['issuedAt']) for r,_,_ in runs}
        self.prediction_hashes = {h for _,_,h in runs}

    def persist(self):
        atomic_json(self.out / 'status.json', self.status)
        atomic_json(self.control_path, {'registry': self.registry, 'memberships': self.memberships,
            'manifest': self.manifest, 'rejected': self.rejected, 'detectedSnapshots': sorted(self.detected),
            'evaluationSignature': self.signature, 'livePolicy':self.live_policy})

    def error(self, exc, fatal=False, **fields):
        # Exception type and controlled context only: never disclose external stderr or keys.
        value = {'at': _now().isoformat(), 'type': type(exc).__name__, 'fatal': fatal, **fields}
        self.status['errorCount'] += 1
        self.status.update(lastError=value, healthState='FATAL' if fatal else 'DEGRADED')
        log('fatal_error' if fatal else 'recoverable_error', **value)

    def cycle(self):
        self.status.update(lastLoopAt=_now().isoformat(), healthState='HEALTHY')
        self.persist()
        registry, registry_sha = read_registry(self.input_root, self.settings['registry'], _now())
        if self.registry != registry:
            self.memberships = adopt_registry(self.out, registry, registry_sha, self.registry, self.memberships, _now())
            log('model_identity_change', registrySha256=registry_sha,
                active=[e['identitySha256'] for e in registry['challengers'] if e['status']=='ACTIVE'])
            self.registry = registry
            self.persist()
        active = load_active(self.input_root, registry, self.cache)
        self.status['activeChallengers'] = [e['modelName'] for e, _ in active]
        self.status['challengerIdentities'] = [e['identitySha256'] for e, _ in active]
        try:
            previous = self.manifest
            manifest, changed = sync(self.settings['remote'], self.out, self.settings['startDate'], previous)
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, json.JSONDecodeError) as exc:
            self.error(exc, operation='public_git_sync')
            self.persist()
            return
        self.manifest = manifest
        self.status.update(lastSuccessfulGitSync=_now().isoformat(), lastSourceRevision=manifest['revision'])
        log('source_sync' if changed else 'no_changes', revision=manifest['revision'])
        label_hashes = {p:r['sha256'] for p,r in manifest['sources'].items() if p.startswith('actual/') or p=='.etl_state.json'}
        old_labels = {p:r['sha256'] for p,r in (previous or {}).get('sources',{}).items() if p.startswith('actual/') or p=='.etl_state.json'}
        if label_hashes != old_labels:
            self.status['lastActualDetected'] = _now().isoformat()
            log('actual_revision', changedPaths=[p for p in sorted(set(label_hashes)|set(old_labels))
                                               if label_hashes.get(p)!=old_labels.get(p)])
        duplicate_count = 0
        for path, ref in sorted(manifest['sources'].items()):
            if not path.startswith(PREFIX):
                continue
            if ref['sha256'] not in self.detected:
                self.detected.add(ref['sha256'])
                self.status['lastSnapshotDetected'] = {'at':_now().isoformat(), 'sourceSha256':ref['sha256'], 'path':path}
                log('new_snapshot', sourceSha256=ref['sha256'])
            pending = [(e,m) for e,m in active if (e['identitySha256'],ref['sha256']) not in self.existing
                       and e['identitySha256']+':'+ref['sha256'] not in self.rejected]
            duplicate_count += len(active)-len(pending)
            if not pending:
                continue
            try:
                captures = capture_shared(self.out, ref, pending, self.memberships, registry_sha,
                                          _now(), self.settings['maxIndependentCaptureDelaySeconds'], self.existing,
                                          self.seen_issues, clock=_now)
                for capture in captures:
                    if capture.get('state') == 'not_applicable':
                        key = capture['identitySha256']+':'+ref['sha256']
                        self.rejected[key] = capture
                        exclusive_json(workspace(self.out/'exclusions'/(sha(encode([key,capture]))+'.json')),capture)
                        log('ineligible_snapshot', **capture)
                        continue
                    if capture.get('state') == 'unavailable':
                        key = capture['identitySha256']+':'+ref['sha256']
                        self.rejected[key] = capture
                        exclusive_json(workspace(self.out/'rejections'/(sha(encode([key,capture]))+'.json')),capture)
                        self.error(ValueError(), operation='challenger_inference', **capture)
                        continue
                    log('challenger_prediction', **capture)
                    self.prediction_hashes.add(capture['recordSha256'])
                    if capture['delayMinutes'] > self.settings['maxIndependentCaptureDelaySeconds']/60:
                        log('delayed_capture', **capture)
                    if capture['prospective']:
                        self.status['lastProspectivePrediction'] = {'at':_now().isoformat(), **capture}
            except (ValueError, KeyError, OSError, TypeError) as exc:
                for entry,_ in pending:
                    self.rejected[entry['identitySha256']+':'+ref['sha256']] = {'type':type(exc).__name__}
                self.error(exc, operation='snapshot_capture', sourceSha256=ref['sha256'])
        if duplicate_count:
            log('duplicate_skip', identitySnapshotPairs=duplicate_count)
        signature = sha(encode({'labels':label_hashes, 'runs':sorted(self.prediction_hashes), 'registry':registry_sha}))
        if signature != self.signature:
            try:
                result = evaluate(self.out, manifest, registry, _now(), registry_sha)
                self.status['lastEvaluation'] = {'at':_now().isoformat(), **result}
                self.signature = signature
                log('evaluation', path=result['path'], sha256=result['sha256'], models=len(result['models']))
            except (ValueError, KeyError, OSError, TypeError) as exc:
                self.error(exc, operation='actual_evaluation')
        self.status['lastLoopAt'] = _now().isoformat()
        self.persist()

    def run(self, cycles=None):
        log('startup', pollIntervalSeconds=self.settings['pollIntervalSeconds'], productionChanged=False)
        count = 0
        self.persist()
        try:
            while not self.stop.is_set() and (cycles is None or count < cycles):
                self.cycle()
                count += 1
                if cycles is None or count < cycles:
                    self.stop.wait(self.settings['pollIntervalSeconds'])
        except Exception as exc:
            self.error(exc, fatal=True, operation='worker_integrity')
            self.persist()
            raise
        finally:
            if self.status['healthState'] != 'FATAL':
                self.status.update(healthState='STOPPED', lastLoopAt=_now().isoformat())
                self.persist()
            log('shutdown', healthState=self.status['healthState'], cycles=count)
        return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run','health','status'))
    parser.add_argument('--input-root', default='/shadow-input')
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--output-root', default='/app/data/intraday_challenger/live')
    parser.add_argument('--cycles', type=int)
    args = parser.parse_args()
    if args.command == 'health':
        result = health(args.output_root)
        print(json.dumps(result))
        raise SystemExit(0 if result['healthy'] else 1)
    if args.command == 'status':
        try:
            print(workspace(Path(args.output_root)/'status.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            print(json.dumps({'state':'unavailable','reason':'status/workspace inaccessible'}))
            raise SystemExit(2)
        return
    if args.cycles is not None and args.cycles < 1:
        parser.error('cycles must be positive')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        with WorkerLock(args.output_root):
            try:
                Worker(args.input_root,args.config,args.output_root,stop).run(args.cycles)
            except Exception as exc:
                atomic_json(Path(args.output_root)/'status.json', {'contract':SERVICE_CONTRACT,
                    'healthState':'FATAL','lastLoopAt':_now().isoformat(),'healthMaxLoopAgeSeconds':2100,
                    'lastError':{'type':type(exc).__name__,'fatal':True},'productionChanged':False})
                raise
    except Exception as exc:
        log('fatal_error', type=type(exc).__name__, operation='startup_or_worker', productionChanged=False)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
