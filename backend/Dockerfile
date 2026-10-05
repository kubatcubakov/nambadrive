FROM python:3.13-slim@sha256:3dd7cc108ec1493442514f5c2a871af6af0ec31d768ff6e378a93340c3b3db5f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 nambadrive \
    && useradd --system --uid 10001 --gid nambadrive --create-home nambadrive \
    && mkdir -p /var/log/nambadrive \
    && chown -R nambadrive:nambadrive /var/log/nambadrive

WORKDIR /app

COPY pyproject.toml requirements.lock ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .

USER nambadrive

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "172.29.0.2,172.29.0.4"]
