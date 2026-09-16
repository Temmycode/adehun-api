"""Platform-staff dispute queue.

A separate module from `dispute.py` so the authorisation boundary is visible at
file level: every route here is gated by `AdminUserDep`, and the service methods
they call are deliberately unscoped.
"""

from fastapi import APIRouter, Query, Request

from app.common.enums import (
    DisputeCategory,
    DisputeResolutionOutcome,
    DisputeStatus,
    NotificationType,
)
from app.core.response import (
    APIResponse,
    ConflictResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import (
    AdminUserDep,
    AgreementServiceDep,
    DisputeServiceDep,
    NotificationServiceDep,
    TransactionServiceDep,
    WalletServiceDep,
)
from app.logging import get_logger
from app.rate_limiting import limiter
from app.routers.agreement import (
    broadcast_agreement_update,
    perform_escrow_refund,
    perform_escrow_release,
)
from app.routers.dispute import broadcast_dispute_change, notify
from app.schemas.dispute_schema import (
    DisputeListResponse,
    DisputeResolveRequest,
    DisputeResponse,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/admin/disputes",
    tags=["Admin — Disputes"],
    responses={
        401: {"model": UnauthorizedResponse},
        403: {"model": ForbiddenResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get(
    "",
    response_model=APIResponse[DisputeListResponse],
)
@limiter.limit("60/minute")
async def list_disputes(
    request: Request,
    _: AdminUserDep,
    dispute_service: DisputeServiceDep,
    status: DisputeStatus | None = None,
    category: DisputeCategory | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """The dispute queue, newest first. Filterable by status and category."""
    return success_response(
        data=dispute_service.admin_list_disputes(
            status=status, category=category, skip=skip, limit=limit
        )
    )


@router.get(
    "/{dispute_id}",
    response_model=APIResponse[DisputeResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("60/minute")
async def get_dispute(
    request: Request,
    dispute_id: str,
    _: AdminUserDep,
    dispute_service: DisputeServiceDep,
):
    """Any dispute, with its evidence."""
    return success_response(data=dispute_service.admin_get_dispute(dispute_id))


@router.patch(
    "/{dispute_id}/review",
    response_model=APIResponse[DisputeResponse],
    responses={
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("30/minute")
async def mark_under_review(
    request: Request,
    dispute_id: str,
    current_user: AdminUserDep,
    dispute_service: DisputeServiceDep,
    notification_service: NotificationServiceDep,
):
    """Claim a dispute for review, so two admins cannot resolve the same one."""
    dispute = dispute_service.admin_mark_under_review(dispute_id, current_user.id)

    for party in (dispute.raised_by, dispute.against_user):
        if party:
            notify(
                notification_service,
                user_id=party.id,
                type=NotificationType.DISPUTE_UNDER_REVIEW,
                title="Dispute Under Review",
                message=(
                    f"An agent is reviewing the dispute on "
                    f"'{dispute.agreement_title}'"
                ),
                metadata={
                    "dispute_id": dispute.id,
                    "agreement_id": dispute.agreement_id,
                },
            )

    return success_response(data=dispute)


@router.post(
    "/{dispute_id}/resolve",
    response_model=APIResponse[DisputeResponse],
    responses={
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("10/minute")
async def resolve_dispute(
    request: Request,
    dispute_id: str,
    resolution: DisputeResolveRequest,
    current_user: AdminUserDep,
    dispute_service: DisputeServiceDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
    wallet_service: WalletServiceDep,
    transaction_service: TransactionServiceDep,
):
    """Record a binding outcome, unfreeze the agreement, and settle the money.

    * `favour_beneficiary`: escrow is released to the beneficiary. The admin's
      decision stands in for condition approval, so the all-conditions check is
      deliberately bypassed.
    * `favour_depositor`: escrow is refunded to the depositor.
    * `dismissed`: nothing moves; the deal resumes.
    * `split`: rejected at validation (422) until partial settlement exists.

    The decision is committed first. If the payout then fails, the response
    still carries the resolved dispute plus a message; both payout paths are
    idempotent, so the admin re-runs `/release` or `/refund` to settle.
    """
    dispute = dispute_service.admin_resolve_dispute(
        dispute_id, current_user.id, resolution
    )

    payout_message: str | None = None
    agreement_id = dispute.agreement_id
    funded = transaction_service.is_agreement_funded(agreement_id)
    released = transaction_service.is_agreement_released(agreement_id)
    try:
        if funded and not released:
            if resolution.outcome == DisputeResolutionOutcome.FAVOUR_BENEFICIARY:
                perform_escrow_release(
                    agreement_id, agreement_service, wallet_service, notification_service
                )
                await broadcast_agreement_update(
                    agreement_service, agreement_id, event="released"
                )
            elif resolution.outcome == DisputeResolutionOutcome.FAVOUR_DEPOSITOR:
                perform_escrow_refund(
                    agreement_id, agreement_service, wallet_service, notification_service
                )
                await broadcast_agreement_update(
                    agreement_service, agreement_id, event="refunded"
                )
    except Exception:
        logger.exception(
            "dispute resolved but payout failed; retry via /release or /refund",
            extra={"dispute_id": dispute.id, "agreement_id": agreement_id},
        )
        payout_message = (
            "Dispute resolved, but the payout could not be completed. "
            "Retry with POST /agreements/{id}/release or /refund."
        )

    for party in (dispute.raised_by, dispute.against_user):
        if party:
            notify(
                notification_service,
                user_id=party.id,
                type=NotificationType.DISPUTE_RESOLVED,
                title="Dispute Resolved",
                message=(
                    f"The dispute on '{dispute.agreement_title}' has been resolved"
                ),
                metadata={
                    "dispute_id": dispute.id,
                    "agreement_id": dispute.agreement_id,
                    "outcome": str(dispute.resolution_outcome),
                },
            )

    await broadcast_dispute_change(dispute, agreement_service, event="resolved")

    return success_response(data=dispute, message=payout_message)
