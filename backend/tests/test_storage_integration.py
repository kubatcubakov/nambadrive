"""Opt-in tests against real, isolated SeaweedFS; never production buckets."""

import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.storage.seaweed import (
    Area,
    ObjectExists,
    ObjectKey,
    ObjectMissing,
    StorageError,
    create_storage,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("NAMBADRIVE_TEST_S3_CONFIG"), reason="Isolated SeaweedFS not configured"
)


def test_real_storage_immutable_concurrent_quarantine_and_auth():
    config = json.loads(Path(os.environ["NAMBADRIVE_TEST_S3_CONFIG"]).read_text())
    credentials = config["identities"][0]["credentials"][0]
    suffix = uuid.uuid4().hex
    settings = Settings(
        s3_endpoint=os.environ.get("NAMBADRIVE_TEST_S3_ENDPOINT", "http://127.0.0.1:18333"),
        s3_access_key=SecretStr(credentials["accessKey"]),
        s3_secret_key=SecretStr(credentials["secretKey"]),
        s3_data_bucket=f"test-data-{suffix}",
        s3_quarantine_bucket=f"test-quarantine-{suffix}",
    )
    storage = create_storage(settings)
    keys = [ObjectKey(uuid.uuid4(), uuid.uuid4(), uuid.uuid4()) for _ in range(2)]
    buckets = list(storage.buckets.values())
    for bucket in buckets:
        storage.client.create_bucket(Bucket=bucket)
    try:
        info = storage.put(keys[0], io.BytesIO(b"original"))
        assert storage.stat(keys[0], Area.QUARANTINE) == info
        with pytest.raises(ObjectMissing):
            storage.stat(keys[0], Area.DATA)
        with pytest.raises(ObjectExists):
            storage.put(keys[0], io.BytesIO(b"replacement"))
        assert b"".join(storage.read(keys[0], Area.QUARANTINE)) == b"original"

        def attempt(number):
            try:
                storage.put(keys[1], io.BytesIO(str(number).encode()))
                return number
            except ObjectExists:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        winners = [item for item in results if item is not None]
        assert len(winners) == 1
        assert b"".join(storage.read(keys[1], Area.QUARANTINE)) == str(winners[0]).encode()
        settings.s3_secret_key = SecretStr("incorrect-test-secret")
        with pytest.raises(StorageError):
            create_storage(settings).stat(keys[0], Area.QUARANTINE)
    finally:
        for key in keys:
            storage.delete(key, Area.QUARANTINE)
        for bucket in buckets:
            storage.client.delete_bucket(Bucket=bucket)
