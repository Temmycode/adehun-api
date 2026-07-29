"""Webhook dedupe: insert first, then process.

`claim()` is the whole idea. It inserts the event and tells the caller whether
this process won the insert. If it did not, the event has already been handled
(or is being handled) and must be ignored — that is what makes redelivery from
Paystack a no-op.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis import Redis
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from app.common.enums import WebhookEventStatus
from app.logging import get_logger
from app.models import WebhookEvent
from app.redis import RedisClient

logger = get_logger(__name__)


class WebhookEventRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    def claim(
        self,
        *,
        dedupe_key: str,
        event_type: str,
        payload: dict[str, Any],
        provider_event_id: str | None = None,
        reference: str | None = None,
        provider: str = "paystack",
    ) -> bool:
        """Try to take ownership of an event. True means "process it".

        The `WHERE status = 'failed'` clause on the conflict branch is what lets
        Paystack's automatic retry re-drive an event that blew up transiently,
        without ever re-driving one that already succeeded.
        """
        now = datetime.now(timezone.utc)
        statement = (
            pg_insert(WebhookEvent.__table__)
            .values(
                id=str(uuid4()),
                provider=provider,
                dedupe_key=dedupe_key,
                event_type=event_type,
                provider_event_id=provider_event_id,
                reference=reference,
                status=WebhookEventStatus.RECEIVED.value,
                attempts=1,
                payload=payload,
                received_at=now,
            )
            .on_conflict_do_update(
                index_elements=["dedupe_key"],
                set_={
                    "status": WebhookEventStatus.RECEIVED.value,
                    "attempts": text("webhook_event.attempts + 1"),
                    "received_at": now,
                },
                where=WebhookEvent.__table__.c.status == WebhookEventStatus.FAILED.value,
            )
            .returning(WebhookEvent.__table__.c.id)
        )
        claimed_id = self.session.execute(statement).scalar()
        self.session.commit()

        if claimed_id is None:
            logger.info(
                "duplicate webhook ignored",
                extra={"dedupe_key": dedupe_key, "event_type": event_type},
            )
            return False
        return True

    def get(self, dedupe_key: str) -> WebhookEvent | None:
        return self.session.exec(
            select(WebhookEvent).where(WebhookEvent.dedupe_key == dedupe_key)
        ).first()

    def mark(self, dedupe_key: str, status: WebhookEventStatus) -> None:
        event = self.get(dedupe_key)
        if event is None:
            return
        event.status = status
        event.processed_at = datetime.now(timezone.utc)
        self.session.add(event)
        self.session.commit()

    def mark_failed(self, dedupe_key: str, error: str) -> None:
        """Record a handler failure.

        Rolls back first: the session is poisoned after the exception that got
        us here, so the write has to happen in a fresh transaction.
        """
        self.session.rollback()
        event = self.get(dedupe_key)
        if event is None:
            return
        event.status = WebhookEventStatus.FAILED
        event.error = error[:2000]
        event.processed_at = datetime.now(timezone.utc)
        self.session.add(event)
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
