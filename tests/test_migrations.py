from pathlib import Path


def test_alembic_env_uses_application_metadata() -> None:
    env_path = Path(__file__).resolve().parents[1] / "migrations" / "env.py"

    content = env_path.read_text(encoding="utf-8")

    assert "from app.core.database import Base" in content
    assert "target_metadata = Base.metadata" in content
