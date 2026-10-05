from __future__ import annotations

import base64
import hashlib
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, BinaryIO
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class StorageError(RuntimeError):
    """Sanitized error; SDK details/credentials must not cross the API boundary."""


class ObjectExists(StorageError):
    pass


class ObjectMissing(StorageError):
    pass


class Area(StrEnum):
    QUARANTINE = "quarantine"
    DATA = "data"


@dataclass(frozen=True)
class ObjectKey:
    space_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, uuid.UUID)
            for value in (self.space_id, self.document_id, self.version_id)
        ):
            raise ValueError("Object identifiers must be UUIDs")

    def __str__(self) -> str:
        return f"{self.space_id}/{self.document_id}/{self.version_id}"


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    sha256: str


def create_storage(settings: Settings) -> SeaweedStorage:
    url = urlsplit(settings.s3_endpoint)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Invalid internal S3 endpoint")
    if (
        not settings.s3_access_key.get_secret_value()
        or not settings.s3_secret_key.get_secret_value()
    ):
        raise ValueError("S3 credentials are not configured")
    if settings.s3_data_bucket == settings.s3_quarantine_bucket:
        raise ValueError("Data and quarantine buckets must be separate")
    for bucket in (settings.s3_data_bucket, settings.s3_quarantine_bucket):
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("Invalid S3 bucket")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=60,
            retries={"mode": "standard", "max_attempts": 2},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    return SeaweedStorage(
        client, settings.s3_data_bucket, settings.s3_quarantine_bucket, settings.upload_max_bytes
    )


class SeaweedStorage:
    """Blocking SDK adapter: call from worker or an API threadpool, never the event loop."""

    def __init__(
        self, client: S3Client, data_bucket: str, quarantine_bucket: str, max_bytes: int
    ) -> None:
        self.client = client
        self.buckets = {Area.DATA: data_bucket, Area.QUARANTINE: quarantine_bucket}
        self.max_bytes = max_bytes

    @staticmethod
    def _error(exc: ClientError | BotoCoreError) -> StorageError:
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}:
                return ObjectExists("Immutable object already exists")
            if code in {"NoSuchKey", "404", "NotFound"}:
                return ObjectMissing("Object unavailable")
        return StorageError("Object storage unavailable")

    def put(self, key: ObjectKey, source: BinaryIO, area: Area = Area.QUARANTINE) -> ObjectInfo:
        source.seek(0)
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > self.max_bytes:
                raise ValueError("Object exceeds configured limit")
            digest.update(chunk)
        source.seek(0)
        info = ObjectInfo(size, digest.hexdigest())
        try:
            self.client.put_object(
                Bucket=self.buckets[area],
                Key=str(key),
                Body=source,
                ContentLength=size,
                ContentType="application/octet-stream",
                IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(digest.digest()).decode("ascii"),
                Metadata={"sha256": info.sha256},
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._error(exc) from None
        return info

    def stat(self, key: ObjectKey, area: Area = Area.DATA) -> ObjectInfo:
        try:
            result = self.client.head_object(Bucket=self.buckets[area], Key=str(key))
        except (ClientError, BotoCoreError) as exc:
            raise self._error(exc) from None
        digest = result.get("Metadata", {}).get("sha256", "")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise StorageError("Object integrity metadata missing")
        return ObjectInfo(result["ContentLength"], digest)

    def read(self, key: ObjectKey, area: Area = Area.DATA) -> Iterator[bytes]:
        try:
            result = self.client.get_object(Bucket=self.buckets[area], Key=str(key))
            body = result["Body"]
            try:
                while chunk := body.read(1024 * 1024):
                    yield chunk
            finally:
                body.close()
        except (ClientError, BotoCoreError) as exc:
            raise self._error(exc) from None

    def delete(self, key: ObjectKey, area: Area) -> None:
        """Internal worker primitive. Caller must enforce purge/retention/hold policy."""
        try:
            self.client.delete_object(Bucket=self.buckets[area], Key=str(key))
        except (ClientError, BotoCoreError) as exc:
            raise self._error(exc) from None
