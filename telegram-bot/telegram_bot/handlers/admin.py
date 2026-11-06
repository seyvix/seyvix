"""Admin access commands: /allow, /deny, /access (the backend re-checks admin rights)."""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from telegram_bot.bot.middlewares import UserStatusCache
from telegram_bot.domain.models import AccessGrant, UserContext
from telegram_bot.infrastructure.backend_client import (
    BackendError,
    BackendUnavailableError,
    HttpSeyvixBackend,
)
from telegram_bot.texts.common import BACKEND_UNAVAILABLE

router = Router(name="admin")

NOT_ADMIN = "Эта команда доступна только администраторам."
ALLOW_USAGE = "Использование: /allow &lt;telegram_id|@username&gt; [заметка]"
DENY_USAGE = "Использование: /deny &lt;telegram_id|@username&gt;"
MAX_LISTED = 50


def parse_target(raw: str) -> tuple[int | None, str | None] | None:
    """`123` → (123, None); `@name` or `name` → (None, "name"); invalid → None."""
    value = raw.strip()
    if value.isdecimal():
        number = int(value)
        return (number, None) if number > 0 else None
    username = value.removeprefix("@")
    if 3 <= len(username) <= 32 and all(ch.isalnum() or ch == "_" for ch in username):
        return None, username.casefold()
    return None


def _label(grant: AccessGrant) -> str:
    parts = []
    if grant.telegram_user_id is not None:
        parts.append(f"<code>{grant.telegram_user_id}</code>")
    if grant.username:
        parts.append(f"@{escape(grant.username)}")
    if grant.display_name:
        parts.append(escape(grant.display_name))
    if grant.note:
        parts.append(f"— {escape(grant.note)}")
    return " ".join(parts)


def _error_text(exc: BackendError) -> str:
    if exc.code == "admin_required":
        return NOT_ADMIN
    if exc.code == "access_grant_exists":
        return "У этого пользователя уже есть доступ."
    if exc.code == "access_grant_not_found":
        return "Такой записи в списке доступа нет."
    return f"Не получилось: {escape(exc.message)}"


@router.message(Command("allow"))
async def allow_handler(
    message: Message,
    command: CommandObject,
    user: UserContext,
    backend: HttpSeyvixBackend,
    status_cache: UserStatusCache,
) -> None:
    if not user.is_admin:
        await message.answer(NOT_ADMIN)
        return
    target_raw, _, note = (command.args or "").strip().partition(" ")
    target = parse_target(target_raw) if target_raw else None
    if target is None:
        await message.answer(ALLOW_USAGE)
        return
    telegram_user_id, username = target
    try:
        grant = await backend.grant_access(
            actor_telegram_id=user.telegram_user_id,
            telegram_user_id=telegram_user_id,
            username=username,
            note=note.strip() or None,
        )
    except BackendUnavailableError:
        await message.answer(BACKEND_UNAVAILABLE)
        return
    except BackendError as exc:
        await message.answer(_error_text(exc))
        return
    # None (username target) clears the whole cache: we don't know which id it maps to.
    status_cache.invalidate(telegram_user_id)
    await message.answer(f"Доступ открыт: {_label(grant)}")


@router.message(Command("deny"))
async def deny_handler(
    message: Message,
    command: CommandObject,
    user: UserContext,
    backend: HttpSeyvixBackend,
    status_cache: UserStatusCache,
) -> None:
    if not user.is_admin:
        await message.answer(NOT_ADMIN)
        return
    target = parse_target(command.args or "") if command.args else None
    if target is None:
        await message.answer(DENY_USAGE)
        return
    telegram_user_id, username = target
    try:
        revoked = await backend.revoke_access(
            actor_telegram_id=user.telegram_user_id,
            telegram_user_id=telegram_user_id,
            username=username,
        )
    except BackendUnavailableError:
        await message.answer(BACKEND_UNAVAILABLE)
        return
    except BackendError as exc:
        await message.answer(_error_text(exc))
        return
    # None (username target) clears the whole cache: we don't know which id it maps to.
    status_cache.invalidate(telegram_user_id)
    await message.answer(f"Доступ закрыт. Завершено сессий: {revoked}.")


@router.message(Command("access"))
async def access_handler(
    message: Message,
    user: UserContext,
    backend: HttpSeyvixBackend,
) -> None:
    if not user.is_admin:
        await message.answer(NOT_ADMIN)
        return
    try:
        access = await backend.list_access(actor_telegram_id=user.telegram_user_id)
    except BackendUnavailableError:
        await message.answer(BACKEND_UNAVAILABLE)
        return
    except BackendError as exc:
        await message.answer(_error_text(exc))
        return
    mode = "открытый (вход для всех)" if access.mode == "open" else "по списку"
    lines = [
        f"Режим доступа: {mode}",
        "Администраторы: " + (", ".join(f"<code>{a}</code>" for a in access.admins) or "—"),
        "",
    ]
    if access.items:
        lines.append(f"Разрешено ({len(access.items)}):")
        lines.extend(f"• {_label(grant)}" for grant in access.items[:MAX_LISTED])
        if len(access.items) > MAX_LISTED:
            lines.append(f"…и ещё {len(access.items) - MAX_LISTED} — полный список в приложении.")
    else:
        lines.append("Список доступа пуст.")
    await message.answer("\n".join(lines))
