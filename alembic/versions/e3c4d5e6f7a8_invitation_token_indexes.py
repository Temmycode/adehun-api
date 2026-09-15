"""invitation token and email indexes

Revision ID: e3c4d5e6f7a8
Revises: d2b3c4d5e6f7
Create Date: 2026-09-15 12:10:00.000000

The public invite lookup (`GET /invitations/{token}`) and the invited-list
query both hit `invitation` by a column that had no index. The token index is
UNIQUE: two invitations must never share a token.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "d2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_invitation_token", "invitation", ["token"], unique=True)
    op.create_index("ix_invitation_email", "invitation", ["email"])


def downgrade() -> None:
    op.drop_index("ix_invitation_email", table_name="invitation")
    op.drop_index("ix_invitation_token", table_name="invitation")
