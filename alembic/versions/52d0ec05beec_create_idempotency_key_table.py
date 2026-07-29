"""create idempotency key table

Revision ID: 52d0ec05beec
Revises: c0b1ab165890
Create Date: 2026-07-29 12:31:40.824068

Client-supplied Idempotency-Key reservations and their stored responses. This
is a UX convenience layer — the durable money-safety guarantee is the UNIQUE
index on transaction.reference.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '52d0ec05beec'
down_revision: Union[str, Sequence[str], None] = 'c0b1ab165890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "idempotency_key",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("endpoint", sa.String(120), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("resource_reference", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "endpoint", "key", name="ux_idempotency_user_endpoint_key"
        ),
    )
    op.create_index("ix_idempotency_key_user_id", "idempotency_key", ["user_id"])
    op.create_index("ix_idempotency_key_status", "idempotency_key", ["status"])
    op.create_index("ix_idempotency_key_expires_at", "idempotency_key", ["expires_at"])


def downgrade() -> None:
    """Downgrade schema."""
    for index in (
        "ix_idempotency_key_expires_at",
        "ix_idempotency_key_status",
        "ix_idempotency_key_user_id",
    ):
        op.drop_index(index, table_name="idempotency_key")
    op.drop_table("idempotency_key")
