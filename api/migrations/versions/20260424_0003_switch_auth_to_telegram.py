"""switch auth to telegram login

Revision ID: 20260424_0003
Revises: 20260424_0002
Create Date: 2026-04-24 16:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260424_0003"
down_revision = "20260424_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_id", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("telegram_username", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("telegram_photo_url", sa.String(length=2048), nullable=True))
    op.execute("UPDATE users SET telegram_id = id WHERE telegram_id IS NULL")
    op.alter_column("users", "telegram_id", nullable=False)
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")

    op.add_column(
        "auth_sessions", sa.Column("login_code_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "auth_sessions",
        sa.Column("login_code_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("login_code_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_auth_sessions_login_code_hash"),
        "auth_sessions",
        ["login_code_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_sessions_login_code_hash"), table_name="auth_sessions")
    op.drop_column("auth_sessions", "login_code_used_at")
    op.drop_column("auth_sessions", "login_code_expires_at")
    op.drop_column("auth_sessions", "login_code_hash")

    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.execute(
        "UPDATE users "
        "SET email = telegram_id || '@telegram.local', password_hash = '' "
        "WHERE email IS NULL"
    )
    op.alter_column("users", "password_hash", nullable=False)
    op.alter_column("users", "email", nullable=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_column("users", "telegram_photo_url")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_id")
