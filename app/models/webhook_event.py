from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.common.enums import WebhookEventStatus


class WebhookEvent(SQLModel, table=True):
    """Dedupe + audit log for inbound provider webhooks.

    The unique `dedupe_key` is what makes webhook processing idempotent: we
    insert first and only process if we won the insert, so a redelivered event
    is a no-op. See `WebhookEventRepository.claim`.
    """

    __tablename__ = "webhook_event"  # pyright: ignore[reportAssignmentType]

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    provider: str = Field(default="paystack", max_length=32, nullable=False)
    # f"paystack:{event_type}:{data.id or data.reference or sha256(raw_body)}"
    # Namespaced per event type because a charge id and a transfer id can
    # collide numerically.
    dedupe_key: str = Field(
        sa_column=Column(
            "dedupe_key", String(200), nullable=False, unique=True, index=True
        )
    )
    event_type: str = Field(
        sa_column=Column("event_type", String(64), nullable=False, index=True)
    )
    provider_event_id: str | None = Field(default=None, max_length=64)
    reference: str | None = Field(
        default=None, sa_column=Column("reference", String(120), index=True)
    )
    status: WebhookEventStatus = Field(
        sa_column=Column("status", String(20), nullable=False, index=True)
    )
    attempts: int = Field(default=1, nullable=False)
    payload: dict[str, Any] = Field(
        sa_column=Column("payload", JSONB, nullable=False)
    )
    error: str | None = Field(default=None, sa_column=Column("error", Text))

    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
