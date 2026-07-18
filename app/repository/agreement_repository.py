from typing import Any

from redis import Redis
from sqlalchemy import case, func
from sqlmodel import Session, col, select

from app.logging import get_logger
from app.models import Agreement, AgreementParticipant, Condition, Invitation, User
from app.redis import RedisClient

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_USER_AGREEMENTS = 60 * 5  # 5 minutes – cache TTL
_TTL_AGREEMENTS = 60 * 5  # 5 minutes – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agreement_key(agreement_id: str) -> str:
    return f"agreement:{agreement_id}"


def _agreement_participant_key(agreement_id: str, participant_id: str) -> str:
    return f"agreement:{agreement_id}:participant:{participant_id}"


def _user_agreements_key(user_id: str) -> str:
    return f"user:{user_id}:agreements"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class AgreementRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        self.session = session
        super().__init__(redis_client)

    # ------------------------------------------------------------------ #
    #  Agreement Operations                                              #
    # ------------------------------------------------------------------ #

    def add(self, agreement: Agreement) -> Agreement:
        """Add a new item to the database and refresh it."""
        self.session.add(agreement)
        self.session.commit()
        self.session.refresh(agreement)
        return agreement

    def get_user_agreements(self, user_id: str) -> list[tuple[Agreement, int, int]]:
        """Return a list of agreements for the given user ID.

        Each tuple is (agreement, total_conditions_count, conditions_met_count).
        """

        key = _user_agreements_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("cache hit for user agreements", extra={"user_id": user_id})
            return [
                (self.session.merge(Agreement.model_validate(a)), total, met)
                for a, total, met in cached
            ]

        logger.debug("fetching user agreements from db", extra={"user_id": user_id})
        agreements = self.session.exec(
            select(Agreement)
            .join(AgreementParticipant)
            .where(AgreementParticipant.user_id == user_id)
        ).all()
        logger.debug(
            "fetched user agreements",
            extra={"user_id": user_id, "count": len(agreements)},
        )

        if not agreements:
            return []

        agreement_ids = [a.id for a in agreements]

        condition_counts = self.session.exec(
            select(
                Condition.agreement_id,
                func.count(Condition.id),  # pyright: ignore[reportArgumentType]
                func.sum(case((Condition.status == "approved", 1), else_=0)),  # pyright: ignore[reportArgumentType]
            )
            .where(col(Condition.agreement_id).in_(agreement_ids))
            .group_by(Condition.agreement_id)
        ).all()

        counts_by_agreement = {
            agreement_id: (total, met or 0)
            for agreement_id, total, met in condition_counts
        }

        results = [
            (agreement, *counts_by_agreement.get(agreement.id, (0, 0)))
            for agreement in agreements
        ]

        self._cache_set(
            key,
            [
                (agreement.model_dump(mode="json"), total, met)
                for agreement, total, met in results
            ],
            _TTL_USER_AGREEMENTS,
        )

        return results

    def get_by_id(self, agreement_id: str) -> Agreement | None:
        """Return an agreement by its ID."""
        key = _agreement_key(agreement_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug(
                "cache hit for agreement", extra={"agreement_id": agreement_id}
            )
            return Agreement.model_validate(cached)

        logger.debug("fetching agreement from db", extra={"agreement_id": agreement_id})
        agreement = self.session.exec(
            select(Agreement).where(Agreement.id == agreement_id)
        ).first()
        if agreement:
            self._cache_set(key, agreement, _TTL_AGREEMENTS)
        else:
            logger.info("agreement not found", extra={"agreement_id": agreement_id})
        return agreement

    def get_user_by_email_or_phone(self, email_or_phone: str) -> User | None:
        """Return a user by their email or phone."""
        return self.session.exec(
            select(User).where(
                (User.email == email_or_phone) | (User.phone_number == email_or_phone)
            )
        ).first()

    def get_invitation_by_agreement_id(
        self, email: str, agreement_id: str
    ) -> Invitation | None:
        """Return an invitation by its agreement ID."""
        return self.session.exec(
            select(Invitation).where(
                Invitation.agreement_id == agreement_id,
                Invitation.email == email,
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
            agreement_id=agreement.id,
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

    def update_agreement_conditions_with_invitation(
        self, agreement_id: str, invitation_id: str, participant_id: str
    ):
        """Update the conditions of an agreement to replace the email with the participant's id."""
        condition = self.session.exec(
            select(Condition).where(
                Condition.agreement_id == agreement_id,
                Condition.invitation_id == invitation_id,
            )
        ).first()

        if condition:
            condition.required_from_participant_id = participant_id
            self.session.add(condition)
            self.session.commit()
            self.session.refresh(condition)

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
