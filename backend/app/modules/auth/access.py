"""Allowlist access control shared by every login path, the admin API and the Telegram bot."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import String, cast, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.auth.models import AccessGrant, AuthSession, User
from app.modules.auth.schemas import AccessGrantResponse, AccessListResponse
from app.modules.auth.security import normalize_telegram_username

logger = get_logger(__name__)


class AccessDeniedError(Exception):
    def __init__(self, telegram_user_id: int, username: str | None = None) -> None:
        super().__init__(f"Telegram user {telegram_user_id} is not allowed")
        self.telegram_user_id = telegram_user_id
        self.username = username


class AdminRequiredError(Exception):
    pass


class AccessGrantExistsError(Exception):
    pass


class AccessGrantNotFoundError(Exception):
    pass


def is_admin_telegram_id(telegram_user_id: int | str | None) -> bool:
    if telegram_user_id is None:
        return False
    try:
        return int(telegram_user_id) in get_settings().admin_telegram_ids
    except ValueError:
        return False


def access_denied_details(telegram_user_id: int, username: str | None) -> list[dict[str, object]]:
    return [{"telegram_user_id": telegram_user_id, "username": username}]


class AccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_allowed(
        self,
        telegram_user_id: int,
        username: str | None,
        *,
        record_login: bool = True,
    ) -> None:
        """Raise AccessDeniedError unless the Telegram account may use Seyvix.

        Binds a matching username-only grant to the Telegram id. Changes are staged in the
        caller's transaction (no commit here) so they persist together with the login.
        """
        settings = get_settings()
        if settings.access_mode == "open" or is_admin_telegram_id(telegram_user_id):
            return
        now = datetime.now(UTC)
        values: dict[str, object] = {"last_login_at": now} if record_login else {}
        if values:
            granted = await self.session.scalar(
                update(AccessGrant)
                .where(AccessGrant.telegram_user_id == telegram_user_id)
                .values(**values)
                .returning(AccessGrant.id)
            )
        else:
            granted = await self.session.scalar(
                select(AccessGrant.id).where(AccessGrant.telegram_user_id == telegram_user_id)
            )
        if granted is not None:
            return
        normalized = _safe_username(username)
        if normalized is not None:
            bound = await self.session.scalar(
                update(AccessGrant)
                .where(AccessGrant.username == normalized, AccessGrant.telegram_user_id.is_(None))
                .values(telegram_user_id=telegram_user_id, **values)
                .returning(AccessGrant.id)
            )
            if bound is not None:
                logger.info("auth.access.username_grant_bound", grant_id=bound)
                return
        raise AccessDeniedError(telegram_user_id, username)

    async def is_allowed(self, telegram_user_id: int, username: str | None) -> bool:
        """Read-only variant of `ensure_allowed` (no binding, no last-login bookkeeping)."""
        settings = get_settings()
        if settings.access_mode == "open" or is_admin_telegram_id(telegram_user_id):
            return True
        conditions = [AccessGrant.telegram_user_id == telegram_user_id]
        normalized = _safe_username(username)
        if normalized is not None:
            conditions.append(
                (AccessGrant.username == normalized) & AccessGrant.telegram_user_id.is_(None)
            )
        grant_id = await self.session.scalar(select(AccessGrant.id).where(or_(*conditions)))
        return grant_id is not None

    async def list_grants(self) -> AccessListResponse:
        settings = get_settings()
        rows = await self.session.execute(
            select(AccessGrant, User.display_name)
            .outerjoin(User, User.telegram_id == cast(AccessGrant.telegram_user_id, String))
            .order_by(AccessGrant.created_at.desc())
        )
        return AccessListResponse(
            mode=settings.access_mode,
            admins=list(settings.admin_telegram_ids),
            items=[_grant_response(grant, display_name) for grant, display_name in rows.all()],
        )

    async def create_grant(
        self,
        *,
        telegram_user_id: int | None,
        username: str | None,
        note: str | None,
        created_by_telegram_id: int | None,
    ) -> AccessGrantResponse:
        normalized = normalize_telegram_username(username)
        if telegram_user_id is None and normalized is None:
            raise ValueError("Either telegram_user_id or username is required.")
        duplicate_conditions = []
        if telegram_user_id is not None:
            duplicate_conditions.append(AccessGrant.telegram_user_id == telegram_user_id)
        if normalized is not None:
            duplicate_conditions.append(AccessGrant.username == normalized)
        existing = await self.session.scalar(
            select(AccessGrant.id).where(or_(*duplicate_conditions))
        )
        if existing is not None:
            raise AccessGrantExistsError
        grant = AccessGrant(
            telegram_user_id=telegram_user_id,
            username=normalized,
            note=(note.strip() or None) if note else None,
            created_by_telegram_id=created_by_telegram_id,
        )
        self.session.add(grant)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # concurrent insert of the same identity
            await self.session.rollback()
            raise AccessGrantExistsError from exc
        display_name = await self._display_name(grant.telegram_user_id)
        await self.session.commit()
        logger.info("auth.access.granted", grant_id=grant.id, by=created_by_telegram_id)
        return _grant_response(grant, display_name)

    async def delete_grant(self, grant_id: str) -> int:
        grant = await self.session.get(AccessGrant, grant_id)
        if grant is None:
            raise AccessGrantNotFoundError
        return await self._delete(grant)

    async def delete_grant_by_identity(
        self,
        *,
        telegram_user_id: int | None,
        username: str | None,
    ) -> int:
        normalized = normalize_telegram_username(username)
        conditions = []
        if telegram_user_id is not None:
            conditions.append(AccessGrant.telegram_user_id == telegram_user_id)
        if normalized is not None:
            conditions.append(AccessGrant.username == normalized)
        if not conditions:
            raise AccessGrantNotFoundError
        grant = await self.session.scalar(select(AccessGrant).where(or_(*conditions)).limit(1))
        if grant is None:
            raise AccessGrantNotFoundError
        return await self._delete(grant)

    async def _delete(self, grant: AccessGrant) -> int:
        """Delete the grant and revoke sessions of users that lost access because of it."""
        conditions = []
        if grant.telegram_user_id is not None:
            conditions.append(User.telegram_id == str(grant.telegram_user_id))
        if grant.username is not None:
            conditions.append(func.lower(User.telegram_username) == grant.username)
        await self.session.execute(delete(AccessGrant).where(AccessGrant.id == grant.id))
        candidates = (
            await self.session.execute(
                select(User.id, User.telegram_id, User.telegram_username).where(or_(*conditions))
            )
        ).all()
        lost_access = [
            user_id
            for user_id, telegram_id, telegram_username in candidates
            if not await self.is_allowed(int(telegram_id), telegram_username)
        ]
        revoked = 0
        if lost_access:
            result = await self.session.execute(
                update(AuthSession)
                .where(AuthSession.user_id.in_(lost_access), AuthSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
            revoked = int(getattr(result, "rowcount", 0) or 0)
        await self.session.commit()
        logger.info("auth.access.revoked", grant_id=grant.id, sessions_revoked=revoked)
        return revoked

    async def _display_name(self, telegram_user_id: int | None) -> str | None:
        if telegram_user_id is None:
            return None
        value: str | None = await self.session.scalar(
            select(User.display_name).where(User.telegram_id == str(telegram_user_id))
        )
        return value


def _safe_username(username: str | None) -> str | None:
    try:
        return normalize_telegram_username(username)
    except ValueError:
        return None


def _grant_response(grant: AccessGrant, display_name: str | None) -> AccessGrantResponse:
    return AccessGrantResponse(
        id=grant.id,
        telegram_user_id=grant.telegram_user_id,
        username=grant.username,
        note=grant.note,
        created_at=grant.created_at,
        last_login_at=grant.last_login_at,
        display_name=display_name,
    )
