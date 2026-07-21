from app.logging import get_logger

from fastapi import BackgroundTasks

import app.service.email_service as email_service
from app.common.enums import InvitationStatus
from app.config import settings
from app.exceptions import (
    AgreementAcceptanceError,
    AgreementCreationError,
    AgreementNotFoundError,
    InvitationNotFoundError,
)
from app.models import Agreement, AgreementParticipant, Condition, Invitation
from app.repository.agreement_repository import AgreementRepository
from app.schemas.agreement_schema import (
    AgreementCreate,
    AgreementCreateResponse,
    AgreementInvitationResponse,
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

            agreement_response = self._to_agreement_response(
                db_agreement, len(conditions), 0
            )

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

    def get_agreement(
        self, agreement_id: str, user_id: str | None = None
    ) -> AgreementResponse:
        """Get agreement by id."""
        db_agreement = self.agreement_repo.get_by_id(agreement_id)
        if db_agreement is None:
            raise AgreementNotFoundError()

        response = self._to_agreement_response(db_agreement, 0, 0, user_id)
        return response

    def get_all_user_agreements(self, user_id: str) -> list[AgreementResponse]:
        """Get all agreements for a user."""

        db_agreements = self.agreement_repo.get_user_agreements(user_id)
        return [
            self._to_agreement_response(agr, con_ct, met_ct, user_id)
            for agr, con_ct, met_ct in db_agreements
        ]

    def get_agreement_invitation(
        self, agreement_id: str, user_id: str, email: str
    ) -> AgreementInvitationResponse:
        """Get the invitation for an agreement if the current user can access it."""
        agreement = self.agreement_repo.get_by_id(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        invitation = self.agreement_repo.get_invitation_for_user(
            agreement_id, user_id, email
        )
        if invitation is None:
            raise InvitationNotFoundError("Invitation not found for this agreement")

        return AgreementInvitationResponse.model_validate(invitation)

    def _to_agreement_response(
        self,
        agreement: Agreement,
        condition_count: int,
        conditions_met_count: int,
        user_id: str | None = None,
    ) -> AgreementResponse:
        """Map an Agreement (with loaded participants) to AgreementResponse."""
        depositor: AgreementParticipant | None = None
        beneficiary: AgreementParticipant | None = None
        for p in agreement.participants:
            if p.role == "depositor":
                depositor = p
            elif p.role == "beneficiary":
                beneficiary = p

        response = AgreementResponse(
            id=agreement.id,
            title=agreement.title,
            description=agreement.description,
            amount=agreement.amount,
            status=agreement.status,
            depositor=(
                ParticipantResponse.model_validate(depositor) if depositor else None
            ),
            beneficiary=(
                ParticipantResponse.model_validate(beneficiary) if beneficiary else None
            ),
            created_at=agreement.created_at,
            condition_count=condition_count,
            conditions_met_count=conditions_met_count,
        )
        if user_id is not None:
            participant = self.agreement_repo.get_participant_for_user(
                agreement.id, user_id
            )
            response.current_user_accepted = (
                participant is not None
                and participant.status == InvitationStatus.ACCEPTED.value
            )

        return response

    def accept_agreement(
        self, agreement_id: str, user_id: str, email: str
    ) -> AgreementResponse:
        """Accept an agreement without failing if the same user clicks twice."""

        invitation = self.agreement_repo.get_invitation_by_agreement_id(
            email, agreement_id
        )
        if not invitation:
            raise AgreementAcceptanceError("No invitation found for this agreement")

        participant = self.agreement_repo.get_participant_for_user(
            agreement_id, user_id
        )
        if participant is None:
            participant = AgreementParticipant(
                agreement_id=agreement_id,
                user_id=user_id,
                role=invitation.role,
                status=InvitationStatus.ACCEPTED.value,
            )
            self.agreement_repo.session.add(participant)
        else:
            participant.status = InvitationStatus.ACCEPTED.value
            self.agreement_repo.session.add(participant)

        self.agreement_repo.session.commit()
        self.agreement_repo.session.refresh(participant)

        agreement = self.agreement_repo.get_by_id(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        participants = self.agreement_repo.get_participants_for_agreement(agreement_id)
        accepted_count = sum(
            1 for p in participants if p.status == InvitationStatus.ACCEPTED.value
        )
        if accepted_count >= 2:
            agreement.status = "active"
            self.agreement_repo.session.add(agreement)
            self.agreement_repo.session.commit()
            self.agreement_repo.session.refresh(agreement)
        else:
            agreement.status = "pending"
            self.agreement_repo.session.add(agreement)
            self.agreement_repo.session.commit()
            self.agreement_repo.session.refresh(agreement)

        self.agreement_repo.invalidate_agreement_cache(
            agreement_id,
            [agreement.user_id, user_id],
        )

        # Update the conditions that have the users email to use the participant's id
        self.agreement_repo.update_agreement_conditions_with_invitation(
            agreement_id, invitation.id, participant.id
        )

        return self.get_agreement(agreement_id, user_id)

    def reject_agreement(
        self, agreement_id: str, user_id: str, email: str
    ) -> AgreementResponse:
        """Reject an agreement and mark the participant as rejected."""

        invitation = self.agreement_repo.get_invitation_by_agreement_id(
            email, agreement_id
        )
        if not invitation:
            raise AgreementAcceptanceError("No invitation found for this agreement")

        participant = self.agreement_repo.get_participant_for_user(
            agreement_id, user_id
        )
        if participant is None:
            participant = AgreementParticipant(
                agreement_id=agreement_id,
                user_id=user_id,
                role=invitation.role,
                status=InvitationStatus.REJECTED.value,
            )
            self.agreement_repo.session.add(participant)
        else:
            participant.status = InvitationStatus.REJECTED.value
            self.agreement_repo.session.add(participant)

        self.agreement_repo.session.commit()
        self.agreement_repo.session.refresh(participant)

        agreement = self.agreement_repo.get_by_id(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        agreement.status = "cancelled"
        self.agreement_repo.session.add(agreement)
        self.agreement_repo.session.commit()
        self.agreement_repo.session.refresh(agreement)

        self.agreement_repo.invalidate_agreement_cache(
            agreement_id,
            [agreement.user_id, user_id],
        )

        return self.get_agreement(agreement_id, user_id)

    # def get_invitation  inv
