FROM onlyoffice/documentserver:9.3.1.2@sha256:290a0a1406a485acc8a6bc20418ac7158c5eec78b4844c218f8f975a9800ddbc
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
COPY harden.py /opt/nambadrive/harden.py
COPY entrypoint.py /opt/nambadrive/entrypoint.py
RUN python3 /opt/nambadrive/harden.py
ENTRYPOINT ["python3", "/opt/nambadrive/entrypoint.py"]
