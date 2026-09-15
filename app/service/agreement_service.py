from dataclasses import dataclass
from decimal import Decimal

from fastapi import BackgroundTasks

from app.common.enums import AgreementStatus, InvitationStatus, ParticipantRole
from app.config import settings
from app.exceptions import (
    AgreementAcceptanceError,
    AgreementCreationError,
    AgreementNotFoundError,
    BadRequestError,
    ForbiddenError,
    InvitationNotFoundError,
    ParticipantNotFoundError,
)
from app.logging import get_logger
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
from app.service import email_service

from ..service.invitation_service import (
    get_invitation_token,
    store_invitation,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class EscrowContext:
    """Everything a money operation needs about an agreement.

    Produced by the `prepare_*` methods, which authorise and validate but never
    touch a balance — the router hands this to `WalletService`, keeping the
    services from calling each other.
    """

    agreement_id: str
    title: str
    amount: Decimal
    depositor_user_id: str
    beneficiary_user_id: str
    depositor_participant_id: str
    beneficiary_participant_id: str


class AgreementService:
    def __init__(self, agreement_repo: AgreementRepository):
        self.agreement_repo = agreement_repo

    # ------------------------------------------------------------------ #
    #  Escrow preparation                                                #
    # ------------------------------------------------------------------ #

    def get_escrow_context(self, agreement_id: str) -> EscrowContext:
        """Resolve both sides of an agreement, or explain what is missing."""
        agreement = self.agreement_repo.get_by_id(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        participants = self.agreement_repo.get_participants_for_agreement(agreement_id)
        depositor = next(
            (p for p in participants if p.role == ParticipantRole.DEPOSITOR), None
        )
        beneficiary = next(
            (p for p in participants if p.role == ParticipantRole.BENEFICIARY), None
        )
        if depositor is None or beneficiary is None:
            raise ParticipantNotFoundError(
                "Agreement does not yet have both a depositor and a beneficiary"
            )

        return EscrowContext(
            agreement_id=agreement.id,
            title=agreement.title,
            amount=agreement.amount,
            depositor_user_id=depositor.user_id,
            beneficiary_user_id=beneficiary.user_id,
            depositor_participant_id=depositor.id,
            beneficiary_participant_id=beneficiary.id,
        )

    def prepare_escrow_funding(self, agreement_id: str, user_id: str) -> EscrowContext:
        """Authorise a depositor to move the agreement amount into escrow.

        Note there is no agreement status change here. Funded-ness is derived
        from the ledger (`is_funded`), so adding a `funded` status value — which
        would silently change what StatsRepository counts as active — is
        unnecessary.
        """
        context = self.get_escrow_context(agreement_id)

        if context.depositor_user_id != user_id:
            raise ForbiddenError("Only the depositor can fund this agreement")

        agreement = self.agreement_repo.get_by_id(agreement_id)
        if agreement is not None and agreement.status in {
            AgreementStatus.CANCELLED,
            AgreementStatus.COMPLETED,
            AgreementStatus.REFUNDED,
            # An open dispute freezes the agreement in both directions: no new
            # money in, and (see prepare_release) none out.
            AgreementStatus.DISPUTED,
        }:
            raise BadRequestError(
                f"An agreement that is {agreement.status} cannot be funded"
            )

        return context

    def prepare_release(self, agreement_id: str) -> EscrowContext:
        """Resolve both sides for a release, and mark the agreement completed.

        The status change is FLUSHED, not committed, so that the following
        `apply_transfer` commits it in the same DB transaction as the money.
        If the transfer fails, the rollback inside the wallet repository
        discards this too.
        """
        context = self.get_escrow_context(agreement_id)

        agreement = self.agreement_repo.get_attached(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        # An open dispute freezes the money. This single check protects BOTH
        # release paths — POST /agreements/{id}/release and the automatic
        # release fired on final condition approval — because both funnel
        # through perform_escrow_release -> prepare_release. Guarding the
        # funnel rather than the two call sites means a future third caller
        # cannot bypass it.
        if agreement.status == AgreementStatus.DISPUTED:
            raise BadRequestError(
                "This agreement is under dispute and cannot be released"
            )

        # A cancelled deal is dead and a refunded one has already paid the
        # escrow back to the depositor — in both cases there is nothing left to
        # release. COMPLETED is deliberately NOT blocked: re-running a release
        # is the idempotent fallback path, and the `esc_rel_{id}` reference
        # collapses it to a replay.
        if agreement.status in {
            AgreementStatus.CANCELLED,
            AgreementStatus.REFUNDED,
        }:
            raise BadRequestError(
                f"An agreement that is {agreement.status} cannot be released"
            )

        agreement.status = AgreementStatus.COMPLETED
        self.agreement_repo.save_agreement(agreement, commit=False)
        return context

    def prepare_refund(self, agreement_id: str) -> EscrowContext:
        """Authorise returning escrowed money to the depositor.

        The counterpart to `prepare_release`. Like it, the status change is
        FLUSHED, not committed, so the following ledger entry commits it in the
        same DB transaction as the money — if the refund fails, the rollback
        inside the wallet repository discards this too.

        Deliberately does NOT block an agreement that is already `refunded`:
        the ledger reference `esc_ref_{agreement_id}` makes a repeat call a
        no-op replay, and blocking here would break that idempotent retry.
        """
        context = self.get_escrow_context(agreement_id)

        agreement = self.agreement_repo.get_attached(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        if agreement.status == AgreementStatus.COMPLETED:
            raise BadRequestError(
                "This agreement has already been released to the beneficiary "
                "and cannot be refunded"
            )

        agreement.status = AgreementStatus.REFUNDED
        self.agreement_repo.save_agreement(agreement, commit=False)
        return context

    def invalidate_agreement_cache(self, agreement_id: str) -> None:
        """Drop the cached agreement for both participants after a state change.

        Easy to forget, and without it `get_by_id` serves a stale status from
        Redis for five minutes.
        """
        try:
            context = self.get_escrow_context(agreement_id)
            self.agreement_repo.invalidate_agreement_cache(
                agreement_id,
                [context.depositor_user_id, context.beneficiary_user_id],
            )
        except Exception:
            logger.warning(
                "failed to invalidate agreement cache",
                extra={"agreement_id": agreement_id},
                exc_info=True,
            )

    def mark_agreement_completed_cache(self, agreement_id: str) -> None:
        """Back-compat alias for `invalidate_agreement_cache`."""
        self.invalidate_agreement_cache(agreement_id)

    def _invite_participant(
        self,
        role: ParticipantRole,
        creator_id: str,
        creator_name: str,
        email: str,
        agreement: Agreement,
        background_tasks: BackgroundTasks,
    ) -> Invitation:
        """Create the invitation row and queue the email. Email only."""
        invitee_role = (
            ParticipantRole.BENEFICIARY
            if role == ParticipantRole.DEPOSITOR
            else ParticipantRole.DEPOSITOR
        )
        invitation_token = get_invitation_token()
        invitation = self.agreement_repo.invite_participant(
            invitation_token,
            creator_id,
            invitee_role.value,
            agreement,
            email,
        )
        invitation_data = InvitationResponse.model_validate(invitation)

        store_invitation(
            self.agreement_repo.redis_client,
            invitation_token,
            invitation_data.model_dump(mode="json"),
        )
        # Served by GET /invite on this API; it deep-links into the app.
        invitation_link = f"{settings.web_url.rstrip('/')}/invite?token={invitation_token}"
        background_tasks.add_task(
            email_service.send_invitation_email,
            email,
            invitation_link,
            creator_name,
            agreement.title,
        )
        logger.info(
            "participant invited",
            extra={
                "role": invitee_role.value,
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
        current_user_email: str = "",
        current_user_name: str = "",
    ) -> AgreementCreateResponse:
        invitee_email = agreement_data.invitee_email
        if current_user_email and invitee_email == current_user_email.lower():
            raise BadRequestError("You cannot invite yourself to an agreement")

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
                role=agreement_data.role.value,
                status=InvitationStatus.ACCEPTED.value,
            )

            self.agreement_repo.flush_participant(creator)

            # invite the other participant (flushed, so we get an id)
            invitation = self._invite_participant(
                agreement_data.role,
                creator.user_id,
                current_user_name,
                invitee_email,
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

            # Ensure the creator participant was persisted. In some rare
            # failure modes the in-memory participant may not have been
            # committed; double-check and insert if missing.
            existing_participant = self.agreement_repo.get_participant_for_user(
                agreement.id, current_user_id
            )
            if existing_participant is None:
                creator_check = AgreementParticipant(
                    user_id=current_user_id,
                    agreement_id=agreement.id,
                    role=agreement_data.role.value,
                    status=InvitationStatus.ACCEPTED.value,
                )
                self.agreement_repo.session.add(creator_check)
                self.agreement_repo.session.commit()
                self.agreement_repo.session.refresh(creator_check)

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

    def get_user_invited_agreements(self, email: str) -> list[InvitationResponse]:
        """Return notifications for all agreements where the user has an invitation."""
        invitations = self.agreement_repo.get_invitations_for_email(email)
        return [InvitationResponse.model_validate(inv) for inv in invitations]

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
        if (
            participant is not None
            and participant.status == InvitationStatus.ACCEPTED.value
        ):
            return self.get_agreement(agreement_id, user_id)

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

        invitation.status = "accepted"
        self.agreement_repo.session.add(invitation)

        self.agreement_repo.session.commit()
        self.agreement_repo.session.refresh(participant)

        agreement = self.agreement_repo.get_attached(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        participants = self.agreement_repo.get_participants_for_agreement(agreement_id)
        accepted_count = sum(
            1 for p in participants if p.status == InvitationStatus.ACCEPTED.value
        )
        if accepted_count >= 2:
            agreement.status = AgreementStatus.ACTIVE
            self.agreement_repo.session.add(agreement)
            self.agreement_repo.session.commit()
            self.agreement_repo.session.refresh(agreement)
        else:
            agreement.status = AgreementStatus.PENDING
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

    def cancel_agreement(self, agreement_id: str, user_id: str) -> AgreementResponse:
        """Cancel an agreement the caller is a participant on.

        This is what the app's "Cancel Agreement" button means, and it is a
        different thing from `reject_agreement`, which declines an INVITATION
        before you have joined.

        The funded case is NOT handled here. Whether money sits in escrow is a
        ledger question, and services do not call each other — so the route
        checks `is_agreement_funded` and refuses before reaching this method.
        A funded deal has to go through dispute -> admin refund instead, or no
        unilateral cancel would be safe: the depositor could otherwise pull
        their money the moment the beneficiary started work.
        """
        agreement = self.agreement_repo.get_attached(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        participant = self.agreement_repo.get_participant_for_user(
            agreement_id, user_id
        )
        if participant is None:
            raise ForbiddenError("You are not a participant on this agreement")

        if agreement.status == AgreementStatus.CANCELLED:
            return self.get_agreement(agreement_id, user_id)

        if agreement.status != AgreementStatus.PENDING and (
            agreement.status != AgreementStatus.ACTIVE
        ):
            raise BadRequestError(
                f"An agreement that is {agreement.status} cannot be cancelled"
            )

        agreement.status = AgreementStatus.CANCELLED
        self.agreement_repo.save_agreement(agreement)
        self.invalidate_agreement_cache(agreement_id)

        logger.info(
            "agreement cancelled",
            extra={"agreement_id": agreement_id, "cancelled_by": user_id},
        )
        return self.get_agreement(agreement_id, user_id)

    def reject_agreement(
        self, agreement_id: str, user_id: str, email: str
    ) -> AgreementResponse:
        """Reject an agreement and mark the participant as rejected."""

        # This method cancels the agreement unconditionally further down, which
        # would otherwise let a party under dispute cancel their way out of the
        # freeze. Checked before any state is written.
        existing = self.agreement_repo.get_by_id(agreement_id)
        if existing is not None and existing.status == AgreementStatus.DISPUTED:
            raise BadRequestError(
                "This agreement is under dispute and cannot be cancelled"
            )

        invitation = self.agreement_repo.get_invitation_by_agreement_id(
            email, agreement_id
        )
        if not invitation:
            raise AgreementAcceptanceError("No invitation found for this agreement")

        participant = self.agreement_repo.get_participant_for_user(
            agreement_id, user_id
        )
        if (
            participant is not None
            and participant.status == InvitationStatus.REJECTED.value
        ):
            return self.get_agreement(agreement_id, user_id)

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

        invitation.status = "expired"
        self.agreement_repo.session.add(invitation)

        self.agreement_repo.session.commit()
        self.agreement_repo.session.refresh(participant)

        agreement = self.agreement_repo.get_attached(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        agreement.status = AgreementStatus.CANCELLED
        self.agreement_repo.session.add(agreement)
        self.agreement_repo.session.commit()
        self.agreement_repo.session.refresh(agreement)

        self.agreement_repo.invalidate_agreement_cache(
            agreement_id,
            [agreement.user_id, user_id],
        )

        return self.get_agreement(agreement_id, user_id)

    # def get_invitation  inv
