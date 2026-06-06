from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import UserContext
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.keyboards.modes import mode_keyboard
from telegram_bot.services.modes import ModeService
from telegram_bot.texts.common import AUTH_REQUIRED
from telegram_bot.texts.modes import FINISH_DONE, FINISH_EMPTY, mode_enabled_text, mode_menu_text

router = Router(name="modes")


@router.message(Command("mode"))
async def mode_handler(
    message: Message,
    mode_service: ModeService,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
    telegram_user_id: str | None = None,
) -> None:
    if user_context is None or not user_context.linked or telegram_user_id is None:
        await message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return
    state = await mode_service.get_state(telegram_user_id)
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
    mode_service: ModeService,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
    telegram_user_id: str | None = None,
) -> None:
    if user_context is None or not user_context.linked or telegram_user_id is None:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return
    raw_mode = (callback.data or "").removeprefix("mode:")
    mode = BotMode(raw_mode)
    state = await mode_service.set_mode(telegram_user_id, mode)
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
    mode_service: ModeService,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
    telegram_user_id: str | None = None,
) -> None:
    if user_context is None or not user_context.linked or telegram_user_id is None:
        await message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return
    state = await mode_service.get_state(telegram_user_id)
    if state.active_collection_id is None:
        await message.answer(FINISH_EMPTY, reply_markup=web_app_keyboard(web_app_url))
        return
    await mode_service.finish_collection(telegram_user_id)
    await message.answer(FINISH_DONE, reply_markup=web_app_keyboard(web_app_url))


@router.callback_query(F.data == "collection:finish")
async def finish_callback_handler(
    callback: CallbackQuery,
    mode_service: ModeService,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
    telegram_user_id: str | None = None,
) -> None:
    if user_context is None or not user_context.linked or telegram_user_id is None:
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return
    state = await mode_service.get_state(telegram_user_id)
    if state.active_collection_id is None:
        await callback.answer(FINISH_EMPTY)
        return
    finished = await mode_service.finish_collection(telegram_user_id)
    await callback.answer(FINISH_DONE)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            mode_menu_text(finished.mode),
            reply_markup=mode_keyboard(
                current_mode=finished.mode,
                has_active_collection=False,
                web_app_url=web_app_url,
            ),
        )
