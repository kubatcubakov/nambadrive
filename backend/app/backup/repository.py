"""Operator-local encrypted cold backups. No application-user endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHUNK = 1024 * 1024
PROFILES = {
    "AIO": {"postgres", "wal", "audit", "seaweed_single"},
    "PROD-COMPACT": {
        "postgres",
        "wal",
        "audit",
        "seaweed_master01",
        "seaweed_master02",
        "seaweed_master03",
        "seaweed_volume01",
        "seaweed_volume02",
        "seaweed_filer",
    },
    "PROD-DISTRIBUTED": {
        "postgres",
        "wal",
        "audit",
        "seaweed_master01",
        "seaweed_master02",
        "seaweed_master03",
        "seaweed_volume01",
        "seaweed_volume02",
        "seaweed_filer",
    },
}


class BackupError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def purpose_key(key: bytes, purpose: bytes) -> bytes:
    return hmac.new(key, b"NambaDrive backup v1:" + purpose, hashlib.sha256).digest()


def key_file(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise BackupError("Private operator-owned key file required")
        key = handle.read(33)
    if len(key) != 32:
        raise BackupError("32-byte backup encryption key required")
    return key


def private_directory(path: Path, *, create: bool = False) -> None:
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise BackupError("Private operator-owned directory required")


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def regular_source(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise BackupError("Cold backup refuses nonregular sources and symbolic links")
    return info


def encrypt(source: Path, target: Path, key: bytes, aad: bytes) -> dict[str, Any]:
    before = regular_source(source)
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(purpose_key(key, b"encryption")), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(aad)
    digest, encrypted_digest, size = hashlib.sha256(), hashlib.sha256(), 0
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as incoming, target.open("xb") as outgoing:
        if os.fstat(incoming.fileno()).st_ino != before.st_ino:
            raise BackupError("Cold source changed before read")
        os.chmod(target, 0o600)
        while chunk := incoming.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            ciphertext = cipher.update(chunk)
            encrypted_digest.update(ciphertext)
            outgoing.write(ciphertext)
        tail = cipher.finalize()
        encrypted_digest.update(tail)
        outgoing.write(tail)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    after = regular_source(source)
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise BackupError("Source changed: stop all writers before cold backup")
    return {
        "size": size,
        "sha256": digest.hexdigest(),
        "cipher_sha256": encrypted_digest.hexdigest(),
        "nonce": nonce.hex(),
        "tag": cipher.tag.hex(),
    }


def build(
    repository: Path,
    key: bytes,
    sources: dict[str, Path],
    profile: str,
    *,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    if len(key) != 32 or profile not in PROFILES or not PROFILES[profile] <= sources.keys():
        raise BackupError("Complete approved profile sources and key required")
    if not all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in sources):
        raise BackupError("Invalid source name")
    private_directory(repository, create=True)
    snapshot = str(uuid.uuid4())
    staging = repository / (".incomplete-" + snapshot)
    staging.mkdir(mode=0o700)
    objects = staging / "objects"
    objects.mkdir(mode=0o700)
    manifest: dict[str, Any] = {
        "schema": 1,
        "id": snapshot,
        "profile": profile,
        "created_at": (now or datetime.now(UTC)).isoformat(),
        "sources": sorted(sources),
        "directories": sorted(sources),
        "files": [],
    }
    for name, root in sorted(sources.items()):
        if root.is_symlink() or not root.is_dir():
            raise BackupError("Cold source must be a directory")
        if repository.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(
            repository.resolve()
        ):
            raise BackupError("Repository and source must be separate")
        for source in sorted(root.rglob("*")):
            if source.is_symlink():
                raise BackupError("Symbolic links and external tablespaces are unsupported")
            if source.is_dir():
                manifest["directories"].append(name + "/" + source.relative_to(root).as_posix())
                continue
            relative = name + "/" + source.relative_to(root).as_posix()
            blob = f"{len(manifest['files']):08}.bin"
            details = encrypt(source, objects / blob, key, (snapshot + ":" + relative).encode())
            manifest["files"].append({"path": relative, "blob": blob, **details})
    if not any(f["path"] == "postgres/backup_manifest" for f in manifest["files"]):
        raise BackupError("Verified pg_basebackup manifest required")
    if not any(re.fullmatch(r"wal/[0-9A-F]{24}", f["path"]) for f in manifest["files"]):
        raise BackupError("Archived WAL segment required")
    fsync_directory(objects)
    manifest["hmac"] = hmac.new(
        purpose_key(key, b"manifest"), canonical(manifest), hashlib.sha256
    ).hexdigest()
    path = staging / "manifest.json"
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.write(canonical(manifest))
        output.flush()
        os.fsync(output.fileno())
    fsync_directory(staging)
    return staging, manifest


def publish(staging: Path, manifest: dict[str, Any]) -> Path:
    identifier = str(uuid.UUID(manifest["id"]))
    if staging.name != ".incomplete-" + identifier:
        raise BackupError("Invalid snapshot staging")
    target = staging.parent / identifier
    if target.exists():
        raise BackupError("Snapshot already exists")
    staging.rename(target)
    fsync_directory(target.parent)
    return target


def load(snapshot: Path, key: bytes) -> dict[str, Any]:
    private_directory(snapshot)
    path = snapshot / "manifest.json"
    regular_source(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise BackupError("Manifest too large")
    try:
        manifest = json.loads(path.read_bytes())
        supplied = manifest.pop("hmac")
        expected = hmac.new(
            purpose_key(key, b"manifest"), canonical(manifest), hashlib.sha256
        ).hexdigest()
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            raise BackupError("Backup authentication failed")
        if manifest["schema"] != 1 or str(uuid.UUID(manifest["id"])) != manifest["id"]:
            raise BackupError("Unsupported backup")
        if manifest["profile"] not in PROFILES or not PROFILES[manifest["profile"]] <= set(
            manifest["sources"]
        ):
            raise BackupError("Incomplete backup profile")
        seen: set[str] = set()
        for item in manifest["files"]:
            relative = PurePosixPath(item["path"])
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in item["path"]
                or item["path"] in seen
                or str(relative) != item["path"]
            ):
                raise BackupError("Invalid backup path")
            seen.add(item["path"])
            if not re.fullmatch(r"[0-9]{8}\.bin", item["blob"]):
                raise BackupError("Invalid backup object")
            if len(bytes.fromhex(item["nonce"])) != 12 or len(bytes.fromhex(item["tag"])) != 16:
                raise BackupError("Invalid encryption metadata")
        return manifest
    except (ValueError, KeyError, TypeError) as error:
        raise BackupError("Invalid backup manifest") from error


def restore(snapshot: Path, destination: Path, key: bytes) -> dict[str, Any]:
    manifest = load(snapshot, key)
    if destination.exists():
        raise BackupError("Restore requires a new isolated directory")
    destination.mkdir(parents=True, mode=0o700)
    for relative in manifest["directories"]:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or str(path) != relative or "\\" in relative:
            raise BackupError("Invalid backup directory")
        (destination / relative).mkdir(parents=True, mode=0o700, exist_ok=True)
    # A failed restore retains incomplete forensic bytes and never marks a usable result.
    for item in manifest["files"]:
        source = snapshot / "objects" / item["blob"]
        regular_source(source)
        output = destination / item["path"]
        output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        cipher = Cipher(
            algorithms.AES(purpose_key(key, b"encryption")),
            modes.GCM(bytes.fromhex(item["nonce"]), bytes.fromhex(item["tag"])),
        ).decryptor()
        cipher.authenticate_additional_data((manifest["id"] + ":" + item["path"]).encode())
        digest, encrypted_digest, size = hashlib.sha256(), hashlib.sha256(), 0
        temporary = output.with_name(output.name + ".unverified")
        try:
            with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                os.chmod(temporary, 0o600)
                while chunk := incoming.read(CHUNK):
                    encrypted_digest.update(chunk)
                    plaintext = cipher.update(chunk)
                    digest.update(plaintext)
                    size += len(plaintext)
                    outgoing.write(plaintext)
                tail = cipher.finalize()
                digest.update(tail)
                size += len(tail)
                outgoing.write(tail)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        except InvalidTag as error:
            raise BackupError("Encrypted backup integrity failure") from error
        if (
            size != item["size"]
            or digest.hexdigest() != item["sha256"]
            or encrypted_digest.hexdigest() != item["cipher_sha256"]
        ):
            raise BackupError("Restored backup checksum failure")
        temporary.rename(output)
        fsync_directory(output.parent)
    marker = destination / "FILES_VERIFIED.json"
    marker.write_bytes(
        canonical(
            {
                "snapshot_id": manifest["id"],
                "files": len(manifest["files"]),
                "note": "Filesystem integrity only: database/S3 acceptance still required",
            }
        )
    )
    os.chmod(marker, 0o600)
    with marker.open("rb") as handle:
        os.fsync(handle.fileno())
    fsync_directory(destination)
    return manifest


def retention_plan(snapshots: list[dict[str, Any]], now: datetime) -> set[str]:
    """Keep last 30 days plus earliest successful full backup in each of last 12 months."""
    from datetime import timedelta

    monthly: dict[tuple[int, int], tuple[datetime, str]] = {}
    keep: set[str] = set()
    current_month = now.year * 12 + now.month - 1
    for snapshot in snapshots:
        date = datetime.fromisoformat(snapshot["created_at"])
        if date.tzinfo is None or date > now:
            raise BackupError("Invalid backup time")
        if date >= now - timedelta(days=30):
            keep.add(snapshot["id"])
        month = date.year * 12 + date.month - 1
        if current_month - 11 <= month <= current_month:
            key = (date.year, date.month)
            candidate = (date, snapshot["id"])
            if key not in monthly or candidate < monthly[key]:
                monthly[key] = candidate
    keep.update(value[1] for value in monthly.values())
    return keep
