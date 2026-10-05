"""Disposable PG17/SeaweedFS cold restore and archived-WAL acceptance. Never production."""

import asyncio
import hashlib
import io
import json
import os
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
PG = Path(os.environ["PG_BIN"]).resolve()
WEED = Path(os.environ["WEED_BIN"]).resolve()
PYTHON = sys.executable


def run(argv, **kwargs):
    return (
        subprocess.run(
            [str(x) for x in argv],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            **kwargs,
        )
        .stdout.decode()
        .strip()
    )


def wait_port(port):
    for _ in range(90):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError("Isolated storage startup timeout")


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nd-restore-", dir="/tmp") as temporary:
        base = Path(temporary)
        os.chmod(base, 0o700)
        data, sock, wal, audit, cold = [
            base / x for x in ("pg", "sock", "wal", "audit", "seaweed")
        ]
        for path in (sock, wal, audit, cold):
            path.mkdir(mode=0o700)
        auditfile = audit / "audit.json"
        os.environ["NAMBADRIVE_AUDIT_LOG_PATH"] = str(auditfile)
        os.environ["NAMBADRIVE_DATABASE_URL"] = (
            f"postgresql+asyncpg://{os.getlogin() if os.environ.get('ND_USE_LOGIN') else __import__('getpass').getuser()}@/restore_ci?host={sock}&port=15433"
        )
        os.environ["NAMBADRIVE_S3_ENDPOINT"] = "http://127.0.0.1:18334"
        access, secret = secrets.token_hex(16), secrets.token_hex(32)
        os.environ["NAMBADRIVE_S3_ACCESS_KEY"] = access
        os.environ["NAMBADRIVE_S3_SECRET_KEY"] = secret
        config = base / "s3.json"
        config.write_text(
            json.dumps(
                {
                    "identities": [
                        {
                            "name": "restore-test",
                            "credentials": [{"accessKey": access, "secretKey": secret}],
                            "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                        }
                    ]
                }
            )
        )
        config.chmod(0o600)
        keyfile = base / "key"
        keyfile.write_bytes(secrets.token_bytes(32))
        keyfile.chmod(0o600)
        from app.backup.repository import build, publish, restore, key_file
        from app.backup.cli import command
        from app.core.config import get_settings
        from app.storage.seaweed import create_storage, Area, ObjectKey
        from app.models.user import User
        from app.models.organization import Company, Department
        from app.models.resource import Resource
        from app.models.document import DocumentVersion
        from app.models.quota import StorageReservation
        from app.core.database import SessionLocal, engine
        from app.authorization.service import AuthorizationService
        from sqlalchemy import text

        pg_running = False
        weed = None
        restored_pg = None

        def start_weed(directory):
            log = (base / ("weed-" + uuid.uuid4().hex + ".log")).open("wb")
            process = subprocess.Popen(
                [
                    str(WEED),
                    "server",
                    f"-dir={directory}",
                    "-ip=127.0.0.1",
                    "-ip.bind=127.0.0.1",
                    "-master.port=19334",
                    "-master.port.grpc=29334",
                    "-volume.port=18081",
                    "-volume.port.grpc=28081",
                    "-filer",
                    "-filer.port=18889",
                    "-filer.port.grpc=28889",
                    "-s3",
                    "-s3.port=18334",
                    "-s3.port.grpc=28334",
                    "-s3.port.iceberg=0",
                    "-s3.port.lance=0",
                    f"-s3.config={config}",
                    "-master.telemetry=false",
                    "-master.volumeSizeLimitMB=32",
                    "-volume.max=32",
                ],
                cwd=directory,
                stdout=log,
                stderr=log,
            )
            log.close()
            wait_port(18334)
            return process

        def stop_weed(process):
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

        def sql(statement, directory=sock, port=15433):
            return run(
                [
                    PG / "psql",
                    "-h",
                    directory,
                    "-p",
                    str(port),
                    "-d",
                    "restore_ci",
                    "-X",
                    "-A",
                    "-t",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    statement,
                ]
            )

        try:
            assert "17." in run([PG / "postgres", "--version"])
            run(
                [
                    PG / "initdb",
                    "-D",
                    data,
                    "--auth=trust",
                    "--no-locale",
                    "--encoding=UTF8",
                ]
            )
            # Private Unix socket only. No production service is touched.
            hook = f"{PYTHON} {ROOT}/backend/app/backup/wal.py %p %f {wal}"
            with (data / "postgresql.conf").open("a") as output:
                output.write(
                    f"\nlisten_addresses=''\nport=15433\nunix_socket_directories='{sock}'\narchive_mode=on\narchive_command='{hook}'\n"
                )
            run([PG / "pg_ctl", "-D", data, "-l", base / "postgres.log", "-w", "start"])
            pg_running = True
            run([PG / "createdb", "-h", sock, "-p", "15433", "restore_ci"])
            run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend")
            weed = start_weed(cold)
            storage = create_storage(get_settings())
            for bucket in storage.buckets.values():
                for attempt in range(60):
                    try:
                        storage.client.create_bucket(Bucket=bucket)
                        break
                    except Exception:
                        if attempt == 59:
                            raise
                        time.sleep(1)
            owner, outsider, company, department, space = [
                uuid.uuid4() for _ in range(5)
            ]
            documents = [uuid.uuid4(), uuid.uuid4()]
            versions = [uuid.uuid4(), uuid.uuid4()]
            payloads = [
                b"immutable clean restored bytes" * 8192,
                b"quarantine must stay quarantined",
            ]
            for index in range(2):
                storage.put(
                    ObjectKey(space, documents[index], versions[index]),
                    io.BytesIO(payloads[index]),
                    Area.DATA if index == 0 else Area.QUARANTINE,
                )

            async def seed():
                async with SessionLocal() as db:
                    db.add_all(
                        [
                            User(
                                id=owner,
                                authentik_sub="restore-owner",
                                username="owner",
                                display_name="Owner",
                            ),
                            User(
                                id=outsider,
                                authentik_sub="restore-outsider",
                                username="outsider",
                                display_name="Outsider",
                            ),
                            Company(id=company, name="Restore fixture"),
                        ]
                    )
                    await db.flush()
                    db.add(
                        Department(
                            id=department, company_id=company, name="Restore department"
                        )
                    )
                    await db.flush()
                    db.add(
                        Resource(
                            id=space,
                            resource_type="SPACE",
                            name="Private space",
                            owner_user_id=owner,
                            department_id=department,
                        )
                    )
                    await db.flush()
                    for i in range(2):
                        db.add(
                            Resource(
                                id=documents[i],
                                resource_type="DOCUMENT",
                                name=f"restored-{i}.txt",
                                parent_id=space,
                                owner_user_id=owner,
                                department_id=department,
                                legal_hold=True,
                                state="ACTIVE" if i == 0 else "QUARANTINED",
                                retention_until=datetime.now(UTC) + timedelta(days=365),
                            )
                        )
                    await db.flush()
                    for i in range(2):
                        db.add(
                            DocumentVersion(
                                id=versions[i],
                                document_id=documents[i],
                                space_id=space,
                                uploaded_by=owner,
                                filename=f"restored-{i}.txt",
                                mime_type="text/plain",
                                size=len(payloads[i]),
                                sha256=hashlib.sha256(payloads[i]).hexdigest(),
                                status="CLEAN" if i == 0 else "PENDING",
                                is_current=i == 0,
                                retention_until=datetime.now(UTC) + timedelta(days=365),
                            )
                        )
                    db.add(
                        StorageReservation(
                            version_id=uuid.uuid4(),
                            document_id=documents[0],
                            space_id=space,
                            owner_id=owner,
                            department_id=department,
                            size=1,
                            sha256=hashlib.sha256(b"x").hexdigest(),
                            area="quarantine",
                            policy_scope_ids=[str(space)],
                        )
                    )
                    await db.commit()
                await engine.dispose()

            asyncio.run(seed())
            sql("CREATE TABLE restore_wal_probe (value text PRIMARY KEY)")
            backup = base / "basebackup"
            command(
                [
                    str(PG / "pg_basebackup"),
                    f"--dbname=host={sock} port=15433 dbname=restore_ci",
                    f"--pgdata={backup}",
                    "--wal-method=stream",
                    "--checkpoint=fast",
                    "--manifest-checksums=SHA256",
                ]
            )
            command([str(PG / "pg_verifybackup"), str(backup)])
            # This transaction occurs AFTER basebackup; only archived-WAL recovery can return it.
            sql("INSERT INTO restore_wal_probe VALUES ('after-basebackup')")
            target_lsn = sql("SELECT pg_current_wal_lsn()")
            segment = sql("SELECT pg_walfile_name(pg_current_wal_lsn())")
            sql("SELECT pg_switch_wal()")
            for _ in range(90):
                if (wal / segment).is_file():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("WAL archive not acknowledged")
            stop_weed(weed)
            weed = None
            # Durable audit copied independently; application and storage writers are stopped.
            auditfile.write_text(
                '{"event":"restore_test_fixture","result":"success"}\n'
            )
            auditfile.chmod(0o600)
            staging, manifest = build(
                base / "repository",
                key_file(keyfile),
                {
                    "postgres": backup,
                    "wal": wal,
                    "audit": audit,
                    "seaweed_single": cold,
                },
                "AIO",
            )
            snapshot = publish(staging, manifest)
            servicefile = base / "pg_service.conf"
            servicefile.write_text(
                f"[backup_test]\nhost={sock}\nport=15433\ndbname=restore_ci\n"
            )
            servicefile.chmod(0o600)
            os.environ["PGSERVICEFILE"] = str(servicefile)
            created = json.loads(
                run(
                    [
                        PYTHON,
                        "-m",
                        "app.backup.cli",
                        "--key-file",
                        keyfile,
                        "create",
                        "--repository",
                        base / "cli-repository",
                        "--profile",
                        "AIO",
                        "--pg-service",
                        "backup_test",
                        "--pg-bin",
                        PG,
                        "--staging-parent",
                        base,
                        "--confirmed-quiesced",
                        "--source",
                        f"wal={wal}",
                        "--source",
                        f"audit={audit}",
                        "--source",
                        f"seaweed_single={cold}",
                    ],
                    cwd=ROOT / "backend",
                )
            )
            assert created["encrypted_files"] > 0
            run([PG / "pg_ctl", "-D", data, "-w", "stop", "-m", "fast"])
            pg_running = False
            recovery_started = time.monotonic()
            destination = base / "restored"
            run(
                [
                    PYTHON,
                    "-m",
                    "app.backup.cli",
                    "--key-file",
                    keyfile,
                    "restore-files",
                    "--snapshot",
                    snapshot,
                    "--destination",
                    destination,
                    "--pg-bin",
                    PG,
                ],
                cwd=ROOT / "backend",
            )
            restored_pg = destination / "postgres"
            command([str(PG / "pg_verifybackup"), str(restored_pg)])
            restored_sock = base / "restored-sock"
            restored_sock.mkdir(mode=0o700)
            # Isolated recovery cannot connect to a production archive or application.
            with (restored_pg / "postgresql.auto.conf").open("a") as output:
                output.write(
                    f"\nrestore_command='cp {destination}/wal/%f %p'\nrecovery_target_lsn='{target_lsn}'\nrecovery_target_action='promote'\n"
                )
            (restored_pg / "recovery.signal").touch()
            run(
                [
                    PG / "pg_ctl",
                    "-D",
                    restored_pg,
                    "-l",
                    base / "restored-pg.log",
                    "-w",
                    "start",
                    "-o",
                    f"-c listen_addresses='' -c port=15434 -c unix_socket_directories={restored_sock} -c archive_mode=off",
                ]
            )
            assert (
                sql("SELECT value FROM restore_wal_probe", restored_sock, 15434)
                == "after-basebackup"
            )
            assert (
                sql(
                    "SELECT count(*) FROM resources WHERE legal_hold",
                    restored_sock,
                    15434,
                )
                == "2"
            )
            assert (
                sql(
                    "SELECT count(*) FROM document_versions WHERE status='PENDING'",
                    restored_sock,
                    15434,
                )
                == "1"
            )
            assert (
                sql("SELECT count(*) FROM storage_reservations", restored_sock, 15434)
                == "1"
            )
            weed = start_weed(destination / "seaweed_single")
            os.environ["NAMBADRIVE_DATABASE_URL"] = (
                f"postgresql+asyncpg://{__import__('getpass').getuser()}@/restore_ci?host={restored_sock}&port=15434"
            )
            # Separate process guarantees settings/engine point only at the restored environment.
            result = json.loads(
                run(
                    [
                        PYTHON,
                        "-m",
                        "app.backup.cli",
                        "--key-file",
                        keyfile,
                        "verify-live",
                    ],
                    cwd=ROOT / "backend",
                )
            )
            assert result["verified_objects"] == 2
            assert result["verified_bytes"] == sum(map(len, payloads))
            assert result["optional_missing_objects"] == 2
            # Real authorization after recovery: ownership remains, outsider and held purge deny.
            from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

            async def authorize_restored():
                restored_engine = create_async_engine(
                    os.environ["NAMBADRIVE_DATABASE_URL"]
                )
                async with async_sessionmaker(restored_engine)() as db:
                    auth = AuthorizationService()
                    own, other = await db.get(User, owner), await db.get(User, outsider)
                    assert (await auth.authorize(db, own, "VIEW", documents[0])).allowed
                    assert not (
                        await auth.authorize(db, other, "VIEW", documents[0])
                    ).allowed
                    assert not (
                        await auth.authorize(db, own, "PURGE", documents[0])
                    ).allowed
                await restored_engine.dispose()

            asyncio.run(authorize_restored())
            print(
                json.dumps(
                    {
                        "phase": 20,
                        "postgres": "17",
                        "seaweed": "4.48",
                        "wal_replay": "passed",
                        "held_and_quarantined_metadata": "preserved",
                        "authorization": "passed",
                        **result,
                        "fixture_restore_seconds": round(
                            time.monotonic() - recovery_started, 3
                        ),
                        "total_seconds": round(time.monotonic() - started, 3),
                        "production_capacity_acceptance": "pending",
                    }
                )
            )
        except Exception:
            diagnostics = Path("/tmp/nambadrive-backup-diagnostics")
            diagnostics.mkdir(mode=0o700, exist_ok=True)
            for logfile in base.glob("*.log"):
                shutil.copyfile(logfile, diagnostics / logfile.name)
            raise
        finally:
            if weed is not None:
                stop_weed(weed)
            if restored_pg and (restored_pg / "postmaster.pid").exists():
                run([PG / "pg_ctl", "-D", restored_pg, "-w", "stop", "-m", "fast"])
            if pg_running:
                run([PG / "pg_ctl", "-D", data, "-w", "stop", "-m", "fast"])


if __name__ == "__main__":
    main()
