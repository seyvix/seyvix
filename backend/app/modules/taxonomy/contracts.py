from __future__ import annotations

from datetime import datetime

from app.shared.module_definitions import ModuleDefinition
from pydantic import BaseModel

MODULE = ModuleDefinition(
    name="taxonomy",
    description=(
        "User-owned semantic category trees, profiles, templates, and content assignment history."
    ),
    public_contracts=["taxonomy-category", "taxonomy-profile", "taxonomy-assignment"],
    plugin_capabilities=["taxonomy_reader", "taxonomy_writer"],
)


class TaxonomyCategoryRef(BaseModel):
    id: str
    owner_user_id: str
    name: str
    slug: str
    path: str
    depth: int
    is_archived: bool


class TaxonomyAssignmentRef(BaseModel):
    id: str
    owner_user_id: str
    content_object_id: str
    category_id: str
    category_name_snapshot: str
    category_path_snapshot: str
    status: str
    is_current: bool
    created_at: datetime
