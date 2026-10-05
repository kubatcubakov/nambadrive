import hashlib
import io
import uuid
from unittest.mock import Mock

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from pydantic import SecretStr

from app.core.config import Settings
from app.storage.seaweed import (
    ObjectExists,
    ObjectKey,
    ObjectMissing,
    SeaweedStorage,
    StorageError,
    create_storage,
)


@pytest.fixture
def storage():
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:18333",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    return SeaweedStorage(client, "data", "quarantine", 1024)


def key():
    return ObjectKey(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


def test_uuid_only_keys():
    item = key()
    assert str(item) == f"{item.space_id}/{item.document_id}/{item.version_id}"
    with pytest.raises(ValueError):
        ObjectKey("../filename", uuid.uuid4(), uuid.uuid4())


def test_immutable_write_uses_conditional_header_and_digest(storage):
    item = key()
    with Stubber(storage.client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "quarantine",
                "Key": str(item),
                "Body": ANY,
                "ContentLength": 5,
                "ContentType": "application/octet-stream",
                "IfNoneMatch": "*",
                "ChecksumSHA256": ANY,
                "Metadata": {"sha256": hashlib.sha256(b"hello").hexdigest()},
            },
        )
        info = storage.put(item, io.BytesIO(b"hello"))
        assert info.size == 5 and info.sha256 == hashlib.sha256(b"hello").hexdigest()
        stub.assert_no_pending_responses()


def test_oversized_write_never_calls_storage(storage):
    with Stubber(storage.client):
        with pytest.raises(ValueError):
            storage.put(key(), io.BytesIO(b"x" * 1025))


@pytest.mark.parametrize(
    "code,status,expected",
    [
        ("PreconditionFailed", 412, ObjectExists),
        ("NoSuchKey", 404, ObjectMissing),
        ("AccessDenied", 403, StorageError),
        ("InternalError", 500, StorageError),
    ],
)
def test_errors_are_sanitized(storage, code, status, expected):
    with Stubber(storage.client) as stub:
        stub.add_client_error("put_object", code, "SECRET MUST NOT LEAK", status)
        with pytest.raises(expected) as error:
            storage.put(key(), io.BytesIO(b"hello"))
        assert "SECRET" not in str(error.value)


def test_read_stream_closes_and_stat_integrity(storage):
    item = key()
    stream = io.BytesIO(b"hello")
    with Stubber(storage.client) as stub:
        stub.add_response(
            "get_object", {"Body": StreamingBody(stream, 5)}, {"Bucket": "data", "Key": str(item)}
        )
        assert b"".join(storage.read(item)) == b"hello"
        assert stream.closed
        stub.add_response("head_object", {"ContentLength": 5, "Metadata": {"sha256": "a" * 64}})
        assert storage.stat(item).sha256 == "a" * 64
        stub.add_response("head_object", {"ContentLength": 5})
        with pytest.raises(StorageError, match="integrity"):
            storage.stat(item)


def test_network_failure_is_closed():
    client = Mock()
    client.put_object.side_effect = EndpointConnectionError(endpoint_url="http://secret-host")
    with pytest.raises(StorageError, match="unavailable") as error:
        SeaweedStorage(client, "data", "quarantine", 1024).put(key(), io.BytesIO(b"x"))
    assert "secret-host" not in str(error.value)


def test_configuration_requires_secrets_and_separate_buckets():
    with pytest.raises(ValueError):
        create_storage(Settings())
    settings = Settings(s3_access_key=SecretStr("test"), s3_secret_key=SecretStr("sensitive"))
    assert "sensitive" not in repr(settings)
    settings.s3_quarantine_bucket = settings.s3_data_bucket
    with pytest.raises(ValueError, match="separate"):
        create_storage(settings)
    settings.s3_endpoint = "http://name:password@host"
    with pytest.raises(ValueError, match="endpoint"):
        create_storage(settings)
