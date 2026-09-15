"""Platform-staff dispute queue.

A separate module from `dispute.py` so the authorisation boundary is visible at
file level: every route here is gated by `AdminUserDep`, and the service methods
they call are deliberately unscoped.
"""

from fastapi import APIRouter, Query, Request

from app.common.enums import DisputeCategory, DisputeStatus, NotificationType
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
)
from app.logging import get_logger
from app.rate_limiting import limiter
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
):
    """Record a binding outcome and unfreeze the agreement.

    RECORD-ONLY: this moves no money for any outcome. It writes the decision
    and restores the agreement to its pre-dispute status, after which the
    normal release flow can run. Payout and refund remain separate actions.
    """
    dispute = dispute_service.admin_resolve_dispute(
        dispute_id, current_user.id, resolution
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

    return success_response(data=dispute)
