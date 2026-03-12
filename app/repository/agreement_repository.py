import logging
from typing import Any

from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant, Invitation, User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class AgreementRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ #
    #  Agreement Operations                                              #
    # ------------------------------------------------------------------ #

    def add(self, agreement: Agreement) -> Agreement:
        """Add a new item to the database and refresh it."""
        self.session.add(agreement)
        self.session.commit()
        self.session.refresh(agreement)
        return agreement

    def get_user_agreements(self, user_id: str) -> list[Agreement]:
        """Return a list of agreements for the given user ID."""

        agreements = self.session.exec(
            select(Agreement)
            .join(AgreementParticipant)
            .where(AgreementParticipant.user_id == user_id)
        ).all()

        return list(agreements)

    def get_by_id(self, agreement_id: str) -> Agreement | None:
        """Return an agreement by its ID."""
        return self.session.exec(
            select(Agreement).where(Agreement.agreement_id == agreement_id)
        ).one_or_none()

    def get_user_by_email_or_phone(self, email_or_phone: str) -> User | None:
        """Return a user by their email or phone."""
        return self.session.exec(
            select(User).where(
                (User.email == email_or_phone) | (User.phone_number == email_or_phone)
            )
        ).first()

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_user(self, user: User, *, commit: bool = True):
        """Add a new user to the database."""
        self.session.add(user)
        self.session.flush()
        if commit:
            self.session.commit()
            self.session.refresh(user)
        return user

    def save_agreement(self, agreement: Agreement, *, commit: bool = True):
        """Add a new agreement to the database."""
        self.session.add(agreement)
        if commit:
            self.session.commit()
            self.session.refresh(agreement)
        return agreement

    def invite_participant(
        self,
        invitation_token: str,
        invited_by: str,
        role: str,
        agreement: Agreement,
        other_participant_email: str,
    ) -> Invitation:
        """Create an invitation for the other participant."""
        invitation = Invitation(
            email=other_participant_email,
            token=invitation_token,
            agreement_id=agreement.agreement_id,
            role=role,
            invited_by=invited_by,
        )
        self.session.add(invitation)
        self.session.flush()
        return invitation

    def flush(self, agreement: Agreement) -> Agreement:
        """Flush the session's changes to the database."""
        self.session.add(agreement)
        self.session.flush()
        return agreement

    def flush_participant(
        self, participant: AgreementParticipant
    ) -> AgreementParticipant:
        """Flush the session's changes to the database."""
        self.session.add(participant)
        self.session.flush()
        return participant

    def add_all(self, *args: Any) -> None:
        """Add all given objects to the session."""
        self.session.add_all(args)

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self.session.rollback()

    def refresh(self, agreement: Agreement) -> None:
        """Refresh a student instance from DB and re-cache it."""
        self.session.refresh(agreement)
