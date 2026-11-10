"""Private non-global providers, no automatic instrumentation, bounded exit."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import secrets
from threading import Thread
import time

from .contract import OPERATIONS, OUTCOMES, SERVICES, error_kind, valid_parent
from .local_log import LocalLog

_active = ContextVar("tgems_span", default=None)


class Result:
    outcome = "ok"
    reason = "none"
    child_failure = False


class Runtime:
    def __init__(self, service, *, enabled=None):
        self.service = service = "tgems-fixture" if os.getenv("TGEMS_OTEL_FIXTURE")=="1" else service
        self.tracer = self.provider = self.log = self.context = None
        self.parent = None
        self.correlation = ""
        incoming = os.getenv("TGEMS_OTEL_CORRELATION", "")
        if len(incoming) == 16 and all(c in "0123456789abcdef" for c in incoming):
            self.correlation = incoming
        if enabled is None:
            enabled = os.getenv("TGEMS_OTEL_ENABLED") == "1"
        if not enabled or service not in SERVICES:
            return
        try:
            self.correlation = self.correlation or secrets.token_hex(8)
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
            from opentelemetry.sdk.trace.sampling import ALWAYS_ON
            resource, exporter = transport(service, "traces")
            self.provider = TracerProvider(resource=resource, shutdown_on_exit=False, sampler=ALWAYS_ON)
            self.provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=512,
                max_export_batch_size=64, schedule_delay_millis=250))
            self.tracer = self.provider.get_tracer("tgems.ops")
            self.context = trace.set_span_in_context
            value = os.getenv("TGEMS_TRACEPARENT", "")
            if valid_parent(value):
                self.parent = TraceContextTextMapPropagator().extract({"traceparent":value})
            self.log = LocalLog()
        except Exception:
            self.tracer = None

    @contextmanager
    def stage(self, name):
        result = Result()
        current = _active.get()
        span = token = None
        if self.tracer is not None and name in OPERATIONS:
            try:
                ctx = self.context(current[0]) if current else self.parent
                span = self.tracer.start_span(name, context=ctx)
                token = _active.set((span, result))
            except Exception:
                pass
        try:
            yield result
        except BaseException as exc:
            if not isinstance(exc, SystemExit) or exc.code not in (0, None):
                result.outcome, result.reason = "failed", error_kind(exc)
            raise
        finally:
            if token is not None:
                _active.reset(token)
            if result.child_failure and result.outcome != "failed":
                result.outcome = "degraded"
            if current and current[1].outcome=="ok" and (
                (name=="input.inventory" and result.outcome=="skipped") or
                (name=="restore.probe" and result.outcome=="skipped")
            ):
                current[1].outcome=result.outcome
            if current and result.outcome in ("failed","degraded"):
                current[1].child_failure = True
            if span is not None:
                try:
                    from opentelemetry.trace import Status, StatusCode
                    outcome = result.outcome if result.outcome in OUTCOMES else "unknown"
                    reason = result.reason if result.reason in ("none","execution","timeout","io","permission","invalid") else "execution"
                    span.set_attribute("outcome", outcome)
                    span.set_attribute("reason", reason)
                    if outcome == "failed":
                        span.set_status(Status(StatusCode.ERROR))
                    sc = span.get_span_context()
                    span.end()
                    if self.log:
                        self.log.put({"time":time.time(),"service":self.service,"stage":name,
                            "outcome":outcome,"reason":reason,"trace_id":format(sc.trace_id,"032x"),
                            "span_id":format(sc.span_id,"016x"),"correlation":self.correlation})
                except Exception:
                    pass

    def carrier(self):
        try:
            current = _active.get()
            if current:
                sc = current[0].get_span_context()
                return {"TGEMS_TRACEPARENT":f"00-{sc.trace_id:032x}-{sc.span_id:016x}-{int(sc.trace_flags):02x}",
                        "TGEMS_OTEL_CORRELATION":self.correlation}
        except Exception:
            pass
        return {}

    def close(self):
        def finish():
            try:
                if self.log:
                    self.log.done.set()
                if self.provider:
                    self.provider.force_flush(timeout_millis=500)
                    self.provider.shutdown()
                if self.log:
                    self.log.thread.join(.2)
            except Exception:
                pass
        if self.provider or self.log:
            try:
                worker = Thread(target=finish, daemon=True)
                worker.start()
                worker.join(.65)
            except Exception:
                pass


def transport(service, signal):
    from opentelemetry.sdk.resources import Resource
    from requests import Session
    if signal == "traces":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as Exporter
    else:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as Exporter
    endpoint = os.getenv("TGEMS_OTEL_ENDPOINT", "http://127.0.0.1:4318")
    if endpoint not in ("http://127.0.0.1:4318", "http://collector:4318", "http://host.docker.internal:4318"):
        raise ValueError("Only the dedicated local receiver is supported")
    class LocalSession(Session):
        def request(self, method, url, **kwargs):
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)
    session = LocalSession()
    session.trust_env = False
    exporter = Exporter(endpoint=f"{endpoint}/v1/{signal}", timeout=.4, session=session,
                        headers={"User-Agent":"tgems-observer"})
    return Resource({"service.name":service,"service.namespace":"tgems"}), exporter
