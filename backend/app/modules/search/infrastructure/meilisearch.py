from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.modules.search.schemas import HybridSearchResult, SearchFilters, SearchMode
from app.modules.vectorization.infrastructure.chunking import TextChunk
from app.modules.vectorization.infrastructure.embedding_providers import EmbeddingProvider
from app.modules.vectorization.models import VectorizationSource


class MeilisearchUnavailableError(Exception):
    pass


class MeilisearchClient(Protocol):
    async def configure_index(
        self,
        *,
        index_uid: str,
        embedder: str,
        dimensions: int,
    ) -> None:
        raise NotImplementedError

    async def replace_documents(
        self,
        *,
        index_uid: str,
        documents: list[dict[str, Any]],
    ) -> None:
        raise NotImplementedError

    async def delete_documents_by_filter(self, *, index_uid: str, filter_expression: str) -> None:
        raise NotImplementedError

    async def search(self, *, index_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class HttpMeilisearchClient:
    def __init__(self, *, base_url: str, api_key: str | None, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def configure_index(
        self,
        *,
        index_uid: str,
        embedder: str,
        dimensions: int,
    ) -> None:
        await self._request(
            "PATCH",
            f"/indexes/{index_uid}/settings",
            json={
                "searchableAttributes": [
                    "title",
                    "text",
                    "source_filename",
                    "source_title",
                    "tags",
                    "folder_path",
                ],
                "displayedAttributes": [
                    "id",
                    "source",
                    "source_type",
                    "source_id",
                    "external_id",
                    "chunk_external_id",
                    "text",
                    "metadata",
                    "content_object_id",
                    "content_type",
                    "source_provider",
                ],
                "filterableAttributes": [
                    "owner_user_id",
                    "source",
                    "source_type",
                    "source_id",
                    "content_object_id",
                    "content_type",
                    "media_type",
                    "source_provider",
                    "source_kind",
                    "telegram_chat_id",
                    "telegram_chat_type",
                    "telegram_author_id",
                    "tags",
                    "folder_path",
                    "is_favorite",
                    "content_created_ts",
                    "content_updated_ts",
                    "source_original_created_ts",
                    "source_record_id",
                ],
                "sortableAttributes": [
                    "content_created_ts",
                    "content_updated_ts",
                    "source_original_created_ts",
                ],
                "embedders": {
                    embedder: {
                        "source": "userProvided",
                        "dimensions": dimensions,
                    }
                },
            },
        )

    async def replace_documents(
        self,
        *,
        index_uid: str,
        documents: list[dict[str, Any]],
    ) -> None:
        if not documents:
            return
        await self._request("POST", f"/indexes/{index_uid}/documents", json=documents)

    async def delete_documents_by_filter(self, *, index_uid: str, filter_expression: str) -> None:
        await self._request(
            "POST",
            f"/indexes/{index_uid}/documents/delete",
            json={"filter": filter_expression},
        )

    async def search(self, *, index_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/indexes/{index_uid}/search", json=payload)

    async def _request(
        self, method: str, path: str, *, json: object | None = None
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.request(method, path, json=json)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MeilisearchUnavailableError("Meilisearch request failed.") from exc
        return data if isinstance(data, dict) else {}


class MeilisearchSearchBackend:
    def __init__(
        self,
        *,
        client: MeilisearchClient,
        embedding_provider: EmbeddingProvider,
        settings: Settings,
    ) -> None:
        self.client = client
        self.embedding_provider = embedding_provider
        self.settings = settings

    async def search(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        mode: SearchMode,
        filters: SearchFilters | None = None,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list[HybridSearchResult]:
        payload: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "filter": build_meilisearch_filter_expression(
                owner_user_id=owner_user_id,
                filters=filters,
                source=source,
                source_type=source_type,
                source_id=source_id,
            ),
            "showRankingScore": True,
        }
        if mode != "full_text":
            vector = (
                await self.embedding_provider.embed_texts(
                    [query],
                    model=self.settings.vector_embedding_model,
                    dimensions=self.settings.vector_embedding_dimensions,
                )
            )[0]
            payload["vector"] = vector
            payload["hybrid"] = {
                "embedder": self.settings.search_meilisearch_embedder,
                "semanticRatio": (
                    1.0
                    if mode == "semantic"
                    else self.settings.search_meilisearch_hybrid_semantic_ratio
                ),
            }

        response = await self.client.search(
            index_uid=self.settings.search_meilisearch_index_uid,
            payload=payload,
        )
        hits = response.get("hits", [])
        if not isinstance(hits, list):
            return []
        return [_result_from_hit(hit) for hit in hits if isinstance(hit, dict)]


async def sync_meilisearch_source(
    *,
    settings: Settings,
    source_record: VectorizationSource,
    chunks: Sequence[TextChunk],
    embeddings: Sequence[Sequence[float]],
) -> None:
    if settings.search_engine != "meilisearch" or not settings.search_meilisearch_url:
        return
    client = build_meilisearch_client(settings)
    await client.configure_index(
        index_uid=settings.search_meilisearch_index_uid,
        embedder=settings.search_meilisearch_embedder,
        dimensions=settings.vector_embedding_dimensions,
    )
    await client.delete_documents_by_filter(
        index_uid=settings.search_meilisearch_index_uid,
        filter_expression=f'source_record_id = "{_escape_filter_value(source_record.id)}"',
    )
    documents = build_meilisearch_documents(
        source_record=source_record,
        chunks=chunks,
        embeddings=embeddings,
        embedder=settings.search_meilisearch_embedder,
    )
    await client.replace_documents(
        index_uid=settings.search_meilisearch_index_uid,
        documents=documents,
    )


async def delete_meilisearch_source(
    *, settings: Settings, source_record: VectorizationSource
) -> None:
    if settings.search_engine != "meilisearch" or not settings.search_meilisearch_url:
        return
    client = build_meilisearch_client(settings)
    await client.delete_documents_by_filter(
        index_uid=settings.search_meilisearch_index_uid,
        filter_expression=f'source_record_id = "{_escape_filter_value(source_record.id)}"',
    )


def build_meilisearch_client(settings: Settings) -> HttpMeilisearchClient:
    if not settings.search_meilisearch_url:
        raise MeilisearchUnavailableError("Meilisearch URL is not configured.")
    return HttpMeilisearchClient(
        base_url=settings.search_meilisearch_url,
        api_key=settings.search_meilisearch_api_key,
        timeout_seconds=settings.search_meilisearch_timeout_seconds,
    )


def build_meilisearch_documents(
    *,
    source_record: VectorizationSource,
    chunks: Sequence[TextChunk],
    embeddings: Sequence[Sequence[float]],
    embedder: str,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        metadata = dict(chunk.metadata)
        document = {
            "id": _document_id(source_record.id, chunk.chunk_external_id),
            "owner_user_id": source_record.owner_user_id,
            "source": source_record.source,
            "source_type": source_record.source_type,
            "source_id": source_record.source_id,
            "source_record_id": source_record.id,
            "external_id": source_record.external_id,
            "chunk_external_id": chunk.chunk_external_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "metadata": metadata,
            "content_object_id": _metadata_str(metadata, "content_object_id")
            or source_record.source_id,
            "title": _metadata_str(metadata, "content_title"),
            "content_type": _content_type(metadata),
            "media_type": _metadata_str(metadata, "media_type"),
            "mime_type": _metadata_str(metadata, "mime_type"),
            "source_filename": _metadata_str(metadata, "source_filename"),
            "source_provider": _metadata_str(metadata, "content_source_provider")
            or _metadata_str(metadata, "source_provider"),
            "source_kind": _metadata_str(metadata, "source_kind"),
            "source_title": _metadata_str(metadata, "source_title"),
            "telegram_chat_id": _metadata_str(metadata, "telegram_chat_id"),
            "telegram_chat_type": _metadata_str(metadata, "telegram_chat_type"),
            "telegram_author_id": _metadata_str(metadata, "telegram_author_id"),
            "tags": _metadata_list(metadata, "tags"),
            "folder_path": _metadata_str(metadata, "taxonomy_category"),
            "is_favorite": _metadata_bool(metadata, "is_favorite"),
            "content_created_ts": _metadata_ts(metadata, "content_created_at"),
            "content_updated_ts": _metadata_ts(metadata, "content_updated_at"),
            "source_original_created_ts": _metadata_ts(metadata, "source_original_created_at"),
            "_vectors": {embedder: list(embedding)},
        }
        documents.append({key: value for key, value in document.items() if value is not None})
    return documents


def build_meilisearch_filter_expression(
    *,
    owner_user_id: str,
    filters: SearchFilters | None,
    source: str | None,
    source_type: str | None,
    source_id: str | None,
) -> str:
    clauses = [_eq("owner_user_id", owner_user_id)]
    if source:
        clauses.append(_eq("source", source))
    if source_type:
        clauses.append(_eq("source_type", source_type))
    if source_id:
        clauses.append(_eq("source_id", source_id))
    if filters is None:
        return " AND ".join(clauses)

    if filters.source:
        clauses.append(_eq("source", filters.source))
    if filters.source_type:
        clauses.append(_eq("source_type", filters.source_type))
    if filters.source_id:
        clauses.append(_eq("source_id", filters.source_id))

    content_types = [value.strip() for value in filters.content_types if value.strip()]
    if filters.content_type and filters.content_type.strip():
        content_types.append(filters.content_type.strip())
    if content_types:
        clauses.append(
            "(" + " OR ".join(_eq("content_type", value) for value in content_types) + ")"
        )

    provider = filters.source_provider or filters.content_source
    if provider:
        clauses.append(_eq("source_provider", provider))
    if filters.source_kind:
        clauses.append(_eq("source_kind", filters.source_kind))
    if filters.telegram_chat_type:
        clauses.append(_eq("telegram_chat_type", filters.telegram_chat_type))
    if filters.telegram_chat_id:
        clauses.append(_eq("telegram_chat_id", filters.telegram_chat_id))
    if filters.telegram_author_id:
        clauses.append(_eq("telegram_author_id", filters.telegram_author_id))
    for tag in filters.tags:
        if tag.strip():
            clauses.append(_eq("tags", tag.strip()))
    if filters.folder_path:
        clauses.append(_eq("folder_path", filters.folder_path))
    if filters.is_favorite is not None:
        clauses.append(f"is_favorite = {str(filters.is_favorite).lower()}")

    created_from = filters.created_at_from or filters.date_from
    created_to = filters.created_at_to or filters.date_to
    if created_from is not None:
        clauses.append(f"content_created_ts >= {_to_timestamp(created_from)}")
    if created_to is not None:
        clauses.append(f"content_created_ts <= {_to_timestamp(created_to)}")
    if filters.updated_at_from is not None:
        clauses.append(f"content_updated_ts >= {_to_timestamp(filters.updated_at_from)}")
    if filters.updated_at_to is not None:
        clauses.append(f"content_updated_ts <= {_to_timestamp(filters.updated_at_to)}")
    return " AND ".join(clauses)


def _result_from_hit(hit: dict[str, Any]) -> HybridSearchResult:
    metadata: dict[str, object] = hit["metadata"] if isinstance(hit.get("metadata"), dict) else {}
    return HybridSearchResult(
        source=str(hit.get("source") or ""),
        source_type=str(hit.get("source_type") or ""),
        source_id=str(hit.get("source_id") or ""),
        external_id=str(hit.get("external_id") or ""),
        chunk_id=str(hit.get("id") or ""),
        chunk_external_id=str(hit.get("chunk_external_id") or ""),
        text=str(hit.get("text") or ""),
        metadata=metadata,
        score=float(hit.get("_rankingScore") or 0),
        full_text_score=float(hit.get("_rankingScore") or 0),
    )


def _content_type(metadata: dict[str, Any]) -> str | None:
    media_type = _metadata_str(metadata, "media_type")
    mime_type = (_metadata_str(metadata, "mime_type") or "").casefold()
    source_filename = (_metadata_str(metadata, "source_filename") or "").casefold()
    if media_type == "text":
        return "note"
    if media_type == "document" and (
        mime_type == "application/pdf" or source_filename.endswith(".pdf")
    ):
        return "pdf"
    return media_type


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _metadata_bool(metadata: dict[str, Any], key: str) -> bool | None:
    value = metadata.get(key)
    return value if isinstance(value, bool) else None


def _metadata_ts(metadata: dict[str, Any], key: str) -> int | None:
    value = _metadata_str(metadata, key)
    if value is None:
        return None
    try:
        return _to_timestamp(datetime.fromisoformat(value))
    except ValueError:
        return None


def _to_timestamp(value: datetime) -> int:
    return int(value.timestamp())


def _document_id(source_record_id: str, chunk_external_id: str) -> str:
    raw = f"{source_record_id}:{chunk_external_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def _eq(attribute: str, value: str) -> str:
    return f'{attribute} = "{_escape_filter_value(value)}"'


def _escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
