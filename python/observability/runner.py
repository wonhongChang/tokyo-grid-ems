"""Explicit adapter for a fresh, operator-invoked CLI process, not a scheduler."""
from contextlib import ExitStack, contextmanager
from functools import wraps
from importlib import import_module
from pathlib import Path
import sys

from .runtime import Runtime


@contextmanager
def bindings(rt, entries):
    def restore(obj, attr, original):
        try:
            setattr(obj, attr, original)
        except Exception:
            pass
    with ExitStack() as stack:
        it=iter(entries)
        while True:
            try:
                obj,attr,operation,classify = next(it)
                original = vars(obj).get(attr)
            except Exception:
                break
            if original is None:
                continue
            static = isinstance(original, staticmethod)
            fn = original.__func__ if static else original
            def wrap(f, op, label):
                @wraps(f)
                def call(*args, **kwargs):
                    if op == "forecast.publish":
                        try:
                            forecast_write = args and Path(args[0]).parent.name == "forecast"
                        except (TypeError, ValueError, OSError):
                            forecast_write = False
                        if not forecast_write:return f(*args, **kwargs)
                    with rt.stage(op) as status:
                        value = f(*args, **kwargs)
                        if label:
                            try:
                                status.outcome = label(value)
                            except Exception:
                                status.outcome = "unknown"
                        return value
                return call
            try:
                wrapped = wrap(fn, operation, classify)
                setattr(obj, attr, staticmethod(wrapped) if static else wrapped)
                stack.callback(restore, obj, attr, original)
            except Exception:
                continue
        yield


def entries(command, mod):
    if command == "publish":
        yield mod,"_push_with_retry","git.publish",None
        return
    if command == "fetch":
        yield mod, "_download_zip_bytes", "source.fetch", None
        yield mod, "fetch_month", "etl.fetch_historical", lambda counts:"ok" if any(counts) else "skipped"
        return
    if command != "batch":
        return
    skip_none = lambda v: "skipped" if v is None else "ok"
    for name, op, classify in [
        ("discover_csv_files","input.inventory",lambda files:"ok" if files else "skipped"),
        ("parse_tepc_daily_csv","input.parse",None),
        ("run_quality_gate","input.quality",lambda v: {"passed":"ok","warning":"degraded","failed":"failed"}[v.value]),
        ("_inject_today_actuals","cache.prepare",None),
        ("_build_forecast_pipeline","forecast.issue",lambda v:"degraded" if v.model_name=="baseline_dow_hour_mean" else "ok"),
        ("_try_load_lgbm","model.load",lambda v:"degraded" if v is None else "ok"),
        ("_freeze_observed_forecast_hours","publication.freeze",None),
        ("write_json","forecast.publish",None),
        ("_write_forecast_snapshot","snapshot.retain",skip_none),
        ("_write_forecast_origin_snapshot","origin.record",skip_none),
    ]:
        yield mod,name,op,classify
    for module, cls, name, op in [
        ("python.etl.fetch_today",None,"fetch_csv","source.fetch"),
        ("python.etl.fetch_weather",None,"enrich_cache_with_weather","weather.enrich"),
        ("python.etl.fetch_weather",None,"fetch_forecast_temps","weather.enrich"),
        ("python.etl.fetch_weather",None,"fetch_past_temps","weather.fetch"),
        ("python.etl.fetch_weather",None,"fetch_jma_official_forecast_temps","weather.fetch"),
        ("python.etl.fetch_weather",None,"fetch_jma_observed_temps","weather.fetch"),
        ("python.etl.fetch_weather",None,"_fetch_open_meteo_archive_temps","weather.fetch"),
        ("python.etl.fetch_weather",None,"_fetch_open_meteo_jma_forecast_temps","weather.fetch"),
        ("python.forecast.feature_builder",None,"build_inference_features","features.build"),
        ("python.forecast.lgbm_model","LGBMForecaster","predict","model.predict"),
        ("python.forecast.same_regime_calibration","SameRegimeDayLevelCalibrator","apply","forecast.calibrate"),
        ("python.forecast.intraday_correction","IntradayResidualCorrector","apply","forecast.intraday"),
    ]:
        try:
            owner = import_module(module)
            label = (lambda frame:"degraded" if frame.empty else "ok") if op=="weather.fetch" else None
            yield (getattr(owner,cls) if cls else owner),name,op,label
        except Exception:
            # An optional hook must not disable the application's own fallback.
            continue


@contextmanager
def restore_boundary(rt, mod, enabled):
    """Observe the existing fetch/probe return codes without probing Git a second time."""
    if not enabled:
        yield
        return
    original = mod.subprocess
    class Commands:
        def __getattr__(self, key):
            return getattr(original, key)
        def run(self, args, *rest, **kwargs):
            prefix = args[:2]
            if prefix not in (["git", "fetch"], ["git", "ls-remote"]):
                return original.run(args, *rest, **kwargs)
            op = "restore.fetch" if prefix[1]=="fetch" else "restore.probe"
            with rt.stage(op) as status:
                value = original.run(args, *rest, **kwargs)
                if value.returncode:
                    status.outcome = "skipped" if op=="restore.probe" and value.returncode==2 else "degraded"
                return value
    try:
        mod.subprocess = Commands()
        yield
    finally:
        mod.subprocess = original


COMMANDS = {
    "restore": ("scripts.restore_public_from_data_branch","data.restore"),
    "batch": ("python.etl.run_batch","etl.batch"),
    "fetch": ("python.etl.fetch_tepco","etl.fetch"),
    "validate": ("scripts.validate_public_before_publish","publish.validate"),
    "publish": ("scripts.publish_data_branch","publish.request"),
    "dispatch": ("scripts.trigger_deploy_workflow","workflow.dispatch"),
}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        raise SystemExit("Expected one of: " + ", ".join(COMMANDS))
    command = args.pop(0)
    module, op = COMMANDS[command]
    if command == "batch" and "--status-only" in args:
        op = "etl.intraday"
    rt = Runtime("tgems-etl" if command in ("batch","fetch") else "tgems-host")
    old = sys.argv
    try:
        sys.argv = [module,*args]
        with rt.stage(op) as status:
            mod = import_module(module)
            with restore_boundary(rt, mod, command=="restore" and rt.tracer is not None), bindings(rt, entries(command,mod) if rt.tracer else ()):
                result = mod.main()
                if isinstance(result, int) and result != 0:
                    status.outcome = "failed"
                return result
    finally:
        sys.argv = old
        rt.close()


if __name__ == "__main__":
    sys.exit(main())
