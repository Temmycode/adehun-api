import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant, Asset
from app.redis import RedisClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_AGREEMENT_PARTICIPANT = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_USER_PARTICIPANT = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_PARTICIPANT = 60 * 60 * 24  # 24 hours – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _participant_key(participant_id: str) -> str:
    return f"asset:{participant_id}"


def _agreement_participant_key(agreement_id: str) -> str:
    return f"agreement:{agreement_id}:participant"


def _user_participant_key(user_id: str) -> str:
    return f"user:{user_id}:participant"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class AgreementParticipantRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  Asset Operations                                                  #
    # ------------------------------------------------------------------ #

    def flush_participant(self, *participant: AgreementParticipant):
        """Flush participants to generate their IDs without committing."""
        self.session.add_all(participant)
        self.session.flush()
        return participant

    def get_by_id(self, participant_id: str) -> AgreementParticipant | None:
        """Get an asset by id"""
        key = _participant_key(participant_id)
        cached = self._cache_get(key)
        if cached is not None:
            return AgreementParticipant.model_validate(cached)

        asset = self.session.exec(
            select(AgreementParticipant).where(
                AgreementParticipant.participant_id == participant_id
            )
        ).first()
        if asset:
            self._cache_set(key, asset, _TTL_PARTICIPANT)
        return asset

    def get_agreement_users(self, agreement_id: str) -> list[AgreementParticipant]:
        """Get all participants in an agreement"""

        key = _agreement_participant_key(agreement_id)
        cached = self._cache_get(key)
        if cached:
            return [
                AgreementParticipant.model_validate(participant)
                for participant in cached
            ]

        participants = list(
            self.session.exec(
                select(AgreementParticipant)
                .join(
                    Agreement,
                    AgreementParticipant.agreement_id == Agreement.agreement_id,  # pyright: ignore[reportArgumentType]
                )
                .where(Agreement.agreement_id == agreement_id)
            )
        )

        if participants:
            self._cache_set(
                key,
                [participant.model_dump(mode="json") for participant in participants],
                _TTL_AGREEMENT_PARTICIPANT,
            )

        return participants

    def get_user_participants(self, user_id: str) -> list[AgreementParticipant]:
        """Get all participants assigned to a user"""
        key = _user_participant_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            return [
                AgreementParticipant.model_validate(participant)
                for participant in cached
            ]

        participants = list(
            self.session.exec(
                select(AgreementParticipant).where(
                    AgreementParticipant.user_id == user_id
                )
            ).all()
        )
        if participants:
            self._cache_set(
                key,
                [asset.model_dump(mode="json") for asset in participants],
                _TTL_AGREEMENT_PARTICIPANT,
            )
        return participants

    def delete_participant(self, participant_id: str) -> None:
        participant = self.get_by_id(participant_id)
        if participant:
            self.session.delete(participant)
            self.session.commit()
            self._cache_delete(_participant_key(participant_id))

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_asset(self, asset: Asset, *, commit: bool = True) -> Asset:
        """Save an asset to the database"""
        self.session.add(asset)
        if commit:
            self.session.commit()
            self.session.refresh(asset)
        return asset

    def commit(self) -> None:
        """Commit the session"""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the session"""
        self.session.rollback()

    def refresh(self, asset: Asset) -> None:
        """Refresh an asset from the database"""
        self.session.refresh(asset)
