from pathlib import Path


def test_alembic_env_uses_application_metadata() -> None:
    env_path = Path(__file__).resolve().parents[1] / "migrations" / "env.py"

    content = env_path.read_text(encoding="utf-8")

    assert "from app.core.database import Base" in content
    assert "target_metadata = Base.metadata" in content


def test_taxonomy_migration_defines_tables_and_legacy_copy() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260429_0006_create_taxonomy_tables.py"
    )

    content = migration_path.read_text(encoding="utf-8")

    assert '"taxonomy_categories"' in content
    assert '"taxonomy_category_profiles"' in content
    assert '"taxonomy_content_assignments"' in content
    assert '"taxonomy_templates"' in content
    assert '"taxonomy_template_categories"' in content
    assert "legacy_migration" in content
    assert "Migrated from legacy content_objects.category_id" in content
    assert "Deprecated legacy category table" in content
