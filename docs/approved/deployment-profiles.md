# Approved deployment profiles

All profiles use identical application code, database schema, API, ACL and object model.

## AIO
One application server + independent external backup. Intended DEV/TEST/pilot/small production where downtime risk is accepted. Suggested production-ish sizing ~16 vCPU, 48 GB RAM, 2 TB SSD/NVMe, external backup. Only 80/443 published; internal services not user-exposed.

## PROD-COMPACT — preferred initial production
- Node 1: App + ONLYOFFICE (Nginx, frontend, backend, worker, Redis, Tika, ClamAV, ONLYOFFICE, Wazuh agent)
- Node 2: PostgreSQL + OpenSearch + SeaweedFS Master #3
- Node 3: SeaweedFS storage01 + Master #1 + Filer/S3
- Node 4: SeaweedFS storage02 + Master #2
- independent backup target

## PROD-DISTRIBUTED
- App node
- Data node
- Office node
- Storage01
- Storage02
- independent backup

SeaweedFS production masters: 3 for quorum; two storage volume nodes. Cold backup is not the same thing as replication.

User network may only reach NambaDrive HTTPS and browser-required ONLYOFFICE HTTPS. DB/Redis/OpenSearch/Tika/ClamAV/SeaweedFS remain internal.

Backups: PostgreSQL pg_basebackup + WAL archive; daily 30 days, monthly 12 months. SeaweedFS independent cold backup. Restore test quarterly. Target RPO <=24h, RTO target <=4h validated by restore testing.
