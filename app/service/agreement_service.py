from app.logging import get_logger

from fastapi import BackgroundTasks

import app.service.email_service as email_service
from app.common.enums import InvitationStatus
from app.config import settings
from app.exceptions import (
    AgreementAcceptanceError,
    AgreementCreationError,
    AgreementNotFoundError,
)
from app.models import Agreement, AgreementParticipant, Condition, Invitation
from app.repository.agreement_repository import AgreementRepository
from app.schemas.agreement_schema import (
    AgreementCreate,
    AgreementCreateResponse,
    AgreementResponse,
    InvitationResponse,
)
from app.schemas.conditions_schema import ConditionResponse
from app.schemas.participant_schema import ParticipantResponse

from ..service.invitation_service import (
    get_invitation_token,
    store_invitation,
)

logger = get_logger(__name__)


class AgreementService:
    def __init__(self, agreement_repo: AgreementRepository):
        self.agreement_repo = agreement_repo

    def _invite_participant(
        self,
        role: str,
        creator_id: str,
        email: str,
        is_email: bool,
        agreement: Agreement,
        background_tasks: BackgroundTasks,
    ) -> Invitation:

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

        if self.agreement_repo.redis_client:
            store_invitation(
                self.agreement_repo.redis_client,
                invitation_token,
                invitation_data.model_dump(mode="json"),
            )
        invitation_link = f"{settings.frontend_url}/invite?token={invitation_token}"
        background_tasks.add_task(
            email_service.send_invitation_email,
            email,
            invitation_link,
        )
        logger.info(
            "participant invited",
            extra={
                "email": email,
                "role": role,
                "agreement_id": agreement.id,
                "creator_id": creator_id,
            },
        )
        return invitation

    def create_agreement(
        self,
        current_user_id: str,
        agreement_data: AgreementCreate,
        background_tasks: BackgroundTasks,
    ) -> AgreementCreateResponse:
        try:
            # create agreement
            agreement = self.agreement_repo.flush(
                Agreement(
                    title=agreement_data.title,
                    description=agreement_data.description,
                    amount=agreement_data.amount,
                    user_id=current_user_id,
                )
            )

            # create agreement participants
            creator = AgreementParticipant(
                user_id=current_user_id,
                agreement_id=agreement.id,
                role=agreement_data.role,
                status=InvitationStatus.ACCEPTED.value,
            )

            self.agreement_repo.flush_participant(creator)

            # invite the other participant (flushed, so we get an id)
            invitation = self._invite_participant(
                agreement_data.role,
                creator.user_id,
                agreement_data.other_participant_email_or_phone,
                agreement_data.other_participant_email_or_phone.count("@") == 1,
                agreement,
                background_tasks,
            )

            # create conditions linked to creator and invitation
            # required_from_participant_id is None because the other party
            # hasn't accepted yet — it gets backfilled when they accept
            # via update_agreement_conditions_with_invitation
            conditions = [
                Condition(
                    agreement_id=agreement.id,
                    participant_id=creator.id,
                    title=c.title,
                    description=c.description,
                    required_from_participant_id=None,
                    invitation_id=invitation.id,
                )
                for c in agreement_data.conditions
            ]
            self.agreement_repo.session.add_all(conditions)

            # save all
            self.agreement_repo.commit()
            for c in conditions:
                self.agreement_repo.session.refresh(c)

            db_agreement = self.agreement_repo.get_by_id(agreement.id)
            if db_agreement is None:
                raise AgreementNotFoundError()

            agreement_response = self._to_agreement_response(db_agreement)

            return AgreementCreateResponse(
                **agreement_response.model_dump(),
                conditions=[ConditionResponse.model_validate(c) for c in conditions],
            )
        except Exception as err:
            logger.exception(
                "failed to create agreement",
                extra={"user_id": current_user_id, "title": agreement_data.title},
            )
            self.agreement_repo.rollback()
            raise AgreementCreationError() from err

    def get_agreement(self, agreement_id: str) -> AgreementResponse:
        """Get agreement by id"""
        db_agreement = self.agreement_repo.get_by_id(agreement_id)
        if db_agreement is None:
            raise AgreementNotFoundError()

        return AgreementResponse.model_validate(db_agreement)

    def get_all_user_agreements(self, user_id: str) -> list[AgreementResponse]:
        """Get all agreements for a user"""

        db_agreements = self.agreement_repo.get_user_agreements(user_id)
        return [self._to_agreement_response(a) for a in db_agreements]

    @staticmethod
    def _to_agreement_response(agreement: Agreement) -> AgreementResponse:
        """Map an Agreement (with loaded participants) to AgreementResponse."""
        depositor: AgreementParticipant | None = None
        beneficiary: AgreementParticipant | None = None
        for p in agreement.participants:
            if p.role == "depositor":
                depositor = p
            elif p.role == "beneficiary":
                beneficiary = p

        return AgreementResponse(
            id=agreement.id,
            title=agreement.title,
            description=agreement.description,
            amount=agreement.amount,
            status=agreement.status,
            depositor=ParticipantResponse.model_validate(depositor)
            if depositor
            else None,
            beneficiary=ParticipantResponse.model_validate(beneficiary)
            if beneficiary
            else None,
            created_at=agreement.created_at,
        )

    def accept_agreement(
        self, agreement_id: str, user_id: str, email: str
    ) -> AgreementResponse:
        """Accept an agreement"""

        # Create the agreement participant\
        invitation = self.agreement_repo.get_invitation_by_agreement_id(
            email, agreement_id
        )
        if not invitation:
            raise AgreementAcceptanceError("No invitation found for this agreement")

        participant = AgreementParticipant(
            agreement_id=agreement_id,
            user_id=user_id,
            role=invitation.role,
        )
        new_participant = self.agreement_repo.flush_participant(participant)

        # Update the conditions that have the users email to use the participant's id
        self.agreement_repo.update_agreement_conditions_with_invitation(
            agreement_id, invitation.id, new_participant.id
        )

        # fetch the new agreement data
        return self.get_agreement(agreement_id)
