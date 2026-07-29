from fastapi import APIRouter, BackgroundTasks, Request

from app.common.enums import NotificationType
from app.core.response import (
    APIResponse,
    BadRequestResponse,
    ConflictResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import (
    ActiveUserDep,
    AgreementServiceDep,
    ConditionServiceDep,
    IdempotencyDep,
    NotificationServiceDep,
    TransactionServiceDep,
    UserRepositoryDep,
    WalletServiceDep,
)
from app.exceptions import BadRequestError
from app.logging import get_logger
from app.rate_limiting import limiter
from app.schemas.agreement_schema import (
    AgreementCreate,
    AgreementCreateResponse,
    AgreementInvitationResponse,
    AgreementResponse,
)
from app.schemas.escrow_schema import EscrowMovementResponse

logger = get_logger(__name__)

router = APIRouter(
    prefix="/agreements",
    tags=["Agreements"],
    responses={500: {"model": InternalServerErrorResponse}},
)


@router.get(
    "/",
    response_model=APIResponse[list[AgreementResponse]],
    responses={401: {"model": UnauthorizedResponse}},
)
@limiter.limit("10/minute")
async def get_all_user_agreements(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
):
    """
    Get all agreements for the authenticated user.
    """
    return success_response(
        data=agreement_service.get_all_user_agreements(current_user.id)
    )


@router.post(
    "/",
    status_code=201,
    response_model=APIResponse[AgreementCreateResponse],
    responses={
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
    },
)
@limiter.limit("10/minute")
async def create_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_data: AgreementCreate,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
    user_repository: UserRepositoryDep,
    background_tasks: BackgroundTasks,
):
    """
    Create a new agreement.

    The authenticated user is automatically assigned as the depositor.
    All user IDs provided in `user_ids` are added as beneficiaries.
    """

    agreement = agreement_service.create_agreement(
        current_user.id,
        agreement_data,
        background_tasks,
    )

    invited = user_repository.get_by_email(
        agreement_data.other_participant_email_or_phone
    )
    if invited and invited.id != current_user.id:
        try:
            notification_service.create_notification(
                user_id=invited.id,
                type=NotificationType.INVITATION_RECEIVED,
                title="New Escrow Invitation",
                message=f"{current_user.name} invited you to an escrow agreement",
                metadata={
                    "agreement_id": agreement.id,
                    "invited_by_name": current_user.name,
                },
            )
        except Exception:
            logger.exception(
                "failed to create invitation notification",
                extra={"agreement_id": agreement.id, "invited_user_id": invited.id},
            )

    return success_response(data=agreement, status_code=201)


@router.post(
    "/{agreement_id}/accept",
    response_model=APIResponse[AgreementResponse],
    responses={
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
    },
)
@limiter.limit("10/minute")
async def accept_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
    agreement_id: str,
):
    """
    Accept an agreement.
    """

    agreement = agreement_service.accept_agreement(
        agreement_id, current_user.id, current_user.email
    )

    # Notify only the other party once the agreement is accepted.
    if agreement.depositor and agreement.beneficiary:
        recipient_ids = [
            p.user.id
            for p in (agreement.depositor, agreement.beneficiary)
            if p.user.id != current_user.id
        ]
        for uid in recipient_ids:
            try:
                notification_service.create_notification(
                    user_id=uid,
                    type=NotificationType.AGREEMENT_ACCEPTED,
                    title="Agreement Accepted",
                    message=f"{current_user.name} accepted the agreement",
                    metadata={"agreement_id": agreement.id},
                )
            except Exception:
                logger.exception(
                    "failed to create agreement-accepted notification",
                    extra={"agreement_id": agreement.id, "recipient_id": uid},
                )

    if agreement.status == "active":
        participant_ids = [
            p.user.id
            for p in (agreement.depositor, agreement.beneficiary)
            if p is not None and p.user is not None
        ]
        for uid in participant_ids:
            try:
                notification_service.create_notification(
                    user_id=uid,
                    type=NotificationType.AGREEMENT_COMPLETED,
                    title="Agreement Complete",
                    message="All parties have accepted the agreement",
                    metadata={"agreement_id": agreement.id},
                )
            except Exception:
                logger.exception(
                    "failed to create agreement-completed notification",
                    extra={"agreement_id": agreement.id, "recipient_id": uid},
                )

    return success_response(data=agreement)


@router.post(
    "/{agreement_id}/reject",
    response_model=APIResponse[AgreementResponse],
    responses={
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
    },
)
@limiter.limit("10/minute")
async def reject_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
    agreement_id: str,
):
    """Reject an agreement."""

    agreement = agreement_service.reject_agreement(
        agreement_id, current_user.id, current_user.email
    )

    if agreement.depositor and agreement.beneficiary:
        recipient_ids = [
            p.user.id
            for p in (agreement.depositor, agreement.beneficiary)
            if p.user.id != current_user.id
        ]
        for uid in recipient_ids:
            try:
                notification_service.create_notification(
                    user_id=uid,
                    type=NotificationType.AGREEMENT_DECLINED,
                    title="Agreement Declined",
                    message=f"{current_user.name} declined the agreement",
                    metadata={"agreement_id": agreement.id},
                )
            except Exception:
                logger.exception(
                    "failed to create agreement-declined notification",
                    extra={"agreement_id": agreement.id, "recipient_id": uid},
                )

    return success_response(data=agreement)


@router.get(
    "/{agreement_id}",
    response_model=APIResponse[AgreementResponse],
    responses={
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
    },
)
@limiter.limit("10/minute")
async def get_agreement(
    request: Request,
    _: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    agreement_id: str,
):
    """
    Get an agreement by its ID.
    """

    return success_response(data=agreement_service.get_agreement(agreement_id))


@router.get(
    "/{agreement_id}/invitation",
    response_model=APIResponse[AgreementInvitationResponse],
    responses={
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
    },
)
@limiter.limit("10/minute")
async def get_agreement_invitation(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    agreement_id: str,
):
    """
    Get the invitation details for an agreement.
    This is useful for the client to display the pending invitation without
    relying on cached agreement data.
    """

    return success_response(
        data=agreement_service.get_agreement_invitation(
            agreement_id, current_user.id, current_user.email
        )
    )


# ---------------------------------------------------------------------------
# Escrow
#
# Money movement is orchestrated here, not inside AgreementService: the
# agreement service authorises and validates, the wallet service moves the
# money. Because every repository in a request shares one Session, a change
# flushed by `prepare_release` commits atomically with the transfer.
# ---------------------------------------------------------------------------


@router.post(
    "/{agreement_id}/fund",
    response_model=APIResponse[EscrowMovementResponse],
    responses={
        400: {"model": BadRequestResponse},
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("5/minute")
async def fund_agreement(
    request: Request,
    agreement_id: str,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    wallet_service: WalletServiceDep,
    transaction_service: TransactionServiceDep,
    notification_service: NotificationServiceDep,
    idem: IdempotencyDep,
):
    """Move the agreement amount from the depositor's available balance into escrow.

    Only the depositor may call this, and only once — the ledger reference
    `esc_lock_{agreement_id}` makes a repeat call a no-op replay.

    Requires an `Idempotency-Key` header.
    """
    replay = idem.begin("POST /agreements/{id}/fund", {"agreement_id": agreement_id})
    if replay is not None:
        return replay

    context = agreement_service.prepare_escrow_funding(agreement_id, current_user.id)

    if transaction_service.is_agreement_funded(agreement_id):
        raise BadRequestError("This agreement has already been funded")

    result = wallet_service.lock_escrow(
        user_id=current_user.id,
        amount=context.amount,
        agreement_id=agreement_id,
        participant_id=context.depositor_participant_id,
        counterparty_user_id=context.beneficiary_user_id,
        description=f"Escrow funding for '{context.title}'",
    )

    try:
        notification_service.create_notification(
            user_id=context.beneficiary_user_id,
            type=NotificationType.ESCROW_FUNDED,
            title="Escrow Funded",
            message=f"{current_user.name} funded the escrow for '{context.title}'",
            metadata={"agreement_id": agreement_id, "amount": str(context.amount)},
        )
    except Exception:
        logger.exception(
            "failed to create escrow funding notification",
            extra={"agreement_id": agreement_id},
        )

    idem.bind_reference(result.entry.reference)
    return idem.complete(
        success_response(
            data=EscrowMovementResponse(
                agreement_id=agreement_id,
                amount=context.amount,
                reference=result.entry.reference,
                available_balance=result.wallet.available_balance,
                escrow_balance=result.wallet.escrow_balance,
                replayed=result.replayed,
            )
        )
    )


@router.post(
    "/{agreement_id}/release",
    response_model=APIResponse[EscrowMovementResponse],
    responses={
        400: {"model": BadRequestResponse},
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("5/minute")
async def release_agreement_escrow(
    request: Request,
    agreement_id: str,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    condition_service: ConditionServiceDep,
    wallet_service: WalletServiceDep,
    transaction_service: TransactionServiceDep,
    notification_service: NotificationServiceDep,
    idem: IdempotencyDep,
):
    """Release escrow to the beneficiary.

    Release normally happens automatically the moment the final condition is
    approved. This endpoint is the idempotent fallback for when that automatic
    release could not complete — it re-runs the same operation, and collapses to
    a no-op replay if the money already moved.

    Callable by either participant, and only when the agreement is funded and
    every condition has been approved.

    Requires an `Idempotency-Key` header.
    """
    replay = idem.begin("POST /agreements/{id}/release", {"agreement_id": agreement_id})
    if replay is not None:
        return replay

    context = agreement_service.get_escrow_context(agreement_id)
    if current_user.id not in (
        context.depositor_user_id,
        context.beneficiary_user_id,
    ):
        raise BadRequestError("You are not a participant on this agreement")
    if not transaction_service.is_agreement_funded(agreement_id):
        raise BadRequestError("This agreement has not been funded")
    if not condition_service.all_conditions_approved(agreement_id, current_user.id):
        raise BadRequestError("Not every condition on this agreement is approved yet")

    result = perform_escrow_release(
        agreement_id,
        agreement_service,
        wallet_service,
        notification_service,
    )

    idem.bind_reference(result.debit.reference)
    return idem.complete(
        success_response(
            data=EscrowMovementResponse(
                agreement_id=agreement_id,
                amount=context.amount,
                reference=result.debit.reference,
                available_balance=result.debit.balance_after,
                escrow_balance=result.debit.escrow_after,
                replayed=result.replayed,
            )
        )
    )


def perform_escrow_release(
    agreement_id: str,
    agreement_service,
    wallet_service,
    notification_service,
):
    """Move escrow to the beneficiary and tell both parties.

    Shared by the fallback endpoint above and the automatic release fired from
    the condition-approval route, so the two can never drift apart.
    """
    context = agreement_service.prepare_release(agreement_id)

    result = wallet_service.release_escrow(
        agreement_id=agreement_id,
        depositor_user_id=context.depositor_user_id,
        beneficiary_user_id=context.beneficiary_user_id,
        amount=context.amount,
        description=f"Escrow release for '{context.title}'",
    )

    # Without this, get_by_id serves a stale `status` from Redis for 5 minutes.
    agreement_service.mark_agreement_completed_cache(agreement_id)

    for user_id, message in (
        (
            context.beneficiary_user_id,
            f"{context.amount} has been released to you for '{context.title}'",
        ),
        (
            context.depositor_user_id,
            f"The escrow for '{context.title}' has been released",
        ),
    ):
        try:
            notification_service.create_notification(
                user_id=user_id,
                type=NotificationType.ESCROW_RELEASED,
                title="Escrow Released",
                message=message,
                metadata={
                    "agreement_id": agreement_id,
                    "amount": str(context.amount),
                },
            )
        except Exception:
            logger.exception(
                "failed to create escrow release notification",
                extra={"agreement_id": agreement_id, "recipient_id": user_id},
            )

    return result
