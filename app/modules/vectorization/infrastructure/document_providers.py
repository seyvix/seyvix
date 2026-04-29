from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.taxonomy.service import TaxonomyNotFoundError, TaxonomyService
from app.modules.vectorization.contracts import (
    VectorizationDocumentInput,
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


def build_document_provider_registry(session: AsyncSession) -> DocumentProviderRegistry:
    registry = DocumentProviderRegistry()
    registry.register(
        source="taxonomy",
        source_type="category_profile",
        provider=TaxonomyCategoryProfileDocumentProvider(session),
    )
    return registry
