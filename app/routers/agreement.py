from fastapi import APIRouter, BackgroundTasks, Request, WebSocket, status

from app.common.enums import NotificationType
from app.core.authz import require_read_access
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
from app.database import SessionDep
from app.dependencies import (
    ActiveUserDep,
    AdminUserDep,
    AgreementServiceDep,
    ConditionServiceDep,
    IdempotencyDep,
    NotificationServiceDep,
    RequiredIdempotencyDep,
    TransactionServiceDep,
    UserRepositoryDep,
    WalletServiceDep,
)
from app.exceptions import BadRequestError
from app.logging import get_logger
from app.models import User
from app.rate_limiting import limiter
from app.realtime.manager import ws_manager
from app.schemas.agreement_schema import (
    AgreementCreate,
    AgreementCreateResponse,
    AgreementInvitationResponse,
    AgreementResponse,
    InvitationResponse,
)
from app.schemas.escrow_schema import EscrowMovementResponse
from app.service.token_service import get_user_id_from_ws

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


@router.get(
    "/invited",
    response_model=APIResponse[list[InvitationResponse]],
    responses={401: {"model": UnauthorizedResponse}},
)
@limiter.limit("10/minute")
async def get_invited_agreements(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
):
    """
    Get all agreements the authenticated user has been invited to.
    """
    return success_response(
        data=agreement_service.get_user_invited_agreements(current_user.email)
    )


async def _send_agreement_ws_payload(user_id: str, agreement, event: str = "updated"):
    try:
        await ws_manager.send_to_user(
            user_id,
            {
                "type": "agreement",
                "event": event,
                "agreement_id": agreement.id,
                "agreement": agreement.model_dump(mode="json"),
            },
        )
    except Exception:
        logger.exception(
            "failed to push agreement websocket event",
            extra={"user_id": user_id, "agreement_id": agreement.id, "event": event},
        )


async def broadcast_agreement_update(
    agreement_service,
    agreement_id: str,
    event: str = "updated",
) -> None:
    """Push the current agreement state to both participants over /agreements/ws.

    Best-effort: a websocket failure must never break the HTTP request that
    triggered it.
    """
    try:
        agreement = agreement_service.get_agreement(agreement_id)
        recipients = {
            p.user.id
            for p in (agreement.depositor, agreement.beneficiary)
            if p is not None and p.user is not None
        }
        for user_id in recipients:
            await _send_agreement_ws_payload(user_id, agreement, event=event)
    except Exception:
        logger.exception(
            "failed to broadcast agreement update",
            extra={"agreement_id": agreement_id, "event": event},
        )


@router.websocket("/ws")
async def agreement_websocket(
    websocket: WebSocket,
    agreement_service: AgreementServiceDep,
    session: SessionDep,
):
    """Agreement and dispute events for the authenticated user.

    Auth is `?token=<access_token>` — WebSocket handshakes cannot carry an
    Authorization header. Frame shapes are documented in docs/websockets.md;
    FastAPI does not emit WebSocket routes into openapi.json.
    """
    user_id = get_user_id_from_ws(websocket, session)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = session.get(User, user_id)
    user_email = user.email if user else ""

    await ws_manager.connect(user_id, websocket)
    await websocket.send_json(
        {"type": "connected", "message": "Agreement websocket connected"}
    )

    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") == "get_agreement":
                agreement_id = payload.get("agreement_id")
                if not agreement_id:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "agreement_id is required",
                        }
                    )
                    continue
                try:
                    require_read_access(session, agreement_id, user_id, user_email)
                    agreement = agreement_service.get_agreement(agreement_id, user_id)
                    await websocket.send_json(
                        {
                            "type": "agreement",
                            "agreement_id": agreement.id,
                            "agreement": agreement.model_dump(mode="json"),
                        }
                    )
                except Exception:
                    logger.exception(
                        "failed to fetch agreement for websocket request",
                        extra={"user_id": user_id, "agreement_id": agreement_id},
                    )
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Unable to fetch agreement",
                            "agreement_id": agreement_id,
                        }
                    )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Unsupported websocket event type",
                    }
                )
    finally:
        ws_manager.disconnect(user_id, websocket)


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
        current_user_email=current_user.email,
        current_user_name=current_user.name,
    )

    invited = user_repository.get_by_email(
        agreement_data.other_participant_email_or_phone
    )
    # The invitation was created for the other participant's email, so lookup
    # the invitation using that email (not the creator's email).
    invitation = agreement_service.agreement_repo.get_invitation_by_agreement_id(
        agreement_data.other_participant_email_or_phone, agreement.id
    )
    if invited and invited.id != current_user.id:
        try:
            notification_service.create_notification(
                user_id=invited.id,
                type=NotificationType.INVITATION_RECEIVED,
                title="New Escrow Invitation",
                message=f"{current_user.name} invited you to an escrow agreement",
                metadata=(
                    InvitationResponse.model_validate(invitation).model_dump(
                        mode="json"
                    )
                    if invitation
                    else {}
                ),
            )
        except Exception:
            logger.exception(
                "failed to create invitation notification",
                extra={"agreement_id": agreement.id, "invited_user_id": invited.id},
            )

        await _send_agreement_ws_payload(invited.id, agreement, event="created")

    await _send_agreement_ws_payload(current_user.id, agreement, event="created")
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
    idem: IdempotencyDep,
):
    """
    Accept an agreement.
    """
    replay = idem.begin("POST /agreements/{id}/accept", {"agreement_id": agreement_id})
    if replay is not None:
        return replay

    agreement = agreement_service.accept_agreement(
        agreement_id, current_user.id, current_user.email
    )

    # Notify only the other party once the agreement is accepted.
    participant_ids = []
    if agreement.depositor and agreement.beneficiary:
        participant_ids = [
            p.user.id
            for p in (agreement.depositor, agreement.beneficiary)
            if p is not None and p.user is not None
        ]
        recipient_ids = [uid for uid in participant_ids if uid != current_user.id]
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

    for uid in set(participant_ids + [current_user.id]):
        await _send_agreement_ws_payload(uid, agreement, event="updated")

    return idem.complete(success_response(data=agreement))


@router.post(
    "/{agreement_id}/reject",
    response_model=APIResponse[AgreementResponse],
    responses={
        400: {"model": BadRequestResponse},
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("10/minute")
async def reject_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    transaction_service: TransactionServiceDep,
    notification_service: NotificationServiceDep,
    agreement_id: str,
    idem: IdempotencyDep,
):
    """Decline an invitation to an agreement.

    This is for declining BEFORE you have joined. To end an agreement you have
    already accepted, use `POST /agreements/{id}/cancel`. Both end with the
    agreement `cancelled`, but only this one also marks your invitation
    rejected.

    Refuses once the escrow is funded — cancelling then would strand the money
    with no way to get it back. A funded deal has to go through
    `POST /agreements/{id}/disputes` and an admin refund instead.

    Send an `Idempotency-Key` header to make a retry safe.
    """
    replay = idem.begin("POST /agreements/{id}/reject", {"agreement_id": agreement_id})
    if replay is not None:
        return replay

    # Checked here rather than in the service: whether money sits in escrow is
    # a ledger question, and services never call other services.
    if transaction_service.is_agreement_funded(
        agreement_id
    ) and not transaction_service.is_agreement_released(agreement_id):
        raise BadRequestError(
            "This agreement is funded and cannot be rejected. "
            "Raise a dispute so an admin can refund the escrow."
        )

    agreement = agreement_service.reject_agreement(
        agreement_id, current_user.id, current_user.email
    )

    participant_ids = []
    if agreement.depositor and agreement.beneficiary:
        participant_ids = [
            p.user.id
            for p in (agreement.depositor, agreement.beneficiary)
            if p is not None and p.user is not None
        ]
        recipient_ids = [uid for uid in participant_ids if uid != current_user.id]
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

    for uid in set(participant_ids + [current_user.id]):
        await _send_agreement_ws_payload(uid, agreement, event="updated")

    return idem.complete(success_response(data=agreement))


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
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    session: SessionDep,
    agreement_id: str,
):
    """Get an agreement. Participants and pending invitees only."""
    require_read_access(session, agreement_id, current_user.id, current_user.email)
    return success_response(
        data=agreement_service.get_agreement(agreement_id, current_user.id)
    )


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
    idem: RequiredIdempotencyDep,
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

    agreement_payload = agreement_service.get_agreement(agreement_id)
    await _send_agreement_ws_payload(current_user.id, agreement_payload)
    await _send_agreement_ws_payload(context.beneficiary_user_id, agreement_payload)

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
    idem: RequiredIdempotencyDep,
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

    await broadcast_agreement_update(agreement_service, agreement_id, event="released")

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


@router.post(
    "/{agreement_id}/cancel",
    response_model=APIResponse[AgreementResponse],
    responses={
        400: {"model": BadRequestResponse},
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("10/minute")
async def cancel_agreement(
    request: Request,
    agreement_id: str,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    transaction_service: TransactionServiceDep,
    notification_service: NotificationServiceDep,
):
    """Cancel an agreement you are a participant on.

    Callable by either participant while the agreement is `pending` or
    `active`, and only while the escrow is UNFUNDED. Once money is in escrow a
    unilateral cancel would let the depositor pull their funds the moment the
    beneficiary started work, so a funded deal must go through
    `POST /agreements/{id}/disputes` and an admin refund instead.

    Already-cancelled agreements return 200 with no change, so a double tap is
    harmless.
    """
    if transaction_service.is_agreement_funded(
        agreement_id
    ) and not transaction_service.is_agreement_released(agreement_id):
        raise BadRequestError(
            "This agreement is funded and cannot be cancelled. "
            "Raise a dispute so an admin can refund the escrow."
        )

    agreement = agreement_service.cancel_agreement(agreement_id, current_user.id)

    participant_ids = [
        p.user.id
        for p in (agreement.depositor, agreement.beneficiary)
        if p is not None and p.user is not None
    ]
    for uid in participant_ids:
        if uid == current_user.id:
            continue
        try:
            notification_service.create_notification(
                user_id=uid,
                type=NotificationType.AGREEMENT_CANCELLED,
                title="Agreement Cancelled",
                message=f"{current_user.name} cancelled '{agreement.title}'",
                metadata={"agreement_id": agreement.id},
            )
        except Exception:
            logger.exception(
                "failed to create agreement-cancelled notification",
                extra={"agreement_id": agreement.id, "recipient_id": uid},
            )

    for uid in set(participant_ids + [current_user.id]):
        await _send_agreement_ws_payload(uid, agreement, event="cancelled")

    return success_response(data=agreement)


@router.post(
    "/{agreement_id}/refund",
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
async def refund_agreement_escrow(
    request: Request,
    agreement_id: str,
    current_user: AdminUserDep,
    agreement_service: AgreementServiceDep,
    wallet_service: WalletServiceDep,
    transaction_service: TransactionServiceDep,
    notification_service: NotificationServiceDep,
    idem: RequiredIdempotencyDep,
):
    """Return escrowed money to the depositor. **Admin only.**

    The counterpart to `/release`, and the way a dispute resolved
    `favour_depositor` actually pays out — resolving a dispute records the
    decision but moves no money, so this is the explicit second step.

    Also the remedy when a funded agreement needs to be unwound for any other
    reason. Sets the agreement to `refunded`, which permanently blocks any
    later funding or release.

    Restricted to admins because it moves money against the beneficiary's
    interest. Idempotent on the ledger reference `esc_ref_{agreement_id}`, so a
    repeat call is a no-op replay rather than a second refund.

    Requires an `Idempotency-Key` header.
    """
    replay = idem.begin("POST /agreements/{id}/refund", {"agreement_id": agreement_id})
    if replay is not None:
        return replay

    if not transaction_service.is_agreement_funded(agreement_id):
        raise BadRequestError("This agreement has not been funded")
    if transaction_service.is_agreement_released(agreement_id):
        raise BadRequestError(
            "This agreement's escrow has already been released to the beneficiary"
        )

    context, result = perform_escrow_refund(
        agreement_id, agreement_service, wallet_service, notification_service
    )

    await broadcast_agreement_update(agreement_service, agreement_id, event="refunded")

    logger.warning(
        "escrow refunded by admin",
        extra={
            "agreement_id": agreement_id,
            "admin_user_id": current_user.id,
            "amount": str(context.amount),
        },
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


def perform_escrow_refund(
    agreement_id: str,
    agreement_service,
    wallet_service,
    notification_service,
):
    """Return escrow to the depositor and tell both parties.

    Shared by the admin `/refund` endpoint and the dispute-resolution route so
    a `favour_depositor` outcome pays out through exactly the same code.
    Idempotent on `esc_ref_{agreement_id}`.
    """
    # Flushes status = refunded, committed atomically with the ledger entry.
    context = agreement_service.prepare_refund(agreement_id)

    result = wallet_service.refund_escrow(
        agreement_id=agreement_id,
        depositor_user_id=context.depositor_user_id,
        amount=context.amount,
        description=f"Escrow refund for '{context.title}'",
    )

    # Without this, get_by_id serves a stale status from Redis for 5 minutes.
    agreement_service.invalidate_agreement_cache(agreement_id)

    for user_id, message in (
        (
            context.depositor_user_id,
            f"{context.amount} has been refunded to you for '{context.title}'",
        ),
        (
            context.beneficiary_user_id,
            f"The escrow for '{context.title}' was refunded to the depositor",
        ),
    ):
        try:
            notification_service.create_notification(
                user_id=user_id,
                type=NotificationType.ESCROW_REFUNDED,
                title="Escrow Refunded",
                message=message,
                metadata={"agreement_id": agreement_id, "amount": str(context.amount)},
            )
        except Exception:
            logger.exception(
                "failed to create escrow refund notification",
                extra={"agreement_id": agreement_id, "recipient_id": user_id},
            )

    return context, result


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
    agreement_service.invalidate_agreement_cache(agreement_id)

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
