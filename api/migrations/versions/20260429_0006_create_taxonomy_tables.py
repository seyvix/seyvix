"""create taxonomy tables

Revision ID: 20260429_0006
Revises: 20260428_0005
Create Date: 2026-04-29 10:00:00

Legacy content_categories and content_objects.category_id are kept as deprecated schema artifacts.
Runtime application code should use taxonomy_categories and taxonomy_content_assignments instead.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260429_0006"
down_revision = "20260428_0005"
branch_labels = None
depends_on = None

SLUG_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def upgrade() -> None:
    op.create_table(
        "taxonomy_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("slug <> ''", name="ck_taxonomy_categories_slug_not_empty"),
        sa.CheckConstraint("name <> ''", name="ck_taxonomy_categories_name_not_empty"),
        sa.CheckConstraint("path <> ''", name="ck_taxonomy_categories_path_not_empty"),
        sa.CheckConstraint("depth >= 0", name="ck_taxonomy_categories_depth_non_negative"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_taxonomy_categories_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["taxonomy_categories.id"],
            name=op.f("fk_taxonomy_categories_parent_id_taxonomy_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_categories")),
        sa.UniqueConstraint("owner_user_id", "path", name="uq_taxonomy_categories_owner_path"),
        sa.UniqueConstraint(
            "owner_user_id",
            "parent_id",
            "slug",
            name="uq_taxonomy_categories_owner_parent_slug",
        ),
    )
    op.create_index(
        op.f("ix_taxonomy_categories_owner_user_id"),
        "taxonomy_categories",
        ["owner_user_id"],
    )
    op.create_index(op.f("ix_taxonomy_categories_parent_id"), "taxonomy_categories", ["parent_id"])
    op.create_index(
        op.f("ix_taxonomy_categories_sort_order"), "taxonomy_categories", ["sort_order"]
    )
    op.create_index(op.f("ix_taxonomy_categories_source"), "taxonomy_categories", ["source"])
    op.create_index(
        op.f("ix_taxonomy_categories_is_archived"),
        "taxonomy_categories",
        ["is_archived"],
    )
    op.create_index(
        "uq_taxonomy_categories_owner_root_slug",
        "taxonomy_categories",
        ["owner_user_id", "slug"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )

    op.create_table(
        "taxonomy_category_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("positive_examples", sa.JSON(), nullable=False),
        sa.Column("negative_examples", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["taxonomy_categories.id"],
            name=op.f("fk_taxonomy_category_profiles_category_id_taxonomy_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_category_profiles")),
        sa.UniqueConstraint("category_id", name="uq_taxonomy_profiles_category_id"),
    )
    op.create_index(
        op.f("ix_taxonomy_category_profiles_category_id"),
        "taxonomy_category_profiles",
        ["category_id"],
    )

    op.create_table(
        "taxonomy_content_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("assigned_by", sa.String(length=32), nullable=False),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("category_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("category_path_snapshot", sa.String(length=1024), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_taxonomy_content_assignments_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_taxonomy_content_assignments_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["taxonomy_categories.id"],
            name=op.f("fk_taxonomy_content_assignments_category_id_taxonomy_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_content_assignments")),
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_owner_user_id"),
        "taxonomy_content_assignments",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_content_object_id"),
        "taxonomy_content_assignments",
        ["content_object_id"],
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_category_id"),
        "taxonomy_content_assignments",
        ["category_id"],
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_status"),
        "taxonomy_content_assignments",
        ["status"],
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_assigned_by"),
        "taxonomy_content_assignments",
        ["assigned_by"],
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_is_current"),
        "taxonomy_content_assignments",
        ["is_current"],
    )
    op.create_index(
        "ix_taxonomy_assignments_owner_content",
        "taxonomy_content_assignments",
        ["owner_user_id", "content_object_id"],
    )
    op.create_index(
        "ix_taxonomy_assignments_owner_category",
        "taxonomy_content_assignments",
        ["owner_user_id", "category_id"],
    )
    op.create_index(
        "uq_taxonomy_assignments_current_content",
        "taxonomy_content_assignments",
        ["owner_user_id", "content_object_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "taxonomy_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_templates")),
        sa.UniqueConstraint("slug", name="uq_taxonomy_templates_slug"),
    )
    op.create_index(op.f("ix_taxonomy_templates_slug"), "taxonomy_templates", ["slug"])
    op.create_index(op.f("ix_taxonomy_templates_is_active"), "taxonomy_templates", ["is_active"])

    op.create_table(
        "taxonomy_template_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("profile_summary", sa.Text(), nullable=True),
        sa.Column("profile_keywords", sa.JSON(), nullable=False),
        sa.Column("profile_positive_examples", sa.JSON(), nullable=False),
        sa.Column("profile_negative_examples", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["taxonomy_templates.id"],
            name=op.f("fk_taxonomy_template_categories_template_id_taxonomy_templates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["taxonomy_template_categories.id"],
            name=op.f("fk_taxonomy_template_categories_parent_id_taxonomy_template_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_template_categories")),
        sa.UniqueConstraint("template_id", "path", name="uq_taxonomy_template_categories_path"),
    )
    op.create_index(
        op.f("ix_taxonomy_template_categories_template_id"),
        "taxonomy_template_categories",
        ["template_id"],
    )
    op.create_index(
        op.f("ix_taxonomy_template_categories_parent_id"),
        "taxonomy_template_categories",
        ["parent_id"],
    )

    _seed_templates()
    _migrate_legacy_categories()

    op.execute(
        "COMMENT ON TABLE content_categories IS "
        "'Deprecated legacy category table. Runtime taxonomy uses taxonomy_categories.'"
    )
    op.execute(
        "COMMENT ON COLUMN content_objects.category_id IS "
        "'Deprecated legacy category pointer. Runtime taxonomy uses taxonomy_content_assignments.'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN content_objects.category_id IS NULL")
    op.execute("COMMENT ON TABLE content_categories IS NULL")
    op.drop_index(
        op.f("ix_taxonomy_template_categories_parent_id"),
        table_name="taxonomy_template_categories",
    )
    op.drop_index(
        op.f("ix_taxonomy_template_categories_template_id"),
        table_name="taxonomy_template_categories",
    )
    op.drop_table("taxonomy_template_categories")
    op.drop_index(op.f("ix_taxonomy_templates_is_active"), table_name="taxonomy_templates")
    op.drop_index(op.f("ix_taxonomy_templates_slug"), table_name="taxonomy_templates")
    op.drop_table("taxonomy_templates")
    op.drop_index(
        "uq_taxonomy_assignments_current_content",
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        "ix_taxonomy_assignments_owner_category",
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        "ix_taxonomy_assignments_owner_content",
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_is_current"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_assigned_by"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_status"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_category_id"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_content_object_id"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_owner_user_id"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_table("taxonomy_content_assignments")
    op.drop_index(
        op.f("ix_taxonomy_category_profiles_category_id"),
        table_name="taxonomy_category_profiles",
    )
    op.drop_table("taxonomy_category_profiles")
    op.drop_index(
        "uq_taxonomy_categories_owner_root_slug",
        table_name="taxonomy_categories",
    )
    op.drop_index(op.f("ix_taxonomy_categories_is_archived"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_source"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_sort_order"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_parent_id"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_owner_user_id"), table_name="taxonomy_categories")
    op.drop_table("taxonomy_categories")


def _seed_templates() -> None:
    connection = op.get_bind()
    now = datetime.now(UTC)
    for slug, name, tree in (
        ("default", "Default", _default_template_tree()),
        ("developer", "Developer", _developer_template_tree()),
    ):
        template_id = str(uuid4())
        connection.execute(
            sa.text(
                """
                INSERT INTO taxonomy_templates
                    (id, slug, name, description, is_active, created_at, updated_at)
                VALUES
                    (:id, :slug, :name, :description, true, :created_at, :updated_at)
                """
            ),
            {
                "id": template_id,
                "slug": slug,
                "name": name,
                "description": f"{name} cold-start taxonomy template.",
                "created_at": now,
                "updated_at": now,
            },
        )
        parent_id_by_path: dict[str, str] = {}
        for item in _flatten_template_tree(tree):
            category_id = str(uuid4())
            parent_path = item["path"].rsplit("/", 1)[0] if "/" in item["path"] else None
            statement = sa.text(
                """
                    INSERT INTO taxonomy_template_categories
                        (
                            id, template_id, parent_id, slug, name, description, path, depth,
                            sort_order, profile_summary, profile_keywords,
                            profile_positive_examples, profile_negative_examples,
                            created_at, updated_at
                        )
                    VALUES
                        (
                            :id, :template_id, :parent_id, :slug, :name, :description, :path,
                            :depth, :sort_order, :profile_summary, :profile_keywords,
                            :profile_positive_examples, :profile_negative_examples,
                            :created_at, :updated_at
                        )
                    """
            ).bindparams(
                sa.bindparam("profile_keywords", type_=sa.JSON()),
                sa.bindparam("profile_positive_examples", type_=sa.JSON()),
                sa.bindparam("profile_negative_examples", type_=sa.JSON()),
            )
            connection.execute(
                statement,
                {
                    "id": category_id,
                    "template_id": template_id,
                    "parent_id": parent_id_by_path.get(parent_path) if parent_path else None,
                    "slug": item["slug"],
                    "name": item["name"],
                    "description": item["description"],
                    "path": item["path"],
                    "depth": item["depth"],
                    "sort_order": item["sort_order"],
                    "profile_summary": item["profile_summary"],
                    "profile_keywords": item["profile_keywords"],
                    "profile_positive_examples": item["profile_positive_examples"],
                    "profile_negative_examples": item["profile_negative_examples"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
            parent_id_by_path[item["path"]] = category_id


def _migrate_legacy_categories() -> None:
    connection = op.get_bind()
    legacy_rows = list(
        connection.execute(
            sa.text(
                """
                SELECT id, owner_user_id, parent_id, name, slug, path, created_at
                FROM content_categories
                ORDER BY owner_user_id, path, created_at
                """
            )
        ).mappings()
    )
    if not legacy_rows:
        return

    rows_by_id = {row["id"]: row for row in legacy_rows}
    children_by_parent: dict[str | None, list[sa.RowMapping]] = defaultdict(list)
    for row in legacy_rows:
        parent_id = row["parent_id"] if row["parent_id"] in rows_by_id else None
        if parent_id is not None and rows_by_id[parent_id]["owner_user_id"] != row["owner_user_id"]:
            parent_id = None
        children_by_parent[parent_id].append(row)

    migrated: dict[str, dict[str, str]] = {}
    used_paths: dict[str, set[str]] = defaultdict(set)
    used_parent_slugs: dict[tuple[str, str | None], set[str]] = defaultdict(set)
    now = datetime.now(UTC)

    def migrate_row(row: sa.RowMapping, parent_new: dict[str, str] | None) -> None:
        owner_user_id = row["owner_user_id"]
        parent_new_id = parent_new["id"] if parent_new is not None else None
        parent_path = parent_new["path"] if parent_new is not None else ""
        slug = _legacy_slug(row["slug"], row["name"])
        slug = _dedupe_slug(
            slug,
            used_parent_slugs[(owner_user_id, parent_new_id)],
            stable_suffix=row["id"][:8],
        )
        path = f"{parent_path}/{slug}".strip("/")
        if path in used_paths[owner_user_id]:
            slug = _dedupe_slug(
                slug,
                used_parent_slugs[(owner_user_id, parent_new_id)],
                stable_suffix=row["id"][-8:],
            )
            path = f"{parent_path}/{slug}".strip("/")
        used_paths[owner_user_id].add(path)
        used_parent_slugs[(owner_user_id, parent_new_id)].add(slug)

        category_id = str(uuid4())
        created_at = row["created_at"] or now
        connection.execute(
            sa.text(
                """
                INSERT INTO taxonomy_categories
                    (
                        id, owner_user_id, parent_id, slug, name, description, path, depth,
                        sort_order, source, is_system, is_archived, created_at, updated_at
                    )
                VALUES
                    (
                        :id, :owner_user_id, :parent_id, :slug, :name, :description, :path,
                        :depth, 100, 'legacy_migration', false, false, :created_at, :updated_at
                    )
                """
            ),
            {
                "id": category_id,
                "owner_user_id": owner_user_id,
                "parent_id": parent_new_id,
                "slug": slug,
                "name": row["name"],
                "description": None,
                "path": path,
                "depth": path.count("/"),
                "created_at": created_at,
                "updated_at": now,
            },
        )
        statement = sa.text(
            """
                INSERT INTO taxonomy_category_profiles
                    (
                        id, category_id, summary, keywords, positive_examples,
                        negative_examples, created_at, updated_at
                    )
                VALUES
                    (
                        :id, :category_id, :summary, :keywords, :positive_examples,
                        :negative_examples, :created_at, :updated_at
                    )
                """
        ).bindparams(
            sa.bindparam("keywords", type_=sa.JSON()),
            sa.bindparam("positive_examples", type_=sa.JSON()),
            sa.bindparam("negative_examples", type_=sa.JSON()),
        )
        connection.execute(
            statement,
            {
                "id": str(uuid4()),
                "category_id": category_id,
                "summary": f"Legacy category migrated from {row['name']}.",
                "keywords": [slug],
                "positive_examples": [f"Content previously filed under {row['name']}"],
                "negative_examples": ["Unrelated content"],
                "created_at": now,
                "updated_at": now,
            },
        )
        migrated[row["id"]] = {"id": category_id, "name": row["name"], "path": path}
        for child in sorted(children_by_parent.get(row["id"], []), key=lambda item: item["path"]):
            migrate_row(child, migrated[row["id"]])

    for root in sorted(children_by_parent.get(None, []), key=lambda item: item["path"]):
        migrate_row(root, None)

    content_rows = list(
        connection.execute(
            sa.text(
                """
                SELECT id, owner_user_id, category_id, created_at, updated_at
                FROM content_objects
                WHERE category_id IS NOT NULL
                ORDER BY owner_user_id, created_at
                """
            )
        ).mappings()
    )
    for content in content_rows:
        category = migrated.get(content["category_id"])
        if category is None:
            continue
        created_at = content["updated_at"] or content["created_at"] or now
        statement = sa.text(
            """
                INSERT INTO taxonomy_content_assignments
                    (
                        id, owner_user_id, content_object_id, category_id, status, confidence,
                        reasoning, assigned_by, alternatives, category_name_snapshot,
                        category_path_snapshot, is_current, created_at, updated_at
                    )
                VALUES
                    (
                        :id, :owner_user_id, :content_object_id, :category_id, 'accepted',
                        1.0, 'Migrated from legacy content_objects.category_id', 'migration',
                        :alternatives, :category_name_snapshot, :category_path_snapshot, true,
                        :created_at, :updated_at
                    )
                """
        ).bindparams(sa.bindparam("alternatives", type_=sa.JSON()))
        connection.execute(
            statement,
            {
                "id": str(uuid4()),
                "owner_user_id": content["owner_user_id"],
                "content_object_id": content["id"],
                "category_id": category["id"],
                "alternatives": [],
                "category_name_snapshot": category["name"],
                "category_path_snapshot": category["path"],
                "created_at": created_at,
                "updated_at": now,
            },
        )


def _legacy_slug(slug: str | None, name: str) -> str:
    candidate = (slug or "").strip()
    if SLUG_PATTERN.fullmatch(candidate):
        return candidate
    return _slugify(name)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "category"


def _dedupe_slug(slug: str, used: set[str], *, stable_suffix: str) -> str:
    if slug not in used:
        return slug
    candidate = f"{slug}-{stable_suffix}"
    counter = 2
    while candidate in used:
        candidate = f"{slug}-{stable_suffix}-{counter}"
        counter += 1
    return candidate


def _profile(name: str) -> dict[str, object]:
    keyword = _slugify(name)
    return {
        "profile_summary": f"Materials related to {name}.",
        "profile_keywords": [keyword],
        "profile_positive_examples": [f"example item about {name}"],
        "profile_negative_examples": [f"item unrelated to {name}"],
    }


def _node(name: str, children: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {"name": name, "children": children or []}


def _flatten_template_tree(tree: list[dict[str, object]]) -> list[dict[str, object]]:
    flattened: list[dict[str, object]] = []

    def visit(nodes: list[dict[str, object]], parent_path: str, depth: int) -> None:
        for index, node in enumerate(nodes):
            name = str(node["name"])
            slug = _slugify(name)
            path = f"{parent_path}/{slug}".strip("/")
            flattened.append(
                {
                    "slug": slug,
                    "name": name,
                    "description": f"Materials related to {name}.",
                    "path": path,
                    "depth": depth,
                    "sort_order": index * 10,
                    **_profile(name),
                }
            )
            visit(node["children"], path, depth + 1)  # type: ignore[arg-type]

    visit(tree, "", 0)
    return flattened


def _default_template_tree() -> list[dict[str, object]]:
    return [
        _node("Inbox"),
        _node("AI", [_node("LLM"), _node("Agents"), _node("Machine Learning"), _node("Tools")]),
        _node(
            "Programming",
            [
                _node("Python"),
                _node("JavaScript"),
                _node("Backend"),
                _node("Frontend"),
                _node("Databases"),
                _node("Architecture"),
            ],
        ),
        _node("Data", [_node("Analytics"), _node("Data Engineering"), _node("Visualization")]),
        _node(
            "Business", [_node("Product"), _node("Marketing"), _node("Sales"), _node("Strategy")]
        ),
        _node("Resources", [_node("Articles"), _node("Books"), _node("Videos"), _node("Tools")]),
        _node("Personal", [_node("Ideas"), _node("Tasks"), _node("Learning"), _node("Notes")]),
    ]


def _developer_template_tree() -> list[dict[str, object]]:
    return [
        _node("Inbox"),
        _node("AI", [_node("LLM"), _node("Agents"), _node("RAG"), _node("Tools")]),
        _node(
            "Programming",
            [
                _node("Python"),
                _node("JavaScript"),
                _node("Backend"),
                _node("APIs"),
                _node("Architecture"),
                _node("Testing"),
            ],
        ),
        _node("Databases", [_node("PostgreSQL"), _node("Redis"), _node("Vector Search")]),
        _node("DevOps", [_node("Docker"), _node("CI/CD"), _node("Observability")]),
        _node("Product", [_node("Ideas"), _node("UX"), _node("Strategy")]),
        _node("Resources", [_node("Articles"), _node("Videos"), _node("Tools")]),
    ]
