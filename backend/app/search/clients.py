from __future__ import annotations

import json
import re
import ssl
import uuid
from dataclasses import dataclass
from typing import IO, Any
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings


class SearchUnavailable(Exception):
    """Sanitized dependency failure: never return upstream bodies or credentials."""


def endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SearchUnavailable("Invalid search service configuration")
    return value.rstrip("/")


class Tika:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.url = endpoint(settings.tika_url)
        self.limit = settings.search_text_max_bytes
        self.transport = transport

    def extract(self, source: IO[bytes], mime_type: str) -> str:
        source.seek(0)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(60, connect=5), trust_env=False, transport=self.transport
            ) as client:
                with client.stream(
                    "PUT",
                    self.url + "/tika",
                    content=iter(lambda: source.read(65536), b""),
                    headers={
                        "Content-Type": mime_type,
                        "Accept": "text/plain",
                        "X-Tika-PDFOcrStrategy": "no_ocr",
                        "X-Tika-OCRskipOcr": "true",
                    },
                ) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if len(data) + len(chunk) > self.limit:
                            # A bounded prefix is useful; extraction is never executed in the API.
                            data.extend(chunk[: self.limit - len(data)])
                            break
                        data.extend(chunk)
            return bytes(data).decode("utf-8", errors="replace").replace("\x00", "")
        except (httpx.HTTPError, OSError) as exc:
            raise SearchUnavailable("Text extraction unavailable") from exc


@dataclass(frozen=True)
class Candidate:
    document_id: uuid.UUID
    version_id: uuid.UUID
    snippet: str
    name_match: bool


class OpenSearch:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.url = endpoint(settings.opensearch_url)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,99}", settings.search_index):
            raise SearchUnavailable("Invalid index configuration")
        if not settings.opensearch_username or not settings.opensearch_password.get_secret_value():
            raise SearchUnavailable("Search credentials required")
        self.index = settings.search_index
        self.auth = (settings.opensearch_username, settings.opensearch_password.get_secret_value())
        self.verify = ssl.create_default_context(cafile=settings.opensearch_ca_file)
        self.transport = transport

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(30, connect=5),
                trust_env=False,
                auth=self.auth,
                verify=self.verify,
                transport=self.transport,
            ) as client:
                with client.stream(
                    method, self.url + "/" + self.index + path, json=body
                ) as response:
                    # Delete is idempotent across DB commit failure / retries.
                    if method == "DELETE" and response.status_code == 404:
                        return {}
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            raise SearchUnavailable("Search response exceeds limit")
                    result = json.loads(data)
                    if not isinstance(result, dict):
                        raise SearchUnavailable("Invalid search response")
                    return result
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise SearchUnavailable("Search unavailable") from exc

    def initialize(self) -> None:
        # Called explicitly during provisioning, not with the query account.
        self.request(
            "PUT",
            "",
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 1},
                "mappings": {
                    "dynamic": "strict",
                    "properties": {
                        "version_id": {"type": "keyword"},
                        "name": {"type": "text"},
                        "content": {"type": "text"},
                    },
                },
            },
        )

    def put(self, document_id: uuid.UUID, version_id: uuid.UUID, name: str, content: str) -> None:
        self.request(
            "PUT",
            "/_doc/" + str(document_id),
            {
                "version_id": str(version_id),
                "name": name,
                "content": content,
            },
        )

    def delete(self, document_id: uuid.UUID) -> None:
        self.request("DELETE", "/_doc/" + str(document_id))

    def candidates(self, query: str) -> list[Candidate]:
        result = self.request(
            "POST",
            "/_search",
            {
                "size": 1000,
                "track_total_hits": False,
                "_source": ["version_id"],
                "query": {
                    "bool": {
                        "minimum_should_match": 1,
                        "should": [
                            {"match": {"name": {"query": query, "_name": "filename", "boost": 3}}},
                            {"match": {"content": {"query": query, "_name": "body"}}},
                        ],
                    }
                },
                "highlight": {
                    "pre_tags": [""],
                    "post_tags": [""],
                    "fields": {
                        "content": {"fragment_size": 240, "number_of_fragments": 1},
                    },
                },
            },
        )
        try:
            hits = result["hits"]["hits"]
            if not isinstance(hits, list) or len(hits) > 1000:
                raise ValueError
            return [
                Candidate(
                    uuid.UUID(hit["_id"]),
                    uuid.UUID(hit["_source"]["version_id"]),
                    str(hit.get("highlight", {}).get("content", [""])[0])[:500],
                    "filename" in hit.get("matched_queries", []),
                )
                for hit in hits
            ]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise SearchUnavailable("Invalid search response") from exc
