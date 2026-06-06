from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState


class PostgresBotStateRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def ensure_schema(self) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS telegram_bot_states (
                    telegram_user_id text PRIMARY KEY,
                    mode text NOT NULL DEFAULT 'auto',
                    active_collection_id text,
                    auto_group_collection_id text,
                    auto_group_last_message_at timestamptz,
                    manual_collection_started_at timestamptz,
                    manual_collection_last_item_at timestamptz,
                    manual_collection_reminder_sent_at timestamptz,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """)

    async def get_or_create(self, telegram_user_id: str) -> BotState:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO telegram_bot_states (telegram_user_id)
                VALUES ($1)
                ON CONFLICT (telegram_user_id) DO NOTHING
                """,
                telegram_user_id,
            )
            row = await connection.fetchrow(
                "SELECT * FROM telegram_bot_states WHERE telegram_user_id = $1",
                telegram_user_id,
            )
        if row is None:
            raise RuntimeError("telegram_bot_states row was not created.")
        return _row_to_state(row)

    async def save(self, state: BotState) -> BotState:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE telegram_bot_states
                SET mode = $2,
                    active_collection_id = $3,
                    auto_group_collection_id = $4,
                    auto_group_last_message_at = $5,
                    manual_collection_started_at = $6,
                    manual_collection_last_item_at = $7,
                    manual_collection_reminder_sent_at = $8,
                    updated_at = $9
                WHERE telegram_user_id = $1
                RETURNING *
                """,
                state.telegram_user_id,
                state.mode.value,
                state.active_collection_id,
                state.auto_group_collection_id,
                state.auto_group_last_message_at,
                state.manual_collection_started_at,
                state.manual_collection_last_item_at,
                state.manual_collection_reminder_sent_at,
                state.updated_at,
            )
        if row is None:
            raise RuntimeError("telegram_bot_states row was not found.")
        return _row_to_state(row)

    async def list_manual_collections(self) -> list[BotState]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("""
                SELECT *
                FROM telegram_bot_states
                WHERE mode = 'manual_collection'
                  AND active_collection_id IS NOT NULL
                """)
        return [_row_to_state(row) for row in rows]


async def create_state_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=5)


def _row_to_state(row: asyncpg.Record) -> BotState:
    values: dict[str, Any] = dict(row)
    return BotState(
        telegram_user_id=values["telegram_user_id"],
        mode=BotMode(values["mode"]),
        active_collection_id=values["active_collection_id"],
        auto_group_collection_id=values["auto_group_collection_id"],
        auto_group_last_message_at=_aware(values["auto_group_last_message_at"]),
        manual_collection_started_at=_aware(values["manual_collection_started_at"]),
        manual_collection_last_item_at=_aware(values["manual_collection_last_item_at"]),
        manual_collection_reminder_sent_at=_aware(values["manual_collection_reminder_sent_at"]),
        created_at=_aware(values["created_at"]) or datetime.now(UTC),
        updated_at=_aware(values["updated_at"]) or datetime.now(UTC),
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
