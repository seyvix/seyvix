from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import UserContext
from telegram_bot.infrastructure.backend_client import BackendError, BackendUnavailableError
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.keyboards.modes import mode_keyboard
from telegram_bot.services.state import BotStateService
from telegram_bot.texts.common import BACKEND_UNAVAILABLE
from telegram_bot.texts.modes import FINISH_DONE, FINISH_EMPTY, mode_enabled_text, mode_menu_text

router = Router(name="modes")
BACKEND_ERRORS = (BackendUnavailableError, BackendError)


@router.message(Command("mode"))
async def mode_handler(
    message: Message,
    user: UserContext,
    state_service: BotStateService,
    web_app_url: str | None = None,
) -> None:
    try:
        state = await state_service.get_state(user.telegram_user_id)
    except BACKEND_ERRORS:
        await message.answer(BACKEND_UNAVAILABLE)
        return
    await message.answer(
        mode_menu_text(state.mode),
        reply_markup=mode_keyboard(
            current_mode=state.mode,
            has_active_collection=state.active_collection_id is not None,
            web_app_url=web_app_url,
        ),
    )


@router.callback_query(F.data.startswith("mode:"))
async def mode_callback_handler(
    callback: CallbackQuery,
    user: UserContext,
    state_service: BotStateService,
    web_app_url: str | None = None,
) -> None:
    try:
        mode = BotMode((callback.data or "").removeprefix("mode:"))
    except ValueError:
        await callback.answer("Неизвестный режим.")
        return
    try:
        state = await state_service.set_mode(user.telegram_user_id, mode)
    except BACKEND_ERRORS:
        await callback.answer(BACKEND_UNAVAILABLE, show_alert=True)
        return
    await callback.answer(mode_enabled_text(mode))
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            mode_menu_text(state.mode),
            reply_markup=mode_keyboard(
                current_mode=state.mode,
                has_active_collection=state.active_collection_id is not None,
                web_app_url=web_app_url,
            ),
        )


@router.message(Command("finish"))
async def finish_handler(
    message: Message,
    user: UserContext,
    state_service: BotStateService,
    web_app_url: str | None = None,
) -> None:
    try:
        finished, _ = await state_service.finish_collection(user.telegram_user_id)
    except BACKEND_ERRORS:
        await message.answer(BACKEND_UNAVAILABLE)
        return
    await message.answer(
        FINISH_DONE if finished else FINISH_EMPTY,
        reply_markup=web_app_keyboard(web_app_url),
    )


@router.callback_query(F.data == "collection:finish")
async def finish_callback_handler(
    callback: CallbackQuery,
    user: UserContext,
    state_service: BotStateService,
    web_app_url: str | None = None,
) -> None:
    try:
        finished, state = await state_service.finish_collection(user.telegram_user_id)
    except BACKEND_ERRORS:
        await callback.answer(BACKEND_UNAVAILABLE, show_alert=True)
        return
    await callback.answer(FINISH_DONE if finished else FINISH_EMPTY)
    if finished and isinstance(callback.message, Message):
        await callback.message.edit_text(
            mode_menu_text(state.mode),
            reply_markup=mode_keyboard(
                current_mode=state.mode,
                has_active_collection=False,
                web_app_url=web_app_url,
            ),
        )
