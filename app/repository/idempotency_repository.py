"""Storage for client `Idempotency-Key` reservations.

The reservation is taken with a single race-safe statement so two concurrent
requests carrying the same key cannot both proceed. See `app.core.idempotency`
for the flow that drives this.
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from redis import Redis
from sqlalchemy import and_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, delete, select

from app.common.enums import IdempotencyStatus
from app.config import settings
from app.logging import get_logger
from app.models import IdempotencyKey
from app.redis import RedisClient

logger = get_logger(__name__)

# Chance of sweeping expired rows on any given reservation. There is no task
# queue in this project; the table stays small, and the ledger's unique
# reference — not this table — is what actually prevents double spending.
_SWEEP_PROBABILITY = 0.02


class IdempotencyRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    def reserve(
        self, *, user_id: str, endpoint: str, key: str, request_hash: str
    ) -> str | None:
        """Try to claim the key. Returns the row id on success, None if taken.

        A reservation left IN_PROGRESS longer than
        `idempotency_inflight_timeout_seconds` is considered abandoned (the
        process died mid-request) and can be taken over.
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=settings.idempotency_ttl_hours)
        stale_before = now - timedelta(
            seconds=settings.idempotency_inflight_timeout_seconds
        )
        table = IdempotencyKey.__table__

        statement = (
            pg_insert(table)
            .values(
                id=str(uuid4()),
                user_id=user_id,
                endpoint=endpoint,
                key=key,
                request_hash=request_hash,
                status=IdempotencyStatus.IN_PROGRESS.value,
                created_at=now,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="ux_idempotency_user_endpoint_key",
                set_={
                    "status": IdempotencyStatus.IN_PROGRESS.value,
                    "request_hash": request_hash,
                    "created_at": now,
                    "expires_at": expires_at,
                    "completed_at": None,
                    "response_status_code": None,
                    "response_body": None,
                },
                where=and_(
                    table.c.status == IdempotencyStatus.IN_PROGRESS.value,
                    table.c.created_at < stale_before,
                ),
            )
            .returning(table.c.id)
        )
        reserved_id = self.session.execute(statement).scalar()
        self.session.commit()

        if reserved_id is not None and random.random() < _SWEEP_PROBABILITY:
            self._sweep_expired()

        return reserved_id

    def get(self, *, user_id: str, endpoint: str, key: str) -> IdempotencyKey | None:
        return self.session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.key == key,
            )
        ).first()

    def complete(
        self,
        record_id: str,
        *,
        status_code: int,
        body: dict[str, Any] | None,
        resource_reference: str | None = None,
    ) -> None:
        record = self.session.get(IdempotencyKey, record_id)
        if record is None:
            return
        record.status = IdempotencyStatus.COMPLETED
        record.response_status_code = status_code
        record.response_body = body
        record.completed_at = datetime.now(timezone.utc)
        if resource_reference is not None:
            record.resource_reference = resource_reference
        self.session.add(record)
        self.session.commit()

    def bind_reference(self, record_id: str, reference: str) -> None:
        record = self.session.get(IdempotencyKey, record_id)
        if record is None:
            return
        record.resource_reference = reference
        self.session.add(record)
        self.session.commit()

    def release(self, record_id: str) -> None:
        """Drop an abandoned reservation so the client can legitimately retry.

        Only removes rows still IN_PROGRESS — a completed response is never
        thrown away.
        """
        self.session.rollback()
        self.session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.id == record_id,  # pyright: ignore[reportArgumentType]
                IdempotencyKey.status == IdempotencyStatus.IN_PROGRESS,  # pyright: ignore[reportArgumentType]
            )
        )
        self.session.commit()

    def _sweep_expired(self) -> None:
        """Best-effort cleanup.

        An external `pg_cron` job running
        `DELETE FROM idempotency_key WHERE expires_at < now()`
        would do the same job more predictably if one is ever available.
        """
        try:
            self.session.execute(
                text("DELETE FROM idempotency_key WHERE expires_at < now()")
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            logger.warning("idempotency sweep failed", exc_info=True)

    def rollback(self) -> None:
        self.session.rollback()
