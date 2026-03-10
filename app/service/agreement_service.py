import logging

from app.common.enums import InvitationStatus, ParticipantRole
from app.exceptions import AgreementCreationError
from app.models import Agreement, AgreementParticipant, Transaction
from app.repository.agreement_repository import AgreementRepository
from app.schemas.agreement_schema import AgreementCreate

logger = logging.getLogger(__name__)


class AgreementService:
    def __init__(
        self,
        agreement_repo: AgreementRepository,
    ):
        self.agreement_repo = agreement_repo

    def create_agreement(
        self, current_user_id: str, agreement_data: AgreementCreate
    ) -> Agreement:
        # create agreement
        agreement = self.agreement_repo.flush(
            Agreement(description=agreement_data.description)
        )

        # create agreement participants
        depositor = AgreementParticipant(
            user_id=current_user_id,
            agreement_id=agreement.agreement_id,
            role=ParticipantRole.DEPOSITOR.value,
            status=InvitationStatus.ACCEPTED.value,
        )
        beneficiaries = [
            AgreementParticipant(
                user_id=participant,
                agreement_id=agreement.agreement_id,
                role=ParticipantRole.BENEFICIARY.value,
            )
            for participant in agreement_data.user_ids
        ]
        participants = [depositor, *beneficiaries]

        for participant in participants:
            self.agreement_repo.flush_participant(participant)

        # create transaction
        transaction = Transaction(
            agreement_id=agreement.agreement_id,
            participant_id=depositor.participant_id,
            amount=agreement_data.amount,
        )

        # save all
        try:
            self.agreement_repo.add_all(*participants, transaction)
            self.agreement_repo.commit()
            self.agreement_repo.refresh(agreement)
            return agreement
        except Exception as err:
            logger.exception("Failed to save agreement")
            self.agreement_repo.rollback()
            raise AgreementCreationError() from err
