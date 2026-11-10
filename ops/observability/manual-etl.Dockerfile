# Build locally, FROM the existing ETL image; do not rebuild forecast dependencies.
ARG ETL_BASE=tokyogridems-etl:latest
FROM ${ETL_BASE}
COPY ops/observability/requirements.txt /tmp/tgems-otel.txt
RUN python -m pip install --no-cache-dir --target /opt/tgems-observer -r /tmp/tgems-otel.txt \
    && python -c "import pathlib,site; (pathlib.Path(site.getsitepackages()[0])/'tgems-observer.pth').write_text('/opt/tgems-observer\n')" \
    && python -c "from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter"
