from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.service import ContentService, NoteNotFoundError
from app.modules.taxonomy.service import TaxonomyNotFoundError, TaxonomyService
from app.modules.vectorization.contracts import (
    VectorizationDocumentInput,
    build_content_object_vector_subject,
    vectorization_document_from_subject,
)


class VectorizationDocumentProvider(Protocol):
    async def build_document(
        self,
        *,
        owner_user_id: str,
        source_id: str,
    ) -> VectorizationDocumentInput:
        raise NotImplementedError


class DocumentProviderNotFoundError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class DocumentProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], VectorizationDocumentProvider] = {}

    def register(
        self,
        *,
        source: str,
        source_type: str,
        provider: VectorizationDocumentProvider,
    ) -> None:
        self._providers[(source, source_type)] = provider

    def has_provider(self, *, source: str, source_type: str) -> bool:
        return (source, source_type) in self._providers

    def get(self, *, source: str, source_type: str) -> VectorizationDocumentProvider:
        provider = self._providers.get((source, source_type))
        if provider is None:
            raise DocumentProviderNotFoundError(
                f"No vectorization document provider for {source}/{source_type}."
            )
        return provider


class TaxonomyCategoryProfileDocumentProvider:
    def __init__(self, session: AsyncSession) -> None:
        self.service = TaxonomyService(session)

    async def build_document(
        self,
        *,
        owner_user_id: str,
        source_id: str,
    ) -> VectorizationDocumentInput:
        try:
            subject = await self.service.build_category_profile_vector_subject(
                owner_user_id=owner_user_id,
                category_id=source_id,
            )
        except TaxonomyNotFoundError as exc:
            raise DocumentNotFoundError("Taxonomy category profile source not found.") from exc
        return vectorization_document_from_subject(
            owner_user_id=owner_user_id,
            source="taxonomy",
            source_type="category_profile",
            source_id=source_id,
            chunking_strategy="short_document",
            representation_type="category_profile",
            subject=subject,
        )


class ContentObjectDocumentProvider:
    def __init__(self, session: AsyncSession) -> None:
        self.content_service = ContentService(session)
        self.taxonomy_service = TaxonomyService(session)

    async def build_document(
        self,
        *,
        owner_user_id: str,
        source_id: str,
    ) -> VectorizationDocumentInput:
        try:
            classification_input = await self.content_service.build_classification_input(
                owner_user_id=owner_user_id,
                content_object_id=source_id,
                text_excerpt_max_chars=50000,
            )
        except NoteNotFoundError as exc:
            raise DocumentNotFoundError("Content object source not found.") from exc

        assignment = await self.taxonomy_service.get_current_assignment(
            owner_user_id=owner_user_id,
            content_object_id=source_id,
        )
        subject = build_content_object_vector_subject(
            content_object_id=classification_input.content_object_id,
            title=classification_input.title,
            url=classification_input.url,
            tags=classification_input.tags,
            taxonomy_category=assignment.category_path_snapshot if assignment is not None else None,
            content=classification_input.text_excerpt,
            metadata=classification_input.metadata,
            source_updated_at=classification_input.updated_at,
        )
        return vectorization_document_from_subject(
            owner_user_id=owner_user_id,
            source="content",
            source_type="content_object",
            source_id=source_id,
            chunking_strategy="content_text",
            representation_type="content_text",
            subject=subject,
        )


def build_document_provider_registry(session: AsyncSession) -> DocumentProviderRegistry:
    registry = DocumentProviderRegistry()
    registry.register(
        source="taxonomy",
        source_type="category_profile",
        provider=TaxonomyCategoryProfileDocumentProvider(session),
    )
    registry.register(
        source="content",
        source_type="content_object",
        provider=ContentObjectDocumentProvider(session),
    )
    return registry
