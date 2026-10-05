"""Durable archive_command hook, standard-library-only for the PostgreSQL image.

The destination must be a dedicated encrypted independent mount, private to the PG user.
"""

import hashlib
import os
import re
import stat
import sys
import uuid
from pathlib import Path


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("Regular WAL file required")
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def archive(source: Path, filename: str, directory: Path) -> None:
    if not re.fullmatch(
        r"[0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup", filename
    ):
        raise ValueError("Invalid WAL archive filename")
    if not directory.is_absolute():
        raise ValueError("Absolute archive directory required")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Private PG-owned archive directory required")
    destination = directory / filename
    expected = checksum(source)
    if destination.exists() or destination.is_symlink():
        if checksum(destination) != expected:
            raise ValueError("Existing WAL differs: never overwrite archives")
        with destination.open("rb") as completed:
            os.fsync(completed.fileno())
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return
    temporary = directory / (".partial-" + str(uuid.uuid4()))
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(source_fd, "rb") as incoming, temporary.open("xb") as outgoing:
        os.chmod(temporary, 0o600)
        while chunk := incoming.read(1024 * 1024):
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if checksum(temporary) != expected:
        raise ValueError("WAL source changed during archive")
    try:
        os.link(temporary, destination)  # Atomic create-only publication, never replacement.
    except FileExistsError:
        if checksum(destination) != expected:
            raise ValueError("Concurrent WAL archive mismatch") from None
    temporary.unlink()
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise ValueError("WAL hook arguments required")
        archive(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
    except Exception:
        raise SystemExit("WAL archive failed; no segment acknowledged") from None
