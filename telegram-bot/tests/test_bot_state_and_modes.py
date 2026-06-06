from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState
from telegram_bot.services.modes import ModeService
from telegram_bot.services.reminders import ManualCollectionReminderService


class FakeStateRepository:
    def __init__(self) -> None:
        self.states: dict[str, BotState] = {}

    async def get_or_create(self, telegram_user_id: str) -> BotState:
        state = self.states.get(telegram_user_id)
        if state is None:
            now = datetime.now(UTC)
            state = BotState(
                telegram_user_id=telegram_user_id,
                mode=BotMode.AUTO,
                created_at=now,
                updated_at=now,
            )
            self.states[telegram_user_id] = state
        return state

    async def save(self, state: BotState) -> BotState:
        self.states[state.telegram_user_id] = state
        return state

    async def list_manual_collections(self) -> list[BotState]:
        return list(self.states.values())


def test_mode_service_defaults_to_auto_and_switches_interactively() -> None:
    async def scenario() -> None:
        repository = FakeStateRepository()
        service = ModeService(repository)

        initial = await service.get_state("100500")
        manual = await service.set_mode("100500", BotMode.MANUAL_COLLECTION)
        separate = await service.set_mode("100500", BotMode.SEPARATE)

        assert initial.mode == BotMode.AUTO
        assert manual.mode == BotMode.MANUAL_COLLECTION
        assert separate.mode == BotMode.SEPARATE
        assert separate.active_collection_id is None

    asyncio.run(scenario())


def test_finish_collection_returns_to_auto_and_clears_manual_state() -> None:
    async def scenario() -> None:
        repository = FakeStateRepository()
        service = ModeService(repository)
        opened = await service.set_mode("100500", BotMode.MANUAL_COLLECTION)
        opened = opened.with_manual_collection(
            collection_id="collection-1",
            now=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
        )
        await repository.save(opened)

        finished = await service.finish_collection("100500")

        assert finished.mode == BotMode.AUTO
        assert finished.active_collection_id is None
        assert finished.manual_collection_started_at is None
        assert finished.manual_collection_last_item_at is None
        assert finished.manual_collection_reminder_sent_at is None

    asyncio.run(scenario())


def test_manual_collection_reminder_is_due_once_after_configured_delay() -> None:
    async def scenario() -> None:
        repository = FakeStateRepository()
        service = ModeService(repository)
        reminder = ManualCollectionReminderService(
            repository,
            reminder_delay_seconds=1800,
        )
        started_at = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
        state = await service.set_mode("100500", BotMode.MANUAL_COLLECTION)
        await repository.save(
            state.with_manual_collection(collection_id="collection-1", now=started_at)
        )

        assert await reminder.due_states(now=started_at + timedelta(minutes=29)) == []

        due = await reminder.due_states(now=started_at + timedelta(minutes=30))
        assert [item.telegram_user_id for item in due] == ["100500"]

        marked = await reminder.mark_sent(due[0], now=started_at + timedelta(minutes=30))
        assert marked.manual_collection_reminder_sent_at == started_at + timedelta(minutes=30)
        assert await reminder.due_states(now=started_at + timedelta(hours=1)) == []

    asyncio.run(scenario())
