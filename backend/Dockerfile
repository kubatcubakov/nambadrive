FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system nambadrive \
    && useradd --system --gid nambadrive --create-home nambadrive \
    && mkdir -p /var/log/nambadrive \
    && chown -R nambadrive:nambadrive /var/log/nambadrive

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN pip install --no-cache-dir .

USER nambadrive

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
