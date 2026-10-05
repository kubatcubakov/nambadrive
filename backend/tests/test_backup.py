import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.backup.repository import (
    BackupError,
    build,
    key_file,
    load,
    publish,
    restore,
    retention_plan,
)


@pytest.fixture
def sources(tmp_path):
    roots = {name: tmp_path / name for name in ["postgres", "wal", "audit", "seaweed_single"]}
    for root in roots.values():
        root.mkdir(mode=0o700)
    (roots["postgres"] / "backup_manifest").write_text("unit-fixture manifest")
    (roots["postgres"] / "empty-directory").mkdir()
    (roots["wal"] / ("A" * 24)).write_bytes(b"wal")
    (roots["audit"] / "audit.jsonl").write_text('{"event":"legal_hold_enabled"}\n')
    (roots["seaweed_single"] / "volume.dat").write_bytes(os.urandom(2 * 1024 * 1024 + 3))
    return roots


def bundle(tmp_path, sources):
    key = os.urandom(32)
    staging, manifest = build(tmp_path / "repository", key, sources, "AIO")
    return publish(staging, manifest), key


def test_encrypted_bundle_roundtrip_preserves_empty_dirs_and_is_authenticated(tmp_path, sources):
    snapshot, key = bundle(tmp_path, sources)
    manifest = load(snapshot, key)
    assert manifest["profile"] == "AIO"
    raw = (sources["seaweed_single"] / "volume.dat").read_bytes()
    assert all(raw not in p.read_bytes() for p in (snapshot / "objects").iterdir())
    target = tmp_path / "restore"
    restore(snapshot, target, key)
    assert (target / "seaweed_single" / "volume.dat").read_bytes() == raw
    assert (target / "postgres" / "empty-directory").is_dir()
    assert (target / "FILES_VERIFIED.json").exists()
    assert (target / "seaweed_single" / "volume.dat").stat().st_mode & 0o077 == 0
    with pytest.raises(BackupError):
        restore(snapshot, target, key)


@pytest.mark.parametrize("attack", ["manifest", "cipher", "wrong-key"])
def test_corrupt_backup_never_restores_success_marker(tmp_path, sources, attack):
    snapshot, key = bundle(tmp_path, sources)
    if attack == "manifest":
        path = snapshot / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"][0]["path"] = "../../escape"
        path.write_text(json.dumps(manifest))
    elif attack == "cipher":
        path = next((snapshot / "objects").iterdir())
        data = bytearray(path.read_bytes())
        data[0] ^= 1
        path.write_bytes(data)
    else:
        key = os.urandom(32)
    target = tmp_path / "restore"
    with pytest.raises(BackupError):
        restore(snapshot, target, key)
    assert not (target / "FILES_VERIFIED.json").exists()
    assert not (tmp_path / "escape").exists()


def test_missing_sources_wal_and_symlinks_fail_closed(tmp_path, sources):
    key = os.urandom(32)
    with pytest.raises(BackupError):
        build(tmp_path / "repository", key, sources, "PROD-COMPACT")
    (sources["seaweed_single"] / "link").symlink_to(sources["audit"] / "audit.jsonl")
    with pytest.raises(BackupError):
        build(tmp_path / "repository", key, sources, "AIO")
    (sources["seaweed_single"] / "link").unlink()
    (sources["wal"] / ("A" * 24)).unlink()
    with pytest.raises(BackupError):
        build(tmp_path / "repository", key, sources, "AIO")
    assert not any(
        not p.name.startswith(".incomplete-") for p in (tmp_path / "repository").iterdir()
    )


def test_operator_key_permissions_length_and_symlink(tmp_path):
    path = tmp_path / "key"
    path.write_bytes(os.urandom(32))
    path.chmod(0o600)
    assert len(key_file(path)) == 32
    path.chmod(0o644)
    with pytest.raises(BackupError):
        key_file(path)
    path.chmod(0o600)
    path.write_bytes(b"short")
    with pytest.raises(BackupError):
        key_file(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        key_file(link)


def test_backup_retention_minimum_30_days_and_12_calendar_months():
    now = datetime(2026, 10, 5, tzinfo=UTC)
    snapshots = [
        {"id": str(day), "created_at": (now - timedelta(days=day)).isoformat()}
        for day in range(500)
    ]
    keep = retention_plan(snapshots, now)
    assert all(str(day) in keep for day in range(31))
    dates = [datetime.fromisoformat(s["created_at"]) for s in snapshots if s["id"] in keep]
    assert len({(d.year, d.month) for d in dates}) == 12
    assert "499" not in keep
    with pytest.raises(BackupError):
        retention_plan([{"id": "future", "created_at": (now + timedelta(days=1)).isoformat()}], now)


def test_postgres_tools_reject_untrusted_executables(tmp_path):
    from app.backup.cli import command

    for value in ["pg_basebackup", "/bin/sh", "/bin/echo"]:
        with pytest.raises(BackupError):
            command([value])
    candidate = tmp_path / "pg_basebackup"
    candidate.write_text("#!/bin/sh\nexit 0\n")
    candidate.chmod(0o777)
    with pytest.raises(BackupError):
        command([str(candidate)])


def test_wal_archive_is_durable_idempotent_and_never_overwrites(tmp_path):
    from app.backup.wal import archive

    source = tmp_path / "source"
    source.write_bytes(os.urandom(1024))
    directory = tmp_path / "wal"
    name = "0" * 24
    archive(source, name, directory)
    archive(source, name, directory)
    assert (directory / name).read_bytes() == source.read_bytes()
    source.write_bytes(b"wrong-cluster")
    with pytest.raises(ValueError):
        archive(source, name, directory)
    with pytest.raises(ValueError):
        archive(source, "../escape", directory)
    link = directory / ("A" * 24)
    link.symlink_to(source)
    with pytest.raises(OSError):
        archive(source, "A" * 24, directory)


async def test_durable_audit_failure_prevents_backup_publication(tmp_path, sources, monkeypatch):
    from argparse import Namespace

    from app.backup import cli

    key = tmp_path / "operator-key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)

    def fake_postgres(argv):
        for item in argv:
            if item.startswith("--pgdata="):
                from pathlib import Path

                postgres = Path(item.partition("=")[2])
                postgres.mkdir(mode=0o700)
                (postgres / "backup_manifest").write_text("unit fixture only")

    async def failed_audit(*args, **kwargs):
        raise OSError("durable audit unavailable")

    monkeypatch.setattr(cli, "command", fake_postgres)
    monkeypatch.setattr(cli, "event", failed_audit)
    repository = tmp_path / "repository"
    args = Namespace(
        key_file=key,
        action="create",
        confirmed_quiesced=True,
        pg_service="unit_fixture",
        source=[f"{name}={path}" for name, path in sources.items() if name != "postgres"],
        staging_parent=tmp_path,
        pg_bin=tmp_path,
        repository=repository,
        profile="AIO",
    )
    with pytest.raises(OSError):
        await cli.execute(args)
    assert all(path.name.startswith(".incomplete-") for path in repository.iterdir())
