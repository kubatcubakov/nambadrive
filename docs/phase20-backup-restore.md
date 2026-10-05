# Phase 20 — encrypted independent backup and isolated restore

The operator-local `python -m app.backup.cli` tool creates complete cold bundles for AIO, PROD-COMPACT and PROD-DISTRIBUTED. It has no HTTP route or application role grant. Possession of the private OS-owned 32-byte backup key and infrastructure access are required; a System Administrator application account does not gain document access. Restore verification reads bytes only for SHA-256 checking and never outputs content.

Each file is encrypted with AES-256-GCM, a random nonce and authenticated snapshot/path binding. Encryption and manifest authentication use distinct purpose-derived keys. The manifest has HMAC-SHA256, plaintext and ciphertext SHA-256, sizes, source names and empty directory records. A complete profile includes PostgreSQL, archived WAL, durable audit and every SeaweedFS metadata/volume directory. Production profiles require all three masters, both volume nodes and filer metadata. UUID publication is atomic only after fsync and durable audit; incomplete bundles remain unpublished. Symlinks/external PostgreSQL tablespaces, source/repository overlap, weak key permissions, altered sources, malformed paths and missing required sources fail closed.

The WAL hook `backend/app/backup/wal.py` acknowledges only a durable complete segment. It refuses different-content overwrites, including concurrent retries, and fsyncs identical existing files before acknowledging them. Its destination must be an independent encrypted backup mount, with a distinct directory per PostgreSQL cluster. WAL contains sensitive metadata. The cold bundle encrypts these segments again.

No schema change is needed: the backup preserves the identical current schema and immutable object layout. It includes quarantine, historical retained/held versions, trash, reservations, ACL, users, sessions and durable audit. Search indexes are rebuildable and do not replace the authoritative database/object backup. ClamAV definitions and program images are rebuilt from pinned deployment inputs.

## Daily backup runbook

1. Configure an independent encrypted backup target; keep its encryption key in a separate restricted vault and escrow recovery access. Use a private encrypted staging volume large enough for a complete `pg_basebackup`. Never place backups on the only live storage disk. Restrict backup files to the infrastructure operator. Validate mount identity/free space before writing.
2. Enable PostgreSQL 17 `wal_level=replica`, `archive_mode=on`, `archive_timeout=300s` and `archive_command='/usr/bin/python3 /opt/nambadrive/wal.py %p %f /mnt/independent-wal/cluster-id'`. Install the supplied stdlib-only hook on the DB host. Check `pg_stat_archiver`, archive lag and independent target availability; alert on any failure. Maintain contiguous WAL from the oldest retained base backup. No automatic WAL deletion is supplied.
3. Schedule a daily maintenance window through the infrastructure scheduler. Block new traffic, stop backend and every mutating worker, drain ONLYOFFICE callbacks/saves, stop the office service and all SeaweedFS writers. Stop SeaweedFS components in gateway/filer/volume/master order and verify they are stopped on every host. PostgreSQL remains running for the base backup. Do not mistake replication for an independent backup. The `--confirmed-quiesced` flag is an operator attestation, not an automatic distributed lock.
4. Mount read-only cold copies of every stopped SeaweedFS directory on the backup host. Preserve master raft state, volume data/index files and the entire filer metadata database. Include the audit directory. Create a restricted `PGSERVICEFILE` with an authenticated TLS PostgreSQL service; do not put passwords on argv. The tools use allowlisted absolute `pg_basebackup`/`pg_verifybackup` executables.
5. Run from the backend environment (paths below are deployment placeholders, never application defaults):

```bash
python -m app.backup.cli --key-file /vault/nambadrive-backup.key create \
  --profile AIO --repository /mnt/independent-backups/nambadrive \
  --pg-service nambadrive_backup --pg-bin /usr/lib/postgresql/17/bin \
  --staging-parent /mnt/encrypted-staging --confirmed-quiesced \
  --source wal=/mnt/independent-wal/cluster-id \
  --source audit=/mnt/cold/audit --source seaweed_single=/mnt/cold/seaweed
```

For production replace `seaweed_single` with all six `seaweed_master01`, `seaweed_master02`, `seaweed_master03`, `seaweed_volume01`, `seaweed_volume02`, `seaweed_filer` source arguments. Separately preserve sealed deployment secrets/configuration and certificates in the infrastructure vault; they are needed to restore service identities and are never logged by this tool. The repository must not be writable by application service accounts.

6. A nonzero result or `.incomplete-*` directory is a failed backup: alert, preserve diagnostics privately, repair and rerun. Resume services only after a complete published snapshot and verified health. Record backup timestamp, archive lag, snapshot ID, bytes, duration and target identity. Alert if the last successful complete backup is older than 24 hours.
7. Run `retention-plan --repository ...` with the private key. It retains every daily backup from the last 30 days plus one full backup in each of the last 12 calendar months. The result contains review candidates, never deletion instructions. Longer approved document retention/Legal Hold and required WAL dependencies must be reviewed before any infrastructure deletion. Application cleanup cannot erase backups. Unresolved holds retain the affected backup; do not prune to an arbitrary disk budget.

## Quarterly restore runbook

1. Restore into a new isolated encrypted directory/network. Block all outbound delivery, Authentik provisioning, cleanup, callbacks and user traffic. Do not restore over production. Recover the separately escrowed key and required service secrets. Verify executable versions and storage layout.
2. Run `python -m app.backup.cli --key-file ... restore-files --snapshot ... --destination ... --pg-bin ...`. Every GCM tag, size and SHA-256 and `pg_verifybackup` must pass. `FILES_VERIFIED.json` means filesystem integrity only, not acceptance. A partial directory is never a pass.
3. Configure PostgreSQL recovery on the isolated host using `recovery.signal`, a restore command pointing only at this snapshot's WAL directory and a chosen recovery target. Override restored socket/listen/archive settings so recovery cannot touch original infrastructure. Recover no later than the matching cold storage checkpoint: later WAL can reference objects absent from the cold copy. Verify replay/promotion and the expected migration head.
4. Start isolated SeaweedFS using the restored master/filer/volume paths and private service credentials. Configure backend DB/S3 endpoints only for this isolated environment. Run `verify-live`: every required unpurged version must match its full SHA-256 and size. Optional clean quarantine duplicates and unmatched write-ahead reservations can legitimately be absent; their counts are reported and journals remain intact. Investigate all unresolved purge intents before acceptance; never waive a missing retained/held object.
5. Validate users, organization, ACL positive/negative cases, disabled identities, version history, quarantine/AV promotion boundaries, trash, quotas, retention and Legal Hold. Rebuild OpenSearch from restored active clean versions through the normal backend worker, preserving ACL filtering. Record the chosen data checkpoint, observed lost interval/RPO and elapsed full recovery/RTO, including rebuild and user readiness.
6. Revoke restored application/editor sessions and OIDC transactions before any approved user cutover; do not enable mail/Telegram, cleanup or provisioning until identity/hold reconciliation passes. Production cutover requires separate explicit approval. Keep the original environment intact until the accepted cutover plan says otherwise.

Target RPO <=24h and RTO <=4h must be measured on representative hardware/data, including versions/replication/trash/retention overhead. A small CI fixture does not establish a 500 GB production RTO.

## Validation

Local PostgreSQL **17.11** and SeaweedFS **4.48**: encrypted base backup, independent cold storage, archive replay of a transaction committed **after** base backup, isolated restore, full SHA-256 checking of DATA and QUARANTINE, held/retained metadata and unmatched reservation preservation, owner allow/outsider deny/held purge deny. Fixture: 245,792 logical object bytes, 24.333 seconds for file/DB/storage/auth recovery, 50.668 seconds for the full test. CLI create, restore-files and verify-live are exercised against actual services. The all-in-one test also exercises storage restart recovery after writers are stopped; production uses ordered component shutdown.

Ten unit cases cover encryption roundtrip, empty directories, corrupt ciphertext/manifest, incorrect key, missing source/WAL, symlink/permissions, retention planning, executable trust durable conflict-safe WAL archival and audit failure preventing publication. Full local regression suite: **551 passed, 17 runtime-only skipped**, authorization **95.88%**. PostgreSQL migration roundtrip and 528 regression tests passed, authorization coverage 94.48%. CI results are recorded in CURRENT_STATE once green. The `backup-restore` CI job repeats the actual Linux engines rather than relying on generated SQL or SQLite.

Sources: [PostgreSQL 17 continuous archiving/recovery](https://www.postgresql.org/docs/17/continuous-archiving.html), [official PGDG Ubuntu packages](https://www.postgresql.org/download/linux/ubuntu/). Daily scheduling, independent encrypted mounts, external vault and representative production RPO/RTO remain infrastructure acceptance requirements; no production backup/deployment was executed from this coding session.
