"""Render `NoteCardResponse`s with batched loading (a fixed number of queries per page)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import (
    ContentAsset,
    ContentLinkSnapshotDecision,
    ContentObject,
    ContentSource,
)
from app.modules.content.schemas import (
    CollectionParentResponse,
    ContentTaxonomyCategoryResponse,
    DeferredLinkSnapshotsResponse,
    NoteAssetResponse,
    NoteCardResponse,
    SnapshotViewResponse,
    SourceMetadataResponse,
    TagResponse,
)
from app.modules.content.text import (
    extract_links,
    is_generated_favicon_url,
    is_markdown_file,
    is_pdf_file,
)
from app.modules.search.schemas import SearchContentMatch
from app.modules.snapshots.models import SnapshotJob
from app.modules.snapshots.service import AssetPreview, SnapshotArtifactReference, SnapshotService
from app.modules.tags.models import Tag
from app.modules.tags.service import TagsService
from app.modules.taxonomy.models import TaxonomyContentAssignment
from app.platform.jobs import JOB_PENDING, JOB_PROCESSING

AUTO_LINK_SNAPSHOT_LIMIT = 3
DEFERRED_LINK_SNAPSHOT_TTL = timedelta(hours=12)
CARD_LIST_ASSET_LIMIT = 6
CARD_LIST_COLLECTION_ITEM_LIMIT = 6


def visible_children(content_object: ContentObject) -> list[ContentObject]:
    """Live children of a collection in position order (requires loaded collection_items)."""
    if content_object.kind != "collection":
        return []
    return [
        item.content_object
        for item in sorted(content_object.collection_items, key=lambda item: item.position)
        if item.content_object.deleted_at is None
    ]


def tag_response(tag: Tag, *, count: int = 0) -> TagResponse:
    return TagResponse(id=tag.id, name=tag.name, slug=tag.slug, count=count)


def taxonomy_category_response(
    assignment: TaxonomyContentAssignment | None,
) -> ContentTaxonomyCategoryResponse | None:
    if assignment is None:
        return None
    return ContentTaxonomyCategoryResponse(
        id=assignment.category_id,
        name=assignment.category_name_snapshot,
        slug=assignment.category_path_snapshot.rsplit("/", 1)[-1],
        path=assignment.category_path_snapshot,
    )


def text_link_urls(content_object: ContentObject) -> list[str]:
    urls: list[str] = []
    for asset in content_object.assets:
        if asset.media_type != "text" or not asset.text_content:
            continue
        links, _ = extract_links(asset.text_content)
        urls.extend(url for url in links if not is_generated_favicon_url(url))
    return list(dict.fromkeys(urls))


def link_asset_urls(content_object: ContentObject) -> list[str]:
    return [
        asset.text_content.strip()
        for asset in content_object.assets
        if asset.media_type == "link" and asset.text_content
    ]


def remaining_text_link_urls(content_object: ContentObject) -> list[str]:
    existing = set(link_asset_urls(content_object))
    return [url for url in text_link_urls(content_object) if url not in existing]


def source_response(record: ContentSource) -> SourceMetadataResponse:
    return SourceMetadataResponse(
        provider=record.provider,
        provider_label=record.provider_label,
        external_id=record.external_id,
        url=record.source_url,
        title=record.title,
        original_created_at=record.original_created_at,
        origin=record.origin,
        author=record.author,
        group_id=record.group_id,
        entities=record.entities or [],
        custom_emoji_ids=record.custom_emoji_ids or [],
        raw_payload=record.raw_payload,
        metadata=record.source_metadata or {},
    )


def merge_source_metadata(
    base: SourceMetadataResponse, sources: Sequence[SourceMetadataResponse]
) -> SourceMetadataResponse:
    """Union custom emoji ids/assets of all sources of a note into `base` (Telegram albums)."""
    custom_emoji_ids = list(dict.fromkeys(base.custom_emoji_ids))
    custom_emoji_assets: dict[str, Any] = {}
    for source in sources:
        for custom_emoji_id in source.custom_emoji_ids:
            if custom_emoji_id not in custom_emoji_ids:
                custom_emoji_ids.append(custom_emoji_id)
        assets = source.metadata.get("custom_emoji_assets")
        if isinstance(assets, dict):
            for custom_emoji_id, asset in assets.items():
                if isinstance(custom_emoji_id, str):
                    custom_emoji_assets.setdefault(custom_emoji_id, asset)
    metadata = dict(base.metadata)
    if custom_emoji_assets:
        existing = metadata.get("custom_emoji_assets")
        merged = dict(existing) if isinstance(existing, dict) else {}
        for custom_emoji_id, asset in custom_emoji_assets.items():
            merged.setdefault(custom_emoji_id, asset)
        metadata["custom_emoji_assets"] = merged
    return base.model_copy(update={"custom_emoji_ids": custom_emoji_ids, "metadata": metadata})


@dataclass(slots=True)
class _Context:
    tags: dict[str, list[Tag]] = field(default_factory=dict)
    assignments: dict[str, TaxonomyContentAssignment] = field(default_factory=dict)
    processing: set[str] = field(default_factory=set)
    previews: dict[str, AssetPreview] = field(default_factory=dict)
    artifact_refs: dict[str, dict[str, SnapshotArtifactReference]] = field(default_factory=dict)
    object_sources: dict[str, SourceMetadataResponse] = field(default_factory=dict)
    asset_sources: dict[str, SourceMetadataResponse] = field(default_factory=dict)
    decided: set[str] = field(default_factory=set)


class CardBuilder:
    def __init__(
        self,
        session: AsyncSession,
        *,
        snapshots: SnapshotService,
        tags: TagsService,
        api_prefix: str,
    ) -> None:
        self.session = session
        self.snapshots = snapshots
        self.tags = tags
        self.api_prefix = api_prefix

    # --- public -----------------------------------------------------------------------

    async def full_cards(
        self,
        objects: Sequence[ContentObject],
        *,
        search_matches: dict[str, list[SearchContentMatch]] | None = None,
    ) -> list[NoteCardResponse]:
        """Complete cards (all assets, children rendered fully, snapshot views, sources).
        Requires objects loaded with `content_object_load_options()`; nested collections
        deeper than one level must already be in the session (see `ContentReader`)."""
        tree = _collect_tree(objects, max_depth=None)
        if not objects:
            return []
        owner_user_id = objects[0].owner_user_id
        asset_ids = [asset.id for obj in tree for asset in obj.assets]
        context = await self._load_context(owner_user_id, tree, asset_ids=asset_ids, full=True)
        return [
            self._full_card(obj, context, search_matches=(search_matches or {}).get(obj.id))
            for obj in objects
        ]

    async def summary_cards(
        self,
        objects: Sequence[ContentObject],
        *,
        search_matches: dict[str, list[SearchContentMatch]] | None = None,
    ) -> list[NoteCardResponse]:
        """Lightweight dashboard cards: up to 6 preview assets / children, no heavy fields."""
        if not objects:
            return []
        tree = _collect_tree(objects, max_depth=1)
        owner_user_id = objects[0].owner_user_id
        asset_ids = [asset.id for obj in tree for asset in _card_preview_assets(obj.assets)]
        context = await self._load_context(
            owner_user_id, tree, asset_ids=asset_ids, full=False, tag_ids=[o.id for o in objects]
        )
        return [
            self._summary_card(
                obj, context, top_level=True, search_matches=(search_matches or {}).get(obj.id)
            )
            for obj in objects
        ]

    def asset_url(self, content_object: ContentObject, asset: ContentAsset) -> str:
        return f"{self.api_prefix}/notes/{content_object.slug}/asset/{asset.id}"

    # --- loading ----------------------------------------------------------------------

    async def _load_context(
        self,
        owner_user_id: str,
        tree: Sequence[ContentObject],
        *,
        asset_ids: Sequence[str],
        full: bool,
        tag_ids: Sequence[str] | None = None,
    ) -> _Context:
        object_ids = [obj.id for obj in tree]
        context = _Context()
        context.tags = await self.tags.list_active_tags_for_contents(
            owner_user_id=owner_user_id, content_object_ids=list(tag_ids or object_ids)
        )
        assignment_ids = list(tag_ids or object_ids)
        context.assignments = {
            row.content_object_id: row
            for row in await self.session.scalars(
                select(TaxonomyContentAssignment).where(
                    TaxonomyContentAssignment.owner_user_id == owner_user_id,
                    TaxonomyContentAssignment.content_object_id.in_(assignment_ids),
                    TaxonomyContentAssignment.is_current.is_(True),
                )
            )
        }
        context.processing = set(
            await self.session.scalars(
                select(SnapshotJob.content_object_id)
                .where(
                    SnapshotJob.content_object_id.in_(object_ids),
                    SnapshotJob.status.in_((JOB_PENDING, JOB_PROCESSING)),
                )
                .distinct()
            )
        )
        if asset_ids:
            context.previews = await self.snapshots.asset_previews(
                owner_user_id=owner_user_id, asset_ids=list(asset_ids)
            )
        if not full:
            return context
        if asset_ids:
            context.artifact_refs = await self.snapshots.asset_artifact_references(asset_ids)
        await self._load_sources(owner_user_id, tree, context)
        link_ids = [obj.id for obj in tree if obj.media_type == "link"]
        if link_ids:
            context.decided = set(
                await self.session.scalars(
                    select(ContentLinkSnapshotDecision.content_object_id).where(
                        ContentLinkSnapshotDecision.content_object_id.in_(link_ids)
                    )
                )
            )
        return context

    async def _load_sources(
        self, owner_user_id: str, tree: Sequence[ContentObject], context: _Context
    ) -> None:
        object_ids = [obj.id for obj in tree]
        asset_owner = {asset.id: obj.id for obj in tree for asset in obj.assets}
        records = list(
            await self.session.scalars(
                select(ContentSource)
                .where(
                    ContentSource.owner_user_id == owner_user_id,
                    or_(
                        ContentSource.content_object_id.in_(object_ids),
                        ContentSource.content_asset_id.in_(list(asset_owner) or [""]),
                    ),
                )
                .order_by(ContentSource.created_at.asc())
            )
        )
        per_object: dict[str, list[ContentSource]] = {}
        for record in records:
            owner = asset_owner.get(record.content_asset_id or "", record.content_object_id)
            per_object.setdefault(owner, []).append(record)
        for object_id, object_records in per_object.items():
            responses = [source_response(record) for record in object_records]
            for record, response in zip(object_records, responses, strict=True):
                if record.content_asset_id and record.content_asset_id in asset_owner:
                    if record.content_asset_id not in context.asset_sources:
                        context.asset_sources[record.content_asset_id] = merge_source_metadata(
                            response, responses
                        )
                elif record.content_object_id == object_id:
                    if object_id not in context.object_sources:
                        context.object_sources[object_id] = merge_source_metadata(
                            response, responses
                        )

    # --- rendering --------------------------------------------------------------------

    def _base(
        self,
        obj: ContentObject,
        context: _Context,
        *,
        tags: Iterable[Tag],
        assignment: TaxonomyContentAssignment | None,
        search_matches: list[SearchContentMatch] | None,
        processing: bool,
    ) -> dict[str, Any]:
        collection = None
        if obj.collection_memberships:
            parent = obj.collection_memberships[0].collection
            collection = CollectionParentResponse(
                id=parent.id, slug=parent.slug, title=parent.title
            )
        return {
            "id": obj.id,
            "slug": obj.slug,
            "kind": obj.kind,
            "media_type": obj.media_type,
            "title": obj.title,
            "source_filename": obj.source_filename,
            "taxonomy_category": taxonomy_category_response(assignment),
            "tags": [tag_response(tag) for tag in tags],
            "is_favorite": obj.is_favorite,
            "sort_order": obj.sort_order,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
            "download_url": f"{self.api_prefix}/notes/{obj.slug}/download",
            "collection": collection,
            "search_matches": search_matches or [],
            "processing": processing,
        }

    def _is_processing(self, obj: ContentObject, context: _Context) -> bool:
        if obj.id in context.processing:
            return True
        return any(child.id in context.processing for child in _loaded_children(obj))

    def _full_card(
        self,
        obj: ContentObject,
        context: _Context,
        *,
        search_matches: list[SearchContentMatch] | None = None,
    ) -> NoteCardResponse:
        object_source = context.object_sources.get(obj.id)
        return NoteCardResponse(
            **self._base(
                obj,
                context,
                tags=context.tags.get(obj.id, []),
                assignment=context.assignments.get(obj.id),
                search_matches=search_matches,
                processing=self._is_processing(obj, context),
            ),
            source=object_source,
            deferred_link_snapshots=self._deferred_link_snapshots(obj, context),
            assets=[self._full_asset(obj, asset, context, object_source) for asset in obj.assets],
            items=[self._full_card(child, context) for child in visible_children(obj)],
        )

    def _full_asset(
        self,
        obj: ContentObject,
        asset: ContentAsset,
        context: _Context,
        object_source: SourceMetadataResponse | None,
    ) -> NoteAssetResponse:
        asset_url = self.asset_url(obj, asset)
        refs = context.artifact_refs.get(asset.id, {})
        preview = context.previews.get(asset.id)
        is_text = asset.media_type == "text"
        markdown, pdf, html = refs.get("markdown"), refs.get("pdf"), refs.get("webpage_html")
        own_markdown = is_markdown_file(asset.filename, asset.mime_type)
        own_pdf = is_pdf_file(asset.filename, asset.mime_type)
        views: list[SnapshotViewResponse] = []
        if not is_text:
            if markdown is not None or own_markdown:
                url = markdown.url if markdown is not None else asset_url
                views.append(SnapshotViewResponse(kind="markdown", label="MD", url=url))
            if pdf is not None or own_pdf:
                url = pdf.url if pdf is not None else asset_url
                views.append(SnapshotViewResponse(kind="pdf", label="PDF", url=url))
            if html is not None:
                views.append(
                    SnapshotViewResponse(kind="webpage_html", label="Website", url=html.url)
                )
            views.reverse()
        return NoteAssetResponse(
            id=asset.id,
            role=asset.role,
            media_type=asset.media_type,  # type: ignore[arg-type]
            filename=asset.filename,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            url=asset_url,
            text_content=asset.text_content,
            thumbnail_url=(
                f"{asset_url}/thumbnail" if "thumbnail" in refs and not is_text else None
            ),
            thumbnail_text=preview.thumbnail_text if preview is not None and not is_text else None,
            markdown_url=(
                markdown.url
                if markdown is not None
                else (asset_url if own_markdown and not is_text else None)
            ),
            pdf_url=pdf.url if pdf is not None else (asset_url if own_pdf else None),
            html_url=html.url if html is not None else None,
            snapshot_views=views,
            image_width=asset.image_width,
            image_height=asset.image_height,
            source=context.asset_sources.get(asset.id) or object_source,
        )

    def _summary_card(
        self,
        obj: ContentObject,
        context: _Context,
        *,
        top_level: bool,
        search_matches: list[SearchContentMatch] | None = None,
    ) -> NoteCardResponse:
        children = visible_children(obj)[:CARD_LIST_COLLECTION_ITEM_LIMIT] if top_level else []
        return NoteCardResponse(
            **self._base(
                obj,
                context,
                tags=context.tags.get(obj.id, []) if top_level else [],
                assignment=context.assignments.get(obj.id) if top_level else None,
                search_matches=search_matches,
                processing=self._is_processing(obj, context),
            ),
            source=None,
            deferred_link_snapshots=None,
            assets=[
                self._summary_asset(obj, asset, context)
                for asset in _card_preview_assets(obj.assets)
            ],
            items=[self._summary_card(child, context, top_level=False) for child in children],
        )

    def _summary_asset(
        self, obj: ContentObject, asset: ContentAsset, context: _Context
    ) -> NoteAssetResponse:
        asset_url = self.asset_url(obj, asset)
        preview = context.previews.get(asset.id)
        is_text = asset.media_type == "text"
        return NoteAssetResponse(
            id=asset.id,
            role=asset.role,
            media_type=asset.media_type,  # type: ignore[arg-type]
            filename=asset.filename,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            url=asset_url,
            text_content=asset.text_content,
            thumbnail_url=(
                f"{asset_url}/thumbnail"
                if preview is not None and preview.has_thumbnail and not is_text
                else None
            ),
            thumbnail_text=(
                preview.thumbnail_text
                if preview is not None and preview.thumbnail_text and not is_text
                else None
            ),
            image_width=asset.image_width,
            image_height=asset.image_height,
        )

    def _deferred_link_snapshots(
        self, obj: ContentObject, context: _Context
    ) -> DeferredLinkSnapshotsResponse | None:
        if obj.media_type != "link" or obj.id in context.decided:
            return None
        expires_at = obj.created_at + DEFERRED_LINK_SNAPSHOT_TTL
        if datetime.now(UTC) >= expires_at:
            return None
        text_links = text_link_urls(obj)
        if len(text_links) <= AUTO_LINK_SNAPSHOT_LIMIT:
            return None
        existing = set(link_asset_urls(obj))
        remaining = [url for url in text_links if url not in existing]
        if not remaining:
            return None
        return DeferredLinkSnapshotsResponse(
            total_links=len(text_links),
            processed_links=len(text_links) - len(remaining),
            remaining_links=len(remaining),
            expires_at=expires_at,
            status="pending",
        )


def _card_preview_assets(assets: Sequence[ContentAsset]) -> list[ContentAsset]:
    ordered = sorted(assets, key=lambda asset: asset.created_at)
    text_assets = [asset for asset in ordered if asset.media_type == "text"][:1]
    visual_assets = [asset for asset in ordered if asset.media_type != "text"]
    return (text_assets + visual_assets)[:CARD_LIST_ASSET_LIMIT]


def _loaded_children(obj: ContentObject) -> list[ContentObject]:
    if obj.kind != "collection":
        return []
    return [item.content_object for item in obj.collection_items]


def _collect_tree(
    objects: Sequence[ContentObject], *, max_depth: int | None
) -> list[ContentObject]:
    seen: dict[str, ContentObject] = {}

    def visit(obj: ContentObject, depth: int) -> None:
        if obj.id in seen:
            return
        seen[obj.id] = obj
        if max_depth is not None and depth >= max_depth:
            return
        for child in visible_children(obj):
            visit(child, depth + 1)

    for obj in objects:
        visit(obj, 0)
    return list(seen.values())
