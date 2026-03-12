import logging

from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant, Condition, Invitation, User
from app.redis import RedisClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class ConditionRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ #
    #  Condition Operations                                              #
    # ------------------------------------------------------------------ #

    def flush_condition(self, condition: Condition) -> Condition:
        """Add a new item to the database and refresh it."""
        self.session.add(condition)
        self.session.flush()
        return condition

    def get_agreement_condition(self, agreement_id: str) -> list[Condition]:
        """Return a list of agreements for the given user ID."""
        conditions = self.session.exec(
            select(Condition).where(Condition.agreement_id == agreement_id)
        ).all()
        return list(conditions)

    def get_by_id(self, agreement_id: str, condition_id: str) -> Condition | None:
        """Return an agreement by its ID."""
        return self.session.exec(
            select(Condition).where(
                Condition.agreement_id == agreement_id,
                Condition.condition_id == condition_id,
            )
        ).one_or_none()

    def get_participant(
        self, user_id: str, agreement_id: str
    ) -> AgreementParticipant | None:
        return self.session.exec(
            select(AgreementParticipant).where(
                AgreementParticipant.user_id == user_id
                and AgreementParticipant.agreement_id == agreement_id
            )
        ).first()

    def get_participant_or_invitation_by_email(
        self, email: str, agreement_id: str
    ) -> AgreementParticipant | Invitation | None:
        participant = self.session.exec(
            select(AgreementParticipant)
            .join(User)
            .where(
                User.email == email, AgreementParticipant.agreement_id == agreement_id
            )
        ).first()
        if participant:
            return participant
        invitation = self.session.exec(
            select(Invitation).where(
                Invitation.email == email and Invitation.agreement_id == agreement_id
            )
        ).first()
        return invitation

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_condition(self, condition: Condition, *, commit: bool = True):
        """Add a new agreement to the database."""
        self.session.add(condition)
        if commit:
            self.session.commit()
            self.session.refresh(condition)
        return condition

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self.session.rollback()

    def refresh(self, condition: Condition) -> None:
        """Refresh a student instance from DB and re-cache it."""
        self.session.refresh(condition)
