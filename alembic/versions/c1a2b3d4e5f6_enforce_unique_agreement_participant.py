"""enforce unique agreement participant

Revision ID: c1a2b3d4e5f6
Revises: 42098c496863
Create Date: 2026-09-15 12:00:00.000000

Revision 8692a810a7b1 was meant to add this constraint but its upgrade() is a
no-op, so the model's `ux_agreement_participant_agreement_user` never reached
the database and duplicate (agreement_id, user_id) rows are possible.

Before adding the constraint, collapse any duplicates onto the oldest row and
repoint every foreign key that references the losers.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "42098c496863"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ux_agreement_participant_agreement_user"


def upgrade() -> None:
    # Map every duplicate row -> the row to keep (lowest id; the table has no timestamp).
    op.execute(
        """
        CREATE TEMP TABLE participant_dupes AS
        SELECT p.id AS loser_id, k.keep_id
        FROM agreement_participant p
        JOIN (
            SELECT agreement_id, user_id,
                   (array_agg(id ORDER BY id))[1] AS keep_id
            FROM agreement_participant
            GROUP BY agreement_id, user_id
            HAVING count(*) > 1
        ) k ON k.agreement_id = p.agreement_id AND k.user_id = p.user_id
        WHERE p.id <> k.keep_id
        """
    )
    op.execute(
        "UPDATE condition c SET participant_id = d.keep_id "
        "FROM participant_dupes d WHERE c.participant_id = d.loser_id"
    )
    op.execute(
        "UPDATE condition c SET required_from_participant_id = d.keep_id "
        "FROM participant_dupes d WHERE c.required_from_participant_id = d.loser_id"
    )
    op.execute(
        "UPDATE asset a SET uploaded_by = d.keep_id "
        "FROM participant_dupes d WHERE a.uploaded_by = d.loser_id"
    )
    op.execute(
        "UPDATE transaction t SET participant_id = d.keep_id "
        "FROM participant_dupes d WHERE t.participant_id = d.loser_id"
    )
    op.execute(
        "DELETE FROM agreement_participant p "
        "USING participant_dupes d WHERE p.id = d.loser_id"
    )
    op.execute("DROP TABLE participant_dupes")

    op.create_unique_constraint(
        CONSTRAINT, "agreement_participant", ["agreement_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "agreement_participant", type_="unique")
