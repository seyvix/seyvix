"""Client for the Seyvix internal Telegram API (the bot's only persistence)."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import (
    AccessGrant,
    AccessList,
    BotState,
    InboundMaterial,
    SavedMaterial,
    UserContext,
)

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY_SECONDS = 0.5
# Only retried when the request certainly was not processed (connection never established,
# or the API answered "not ready"), so retries can never create duplicate notes.
_SAFE_RETRY_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# 502/503: proxy could not reach the API / API not ready. 504 may mean "processed slowly".
_RETRY_STATUSES = {502, 503}


class BackendUnavailableError(Exception):
    """The API could not be reached (or timed out) after retries."""


class BackendError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class UploadFile:
    path: Path
    filename: str
    mime_type: str | None

    def open(self) -> BinaryIO:
        return self.path.open("rb")


@dataclass(frozen=True, slots=True)
class IngestItem:
    material: InboundMaterial
    file_index: int | None


class HttpSeyvixBackend:
    def __init__(self, *, client: httpx.AsyncClient, base_url: str, internal_token: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {internal_token}"}

    async def user_status(self, *, telegram_user_id: int, username: str | None) -> UserContext:
        params = {"username": username} if username else None
        payload = await self._json("GET", f"/users/{telegram_user_id}", params=params)
        return UserContext(
            telegram_user_id=telegram_user_id,
            allowed=bool(payload.get("allowed")),
            is_admin=bool(payload.get("is_admin")),
            linked=bool(payload.get("linked")),
            display_name=_str_or_none(payload.get("display_name")),
        )

    async def get_state(self, telegram_user_id: int) -> BotState:
        return _state(await self._json("GET", f"/state/{telegram_user_id}"))

    async def set_mode(self, telegram_user_id: int, mode: BotMode) -> BotState:
        payload = await self._json(
            "PUT",
            f"/state/{telegram_user_id}/mode",
            json={"mode": mode.value},
        )
        return _state(payload)

    async def finish_collection(self, telegram_user_id: int) -> tuple[bool, BotState]:
        payload = await self._json("POST", f"/state/{telegram_user_id}/finish")
        state = payload.get("state")
        return bool(payload.get("finished")), _state(state if isinstance(state, Mapping) else {})

    async def claim_reminders(self, *, idle_seconds: int) -> list[int]:
        payload = await self._json(
            "POST",
            "/reminders/claim",
            json={"idle_seconds": idle_seconds},
        )
        ids = payload.get("telegram_user_ids")
        return [int(item) for item in ids if isinstance(item, int)] if isinstance(ids, list) else []

    async def list_access(self, *, actor_telegram_id: int) -> AccessList:
        payload = await self._json(
            "GET",
            "/access",
            params={"actor_telegram_id": str(actor_telegram_id)},
        )
        raw_items = payload.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        admins = payload.get("admins")
        return AccessList(
            mode=str(payload.get("mode") or "allowlist"),
            admins=[int(item) for item in admins] if isinstance(admins, list) else [],
            items=[_grant(item) for item in items if isinstance(item, Mapping)],
        )

    async def grant_access(
        self,
        *,
        actor_telegram_id: int,
        telegram_user_id: int | None,
        username: str | None,
        note: str | None,
    ) -> AccessGrant:
        body: dict[str, Any] = {"actor_telegram_id": actor_telegram_id}
        if telegram_user_id is not None:
            body["telegram_user_id"] = telegram_user_id
        if username is not None:
            body["username"] = username
        if note:
            body["note"] = note
        return _grant(await self._json("POST", "/access", json=body))

    async def revoke_access(
        self,
        *,
        actor_telegram_id: int,
        telegram_user_id: int | None,
        username: str | None,
    ) -> int:
        body: dict[str, Any] = {"actor_telegram_id": actor_telegram_id}
        if telegram_user_id is not None:
            body["telegram_user_id"] = telegram_user_id
        if username is not None:
            body["username"] = username
        payload = await self._json("POST", "/access/revoke", json=body)
        revoked = payload.get("sessions_revoked")
        return revoked if isinstance(revoked, int) else 0

    async def ingest(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: str,
        groups: Sequence[Sequence[IngestItem]],
        files: Sequence[UploadFile],
    ) -> SavedMaterial:
        """One request per flush; files are streamed from disk by httpx."""
        payload = {
            "telegram_user_id": telegram_user_id,
            "telegram_chat_id": telegram_chat_id,
            "groups": [{"parts": [_part(item) for item in group]} for group in groups],
        }
        response = await self._request(
            "POST",
            "/ingest",
            data={"payload": json.dumps(payload, ensure_ascii=False)},
            upload_files=files,
        )
        body = _json_body(response)
        note = body.get("note")
        note_payload = note if isinstance(note, Mapping) else {}
        return SavedMaterial(
            title=_str_or_none(note_payload.get("title")) or "",
            id=_str_or_none(note_payload.get("id")),
            status=_str_or_none(body.get("status")) or "saved",
        )

    async def _json(self, method: str, path: str, **kwargs: Any) -> Mapping[str, Any]:
        return _json_body(await self._request(method, path, **kwargs))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        upload_files: Sequence[UploadFile] = (),
        **kwargs: Any,
    ) -> httpx.Response:
        url = f"{self.base_url}/integrations/telegram{path}"
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                with ExitStack() as stack:
                    # Files are reopened per attempt: httpx streams them from disk in chunks.
                    multipart = [
                        ("files", (file.filename, stack.enter_context(file.open()), file.mime_type))
                        for file in upload_files
                    ]
                    response = await self.client.request(
                        method,
                        url,
                        headers=self.headers,
                        files=multipart or None,
                        **kwargs,
                    )
            except _SAFE_RETRY_ERRORS as exc:
                if attempt == RETRY_ATTEMPTS:
                    raise BackendUnavailableError(str(exc)) from exc
                await _backoff(attempt, method=method, path=path, reason=type(exc).__name__)
                continue
            except httpx.HTTPError as exc:
                # E.g. a read timeout: the request may have been processed, never retry.
                raise BackendUnavailableError(str(exc)) from exc
            if response.status_code in _RETRY_STATUSES:
                if attempt == RETRY_ATTEMPTS:
                    raise BackendUnavailableError(f"backend answered {response.status_code}")
                await _backoff(attempt, method=method, path=path, reason=response.status_code)
                continue
            if response.is_error:
                raise _backend_error(response)
            return response
        raise BackendUnavailableError("retries exhausted")


async def _backoff(attempt: int, *, method: str, path: str, reason: object) -> None:
    delay = RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1) * (1 + random.random() / 2)
    logger.warning("Backend %s %s failed (%s); retry in %.1fs", method, path, reason, delay)
    await asyncio.sleep(delay)


def _backend_error(response: httpx.Response) -> BackendError:
    code, message = "http_error", response.reason_phrase
    try:
        error = response.json().get("error")
    except ValueError:
        error = None
    if isinstance(error, Mapping):
        code = str(error.get("code") or code)
        message = str(error.get("message") or message)
    return BackendError(response.status_code, code, message)


def _json_body(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BackendError(response.status_code, "invalid_json", "Invalid backend JSON") from exc
    if not isinstance(payload, Mapping):
        raise BackendError(response.status_code, "invalid_json", "Unexpected backend payload")
    return payload


def _part(item: IngestItem) -> dict[str, Any]:
    material = item.material
    part: dict[str, Any] = {
        "telegram_message_id": material.telegram_message_id,
        "material_type": material.material_type.value,
        "message_date": datetime.fromtimestamp(material.message_date, UTC).isoformat(),
    }
    if material.text is not None:
        part["text"] = material.text
    if material.caption is not None:
        part["caption"] = material.caption
    if material.source is not None:
        part["source"] = material.source.to_payload()
    if material.attachment is not None:
        part["filename"] = material.attachment.filename
        if material.attachment.mime_type is not None:
            part["mime_type"] = material.attachment.mime_type
    if item.file_index is not None:
        part["file_index"] = item.file_index
    return part


def _state(payload: Mapping[str, Any]) -> BotState:
    started = payload.get("manual_collection_started_at")
    try:
        mode = BotMode(str(payload.get("mode")))
    except ValueError:
        mode = BotMode.AUTO
    return BotState(
        telegram_user_id=int(payload.get("telegram_user_id") or 0),
        mode=mode,
        active_collection_id=_str_or_none(payload.get("active_collection_id")),
        manual_collection_started_at=(
            datetime.fromisoformat(started) if isinstance(started, str) else None
        ),
    )


def _grant(payload: Mapping[str, Any]) -> AccessGrant:
    telegram_user_id = payload.get("telegram_user_id")
    return AccessGrant(
        id=str(payload.get("id") or ""),
        telegram_user_id=telegram_user_id if isinstance(telegram_user_id, int) else None,
        username=_str_or_none(payload.get("username")),
        note=_str_or_none(payload.get("note")),
        display_name=_str_or_none(payload.get("display_name")),
        last_login_at=_str_or_none(payload.get("last_login_at")),
    )


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
