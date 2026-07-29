"""create webhook event table

Revision ID: c0b1ab165890
Revises: 223902e70386
Create Date: 2026-07-29 12:31:40.335885

Dedupe + audit log for inbound provider webhooks. The unique dedupe_key is what
makes webhook processing idempotent — we insert first and only process if we
won the insert, so a redelivered event is a no-op.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c0b1ab165890'
down_revision: Union[str, Sequence[str], None] = '223902e70386'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "webhook_event",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "provider", sa.String(32), server_default="paystack", nullable=False
        ),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("provider_event_id", sa.String(64), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_event_dedupe_key", "webhook_event", ["dedupe_key"], unique=True
    )
    op.create_index("ix_webhook_event_event_type", "webhook_event", ["event_type"])
    op.create_index("ix_webhook_event_reference", "webhook_event", ["reference"])
    op.create_index("ix_webhook_event_status", "webhook_event", ["status"])
    op.create_index("ix_webhook_event_received_at", "webhook_event", ["received_at"])


def downgrade() -> None:
    """Downgrade schema."""
    for index in (
        "ix_webhook_event_received_at",
        "ix_webhook_event_status",
        "ix_webhook_event_reference",
        "ix_webhook_event_event_type",
        "ix_webhook_event_dedupe_key",
    ):
        op.drop_index(index, table_name="webhook_event")
    op.drop_table("webhook_event")
