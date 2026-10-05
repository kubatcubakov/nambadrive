import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.models.acl import HardPolicy
from app.models.search import SearchCheckpoint
from app.search.clients import Candidate, OpenSearch, SearchUnavailable, Tika
from app.search.indexer import Indexer
from app.search.service import search
from app.storage.seaweed import Area, StorageError
from tests.test_authorization import acl
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture

api, clean, scene = api_fixture, clean_fixture, scene_fixture


@pytest.fixture(autouse=True)
def search_audit():
    with patch("app.search.service.write_audit_event", new=AsyncMock()) as event:
        yield event


@pytest.fixture
async def indexed(db, clean):
    row, version, storage = clean
    engine = Mock()
    engine.candidates.return_value = [Candidate(row.id, version.id, "classified body", True)]
    return engine


async def test_acl_search_no_ids_snippets_counts_leak(api, scene, clean, indexed):
    client, state = api
    row, _, _ = clean
    with patch("app.api.v1.search.OpenSearch", return_value=indexed):
        response = await client.get("/api/v1/search?q=secret")
        assert response.status_code == 200 and response.json() == {"data": []}
        assert response.headers["Cache-Control"] == "no-store"
        assert str(row.id) not in response.text and "classified" not in response.text
        state["actor"] = scene[0]
        response = await client.get("/api/v1/search?q=secret")
        assert response.json()["data"][0]["snippet"] == "classified body"
        assert set(response.json()) == {"data"}
        assert "version_id" not in response.text and "score" not in response.text
        for query in ["q=a", "q=" + "a" * 201, "q=ok&limit=51"]:
            assert (await client.get("/api/v1/search?" + query)).status_code == 422


async def test_content_matches_require_preview(db, scene, clean, indexed):
    row, version, _ = clean
    grant = await acl(
        db, scene, resource=row, permission="VIEW", valid_from=datetime.now(UTC) - timedelta(days=1)
    )
    result = await search(db, scene[1], indexed, "secret", 20, {})
    assert result[0]["snippet"] == ""
    indexed.candidates.return_value = [Candidate(row.id, version.id, "secret", False)]
    assert await search(db, scene[1], indexed, "secret", 20, {}) == []
    await acl(
        db,
        scene,
        resource=row,
        permission="PREVIEW",
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    assert len(await search(db, scene[1], indexed, "secret", 20, {})) == 1
    grant.revoked_at = datetime.now(UTC)
    await db.commit()
    assert await search(db, scene[1], indexed, "secret", 20, {}) == []


@pytest.mark.parametrize(
    "blocked",
    [
        "hard_policy",
        "disabled",
        "trash",
        "parent_trash",
        "quarantine",
        "old_version",
        "foreign_version",
        "strict",
    ],
)
async def test_stale_index_never_bypasses_database(db, scene, clean, indexed, blocked):
    row, version, _ = clean
    actor = scene[0]
    if blocked == "hard_policy":
        db.add(HardPolicy(resource_id=scene[3].id, permission_id="VIEW", reason="blocked"))
    elif blocked == "disabled":
        actor.enabled = False
    elif blocked in {"trash", "parent_trash"}:
        target = row if blocked == "trash" else scene[3]
        target.state, target.deleted_at = "TRASH", datetime.now(UTC)
    elif blocked == "quarantine":
        row.state = "QUARANTINED"
    elif blocked == "old_version":
        version.is_current = False
    elif blocked == "foreign_version":
        indexed.candidates.return_value = [Candidate(scene[4].id, version.id, "secret", True)]
    else:
        row.classification = "STRICTLY_CONFIDENTIAL"
        actor = scene[1]
    await db.commit()
    assert await search(db, actor, indexed, "secret", 20, {}) == []


async def test_engine_failure_sanitized_and_no_partial_results(api, scene, indexed):
    client, state = api
    state["actor"] = scene[0]
    indexed.candidates.side_effect = SearchUnavailable("private dependency body")
    with patch("app.api.v1.search.OpenSearch", return_value=indexed):
        response = await client.get("/api/v1/search?q=hello")
    assert response.status_code == 503 and "private" not in response.text


async def test_durable_index_retry_rename_delete(db, scene, clean):
    row, version, storage = clean
    tika, engine = Mock(), Mock()
    tika.extract.return_value = "hello extracted"
    indexer = Indexer(db, storage, tika, engine)
    # Fixture also has a metadata-only document: process it too.
    while await indexer.process_one():
        pass
    engine.put.assert_called_once_with(row.id, version.id, "hello.txt", "hello extracted")
    row.name = "renamed.txt"
    await db.commit()
    engine.put.side_effect = SearchUnavailable()
    with pytest.raises(SearchUnavailable):
        await indexer.process_one()
    checkpoint = await db.get(SearchCheckpoint, row.id)
    assert checkpoint.indexed_name == "hello.txt" and checkpoint.retry_after is not None
    assert not await indexer.process_one()
    checkpoint.retry_after = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    engine.put.side_effect = None
    assert await indexer.process_one()
    assert checkpoint.indexed_name == "renamed.txt"
    row.state, row.deleted_at = "TRASH", datetime.now(UTC)
    await db.commit()
    assert await indexer.process_one()
    engine.delete.assert_called_with(row.id)
    assert not await indexer.process_one()


async def test_indexer_integrity_failure_no_text_sent(db, clean):
    row, _, storage = clean
    for key in storage.objects:
        if key[0] == Area.DATA:
            storage.objects[key] = b"corrupt"
    tika, engine = Mock(), Mock()
    with pytest.raises(StorageError):
        while await Indexer(db, storage, tika, engine).process_one():
            pass
    tika.extract.assert_not_called()
    engine.put.assert_not_called()
    assert (
        await db.scalar(select(SearchCheckpoint).where(SearchCheckpoint.document_id == row.id))
    ).retry_after


def settings():
    return Settings(opensearch_username="test", opensearch_password=SecretStr("test-only"))


def test_generated_query_no_user_dsl_or_full_source():
    doc_id, version_id = uuid.uuid4(), uuid.uuid4()

    def handle(request):
        data = json.loads(request.content)
        assert data["track_total_hits"] is False
        assert data["_source"] == ["version_id"]
        assert data["query"]["bool"]["should"][0]["match"]["name"]["query"] == '{"match_all":{}}'
        return httpx.Response(
            200,
            json={
                "hits": {
                    "hits": [
                        {
                            "_id": str(doc_id),
                            "_source": {"version_id": str(version_id)},
                            "matched_queries": ["filename"],
                            "highlight": {"content": ["<script>plain escaped text</script>"]},
                        }
                    ]
                }
            },
        )

    result = OpenSearch(settings(), httpx.MockTransport(handle)).candidates('{"match_all":{}}')
    assert result[0].document_id == doc_id and result[0].name_match


def test_tika_no_ocr_no_url_fetch_and_bounded_output():
    def handle(request):
        assert str(request.url).endswith("/tika")
        assert request.headers["X-Tika-PDFOcrStrategy"] == "no_ocr"
        assert request.headers["X-Tika-OCRskipOcr"] == "true"
        assert request.content == b"approved file bytes"
        return httpx.Response(200, content=b"a" * 2048)

    s = Settings(search_text_max_bytes=1024)
    assert (
        len(
            Tika(s, httpx.MockTransport(handle)).extract(
                io.BytesIO(b"approved file bytes"), "text/plain"
            )
        )
        == 1024
    )


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://user:secret@host", "http://host/path", "http://host?x=1"]
)
def test_invalid_service_urls(url):
    with pytest.raises(SearchUnavailable):
        Tika(Settings(tika_url=url))


def test_search_errors_and_redirects_are_closed():
    for response in [
        httpx.Response(302, headers={"Location": "http://evil"}),
        httpx.Response(500, text="private upstream body"),
        httpx.Response(200, json={"malformed": True}),
    ]:
        with pytest.raises(SearchUnavailable):
            OpenSearch(
                settings(), httpx.MockTransport(lambda r, response=response: response)
            ).candidates("hello")
    with pytest.raises(SearchUnavailable):
        OpenSearch(Settings())
