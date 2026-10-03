FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tokyo \
    HOME=/tmp \
    GIT_TERMINAL_PROMPT=0

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY docker/shadow-requirements.txt /app/shadow-requirements.txt
RUN pip install --no-cache-dir -r /app/shadow-requirements.txt \
    && groupadd --gid 10001 intradayshadow \
    && useradd --uid 10001 --gid 10001 --no-create-home intradayshadow \
    && mkdir -p /app/data/intraday_challenger \
    && chown 10001:10001 /app/data/intraday_challenger
COPY python/__init__.py /app/python/__init__.py
COPY python/eval/__init__.py /app/python/eval/__init__.py
COPY python/eval/intraday_challenger /app/python/eval/intraday_challenger
USER 10001:10001
CMD ["python", "-m", "python.eval.intraday_challenger.service", "run"]
