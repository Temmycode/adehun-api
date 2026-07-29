from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.common.enums import IdempotencyStatus


class IdempotencyKey(SQLModel, table=True):
    """Client-supplied `Idempotency-Key` reservations and their stored responses.

    This is a UX convenience — it lets a client safely retry a request that
    timed out and get the original response back. It is NOT the durable
    money-safety guarantee: that is the UNIQUE index on `transaction.reference`.
    If a key is swept early the ledger still refuses to double-spend.
    """

    __tablename__ = "idempotency_key"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "user_id", "endpoint", "key", name="ux_idempotency_user_endpoint_key"
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True, nullable=False)
    key: str = Field(max_length=120, nullable=False)
    endpoint: str = Field(max_length=120, nullable=False)  # "POST /wallet/withdraw"
    request_hash: str = Field(max_length=64, nullable=False)  # sha256 of canonical body

    status: IdempotencyStatus = Field(
        sa_column=Column("status", String(20), nullable=False, index=True)
    )
    response_status_code: int | None = Field(default=None)
    response_body: dict[str, Any] | None = Field(
        default=None, sa_column=Column("response_body", JSONB, nullable=True)
    )
    # Links the key to the ledger entry it produced, for support/debugging.
    resource_reference: str | None = Field(default=None, max_length=120)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
