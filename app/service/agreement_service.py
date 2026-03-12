import logging
from uuid import uuid4

from fastapi import BackgroundTasks
from redis import Redis

from app.common.enums import InvitationStatus, ParticipantRole
from app.config import settings
from app.exceptions import AgreementCreationError, AgreementNotFoundError
from app.models import Agreement, AgreementParticipant, User
from app.redis import RedisClient
from app.repository.agreement_repository import AgreementRepository
from app.schemas.agreement_schema import (
    AgreementCreate,
    AgreementResponse,
    InvitationResponse,
)

from ..service.invitation_service import (
    get_invitation_token,
    store_invitation,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_LIST = 60 * 5  # 5 min   – list/collection keys
_TTL_USER_AGREEMENTS = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_AGREEMENTS = 60 * 60 * 24  # 24 hours – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agreement_key(agreement_id: str) -> str:
    return f"agreement:{agreement_id}"


def _agreement_participant_key(agreement_id: str, participant_id: str) -> str:
    return f"agreement:{agreement_id}:participant:{participant_id}"


def _condition_key(condition_id: str) -> str:
    return f"condition:{condition_id}"


def _user_agreements_key(user_id: str) -> str:
    return f"user:{user_id}:agreements"


class AgreementService(RedisClient):
    def __init__(self, agreement_repo: AgreementRepository, redis_client: Redis):
        super().__init__(redis_client)
        self.agreement_repo = agreement_repo

    def _invite_participant(
        self,
        role: str,
        creator_id: str,
        email: str,
        is_email: bool,
        agreement: Agreement,
        background_tasks,
    ):

        # invite the other participant via email/phone
        invitation_token = get_invitation_token()
        invitation = self.agreement_repo.invite_participant(
            invitation_token,
            creator_id,
            "beneficiary" if role == "depositor" else "depositor",
            agreement,
            email,
        )
        invitation_data = InvitationResponse.model_validate(invitation)

        store_invitation(
            self.redis_client, invitation_token, invitation_data.model_dump(mode="json")
        )
        invitation_link = f"{settings.frontend_url}/invite?token={invitation_token}"
        background_tasks.add_task(
            "EmailService.send_tutor_invitation",
            email,
            invitation_link,
        )
        logger.debug(
            "Invite participant succeeded",
            extra={"email": email},
        )

    def create_agreement(
        self,
        current_user_id: str,
        agreement_data: AgreementCreate,
        background_tasks: BackgroundTasks,
    ) -> Agreement:
        try:
            # create agreement
            agreement = self.agreement_repo.flush(
                Agreement(
                    title=agreement_data.title,
                    description=agreement_data.description,
                    amount=agreement_data.amount,
                )
            )

            # create agreement participants
            creator = AgreementParticipant(
                user_id=current_user_id,
                agreement_id=agreement.agreement_id,
                role=agreement_data.role,
                status=InvitationStatus.ACCEPTED.value,
            )
            self.agreement_repo.flush_participant(creator)

            # save all
            self.agreement_repo.commit()

            self._invite_participant(
                agreement_data.role,
                creator.user_id,
                agreement_data.other_participant_email_or_phone,
                agreement_data.other_participant_email_or_phone.count("@") == 1,
                agreement,
                background_tasks,
            )
            return agreement
        except Exception as err:
            logger.exception("Failed to save agreement")
            self.agreement_repo.rollback()
            raise AgreementCreationError() from err

    def get_agreement(self, agreement_id: str) -> AgreementResponse:
        """Get agreement by id"""
        key = _agreement_key(agreement_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning agreement id=%d", agreement_id)
            return AgreementResponse.model_validate(cached)

        db_agreement = self.agreement_repo.get_by_id(agreement_id)
        if db_agreement is None:
            raise AgreementNotFoundError()

        agreement = AgreementResponse.model_validate(db_agreement)
        self._cache_set(key, agreement, _TTL_AGREEMENTS)
        return agreement

    def get_all_user_agreements(self, user_id: str) -> list[AgreementResponse]:
        """Get all agreements for a user"""
        key = _user_agreements_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning agreements for user id=%d", user_id)
            return [AgreementResponse.model_validate(agreement) for agreement in cached]

        db_agreements = self.agreement_repo.get_user_agreements(user_id)
        agreements = [
            AgreementResponse.model_validate(agreement) for agreement in db_agreements
        ]

        if agreements:
            self._cache_set(
                key,
                [agreement.model_dump(mode="json") for agreement in agreements],
                _TTL_USER_AGREEMENTS,
            )

        return agreements
