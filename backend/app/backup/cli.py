"""Local infrastructure operator commands. No HTTP access or implicit user role grant."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import stat

# Operator-local allowlisted PG tools; no HTTP entrypoint.
import subprocess  # nosec B404
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.backup.repository import (
    BackupError,
    build,
    key_file,
    load,
    publish,
    restore,
    retention_plan,
)
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.models.document import DocumentVersion
from app.models.quota import StorageReservation
from app.storage.seaweed import Area, ObjectKey, ObjectMissing, create_storage


def command(argv: list[str]) -> None:
    requested = Path(argv[0])
    if not requested.is_absolute() or requested.name not in {"pg_basebackup", "pg_verifybackup"}:
        raise BackupError("Allowlisted absolute PostgreSQL executable required")
    executable = requested.resolve(strict=True)
    info = executable.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid not in {0, os.geteuid()}
        or info.st_mode & 0o022
    ):
        raise BackupError("Trusted non-writable PostgreSQL executable required")
    argv = [str(executable), *argv[1:]]
    # Owner/mode/name checked above; argv vector, never a shell.
    result = subprocess.run(  # nosec B603
        argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4 * 60 * 60, check=False
    )
    if result.returncode:
        raise BackupError("PostgreSQL backup/verification command failed")


async def event(name: str, **fields: object) -> None:
    await write_audit_event(name, user="local_backup_operator", result="success", **fields)


def verify_object(
    storage, key: ObjectKey, area: Area, expected_size: int, expected_hash: str
) -> int:
    import hashlib

    digest, count = hashlib.sha256(), 0
    for chunk in storage.read(key, area):
        count += len(chunk)
        if count > expected_size:
            raise BackupError("Restored object size mismatch")
        digest.update(chunk)
    if count != expected_size or digest.hexdigest() != expected_hash:
        raise BackupError("Restored object SHA-256 mismatch")
    return count


async def verify_storage() -> dict[str, int]:
    """Read-only integrity verification; never returns content or deletes objects."""
    storage = create_storage(get_settings())
    verified, size, optional_missing = 0, 0, 0
    async with SessionLocal() as db:
        versions = (
            await db.scalars(select(DocumentVersion).where(DocumentVersion.purged_at.is_(None)))
        ).all()
        reservations = (
            await db.scalars(
                select(StorageReservation).where(
                    ~select(DocumentVersion.id)
                    .where(DocumentVersion.id == StorageReservation.version_id)
                    .exists()
                )
            )
        ).all()
        candidates = []
        for version in versions:
            key = ObjectKey(version.space_id, version.document_id, version.id)
            candidates.append(
                (
                    key,
                    Area.DATA if version.status == "CLEAN" else Area.QUARANTINE,
                    version.size,
                    version.sha256,
                    version.purge_started_at is not None,
                )
            )
            # Clean quarantine duplicates may have been removed before a failed metadata commit.
            if version.status == "CLEAN" and version.quarantine_purged_at is None:
                candidates.append((key, Area.QUARANTINE, version.size, version.sha256, True))
        for reservation in reservations:
            candidates.append(
                (
                    ObjectKey(
                        reservation.space_id, reservation.document_id, reservation.version_id
                    ),
                    Area(reservation.area),
                    reservation.size,
                    reservation.sha256,
                    True,
                )
            )
        for key, area, expected_size, expected_hash, optional in candidates:
            try:
                count = await run_in_threadpool(
                    verify_object, storage, key, area, expected_size, expected_hash
                )
            except ObjectMissing:
                if not optional:
                    raise BackupError("Required restored object missing") from None
                optional_missing += 1
                continue
            verified += 1
            size += count
    await event(
        "restore_verified",
        verified_objects=verified,
        verified_bytes=size,
        optional_missing_objects=optional_missing,
    )
    return {
        "verified_objects": verified,
        "verified_bytes": size,
        "optional_missing_objects": optional_missing,
    }


async def execute(args: argparse.Namespace) -> None:
    # Possession of the private OS-owned backup key is required for every operator command.
    key = key_file(args.key_file)
    started = time.monotonic()
    if args.action == "create":
        if not args.confirmed_quiesced or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.pg_service):
            raise BackupError("Stop all application/storage writers and confirm quiescence")
        sources = {}
        for value in args.source:
            name, separator, path = value.partition("=")
            if not separator or name in sources or name == "postgres":
                raise BackupError("Unique name=absolute-cold-directory sources required")
            root = Path(path)
            if not root.is_absolute():
                raise BackupError("Absolute cold source directory required")
            sources[name] = root
        with tempfile.TemporaryDirectory(
            prefix="nambadrive-basebackup-", dir=args.staging_parent
        ) as temporary:
            os.chmod(temporary, 0o700)
            postgres = Path(temporary) / "postgres"
            command(
                [
                    str(args.pg_bin / "pg_basebackup"),
                    "--dbname=service=" + args.pg_service,
                    "--pgdata=" + str(postgres),
                    "--wal-method=stream",
                    "--checkpoint=fast",
                    "--manifest-checksums=SHA256",
                ]
            )
            command([str(args.pg_bin / "pg_verifybackup"), str(postgres)])
            sources["postgres"] = postgres
            staging, manifest = build(args.repository, key, sources, args.profile)
            await event(
                "backup_created",
                snapshot_id=manifest["id"],
                profile=args.profile,
                encrypted_files=len(manifest["files"]),
                operation="publish_intent",
            )
            target = publish(staging, manifest)
            print(
                json.dumps(
                    {
                        "snapshot_id": target.name,
                        "encrypted_files": len(manifest["files"]),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }
                )
            )
    elif args.action == "restore-files":
        manifest = restore(args.snapshot, args.destination, key)
        command([str(args.pg_bin / "pg_verifybackup"), str(args.destination / "postgres")])
        await event(
            "restore_files_verified", snapshot_id=manifest["id"], files=len(manifest["files"])
        )
        print(
            json.dumps(
                {
                    "snapshot_id": manifest["id"],
                    "files_verified": len(manifest["files"]),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "live_database_storage_validation_required": True,
                }
            )
        )
    elif args.action == "verify-live":
        print(
            json.dumps(
                {**await verify_storage(), "elapsed_seconds": round(time.monotonic() - started, 3)}
            )
        )
    elif args.action == "retention-plan":
        snapshots = []
        for path in args.repository.iterdir():
            if re.fullmatch(r"[a-f0-9-]{36}", path.name):
                snapshots.append(load(path, key))
        keep = retention_plan(snapshots, datetime.now(UTC))
        print(
            json.dumps(
                {
                    "keep": sorted(keep),
                    "review_candidates": sorted(s["id"] for s in snapshots if s["id"] not in keep),
                    "automatic_delete": False,
                    "legal_hold_retention_review_required": True,
                }
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("--repository", type=Path, required=True)
    create.add_argument(
        "--profile", choices=["AIO", "PROD-COMPACT", "PROD-DISTRIBUTED"], required=True
    )
    create.add_argument("--pg-service", required=True)
    create.add_argument("--pg-bin", type=Path, required=True)
    create.add_argument("--source", action="append", default=[])
    create.add_argument("--staging-parent", type=Path, required=True)
    create.add_argument("--confirmed-quiesced", action="store_true")
    recover = sub.add_parser("restore-files")
    recover.add_argument("--snapshot", type=Path, required=True)
    recover.add_argument("--destination", type=Path, required=True)
    recover.add_argument("--pg-bin", type=Path, required=True)
    sub.add_parser("verify-live")
    retention = sub.add_parser("retention-plan")
    retention.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()

    async def run() -> None:
        try:
            await execute(args)
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except Exception as error:
        # No DB connection strings, secrets, provider responses or document bytes in CLI logs.
        parser.exit(
            1,
            "Backup/restore failed ("
            + type(error).__name__
            + "); inspect private infrastructure diagnostics.\n",
        )


if __name__ == "__main__":
    main()
