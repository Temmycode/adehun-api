from fastapi import APIRouter, Request

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
    DisputeServiceDep,
    NotificationServiceDep,
)
from app.logging import get_logger
from app.rate_limiting import limiter
from app.realtime.manager import ws_manager
# agreement.py does not import this module, so there is no cycle. Same
# direction as condition.py, which imports perform_escrow_release from it.
from app.routers.agreement import _send_agreement_ws_payload
from app.schemas.asset_schema import AssetResponse
from app.schemas.dispute_schema import (
    DisputeCreateRequest,
    DisputeEvidenceCreateRequest,
    DisputeListResponse,
    DisputeResponse,
)
from app.schemas.image_upload_schema import SignedUploadResponse

logger = get_logger(__name__)

router = APIRouter(
    tags=["Disputes"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


async def send_dispute_ws_payload(
    user_id: str, dispute: DisputeResponse, event: str = "updated"
) -> None:
    """Push a dispute event to one user over the existing agreement socket.

    `ws_manager` is keyed by user id, so no new websocket endpoint is needed —
    the client switches on `payload["type"]`.
    """
    try:
        await ws_manager.send_to_user(
            user_id,
            {
                "type": "dispute",
                "event": event,
                "dispute_id": dispute.id,
                "agreement_id": dispute.agreement_id,
                "dispute": dispute.model_dump(mode="json"),
            },
        )
    except Exception:
        logger.exception(
            "failed to push dispute websocket event",
            extra={"user_id": user_id, "dispute_id": dispute.id, "event": event},
        )


async def broadcast_dispute_change(
    dispute: DisputeResponse,
    agreement_service,
    event: str,
) -> None:
    """Tell both parties the dispute changed, and that the agreement did too.

    Order matters. The agreement payload is fetched AFTER the service has
    committed and invalidated the cache, so it carries the new status
    (`disputed` / restored) rather than a stale one.
    """
    recipients = [
        u
        for u in (
            dispute.raised_by.id if dispute.raised_by else None,
            dispute.against_user.id if dispute.against_user else None,
        )
        if u
    ]

    for user_id in recipients:
        await send_dispute_ws_payload(user_id, dispute, event=event)

    try:
        agreement = agreement_service.get_agreement(dispute.agreement_id)
        for user_id in recipients:
            await _send_agreement_ws_payload(user_id, agreement, event=event)
    except Exception:
        logger.exception(
            "failed to push agreement update after dispute change",
            extra={"dispute_id": dispute.id, "agreement_id": dispute.agreement_id},
        )


def notify(notification_service, *, user_id, type, title, message, metadata) -> None:
    """Best-effort notification — never fail the request because of one."""
    try:
        notification_service.create_notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "failed to create dispute notification",
            extra={"recipient_id": user_id, "type": str(type)},
        )


@router.get(
    "/agreements/{agreement_id}/disputes/upload-signature",
    response_model=APIResponse[SignedUploadResponse],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("10/minute")
async def get_dispute_upload_signature(
    request: Request,
    agreement_id: str,
    current_user: ActiveUserDep,
    dispute_service: DisputeServiceDep,
):
    """Get a signed Cloudinary upload signature for dispute evidence.

    Upload the file directly to Cloudinary with these params, then send the
    resulting metadata when raising the dispute.
    """
    return success_response(
        data=dispute_service.create_upload_signature(agreement_id, current_user.id)
    )


@router.post(
    "/agreements/{agreement_id}/disputes",
    status_code=201,
    response_model=APIResponse[DisputeResponse],
    responses={
        400: {"model": BadRequestResponse},
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("3/minute")
async def raise_dispute(
    request: Request,
    agreement_id: str,
    dispute_data: DisputeCreateRequest,
    current_user: ActiveUserDep,
    dispute_service: DisputeServiceDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
):
    """Raise a dispute on an agreement.

    Freezes the agreement: while the dispute is open the escrow can be neither
    funded nor released. Only an accepted participant on an active agreement
    may raise one, and only one dispute can be live per agreement.
    """
    dispute = dispute_service.raise_dispute(
        agreement_id, current_user.id, dispute_data
    )

    if dispute.against_user:
        notify(
            notification_service,
            user_id=dispute.against_user.id,
            type=NotificationType.DISPUTE_RAISED,
            title="Dispute Raised",
            message=(
                f"{current_user.name} raised a dispute on "
                f"'{dispute.agreement_title}'"
            ),
            metadata={
                "dispute_id": dispute.id,
                "agreement_id": dispute.agreement_id,
                "category": str(dispute.category),
            },
        )

    await broadcast_dispute_change(dispute, agreement_service, event="raised")

    return success_response(data=dispute, status_code=201)


@router.get(
    "/agreements/{agreement_id}/disputes",
    response_model=APIResponse[list[DisputeResponse]],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("20/minute")
async def get_agreement_disputes(
    request: Request,
    agreement_id: str,
    current_user: ActiveUserDep,
    dispute_service: DisputeServiceDep,
):
    """Disputes on an agreement the caller participates in."""
    return success_response(
        data=dispute_service.get_agreement_disputes(agreement_id, current_user.id)
    )


@router.get(
    "/disputes",
    response_model=APIResponse[DisputeListResponse],
)
@limiter.limit("20/minute")
async def get_my_disputes(
    request: Request,
    current_user: ActiveUserDep,
    dispute_service: DisputeServiceDep,
    skip: int = 0,
    limit: int = 20,
):
    """Every dispute the caller raised or is the respondent on."""
    return success_response(
        data=dispute_service.get_user_disputes(current_user.id, skip, limit)
    )


@router.get(
    "/disputes/{dispute_id}",
    response_model=APIResponse[DisputeResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("20/minute")
async def get_dispute(
    request: Request,
    dispute_id: str,
    current_user: ActiveUserDep,
    dispute_service: DisputeServiceDep,
):
    """A single dispute, with its evidence.

    Returns 404 rather than 403 when the caller is not a party, so dispute
    existence is not disclosed.
    """
    return success_response(
        data=dispute_service.get_dispute(dispute_id, current_user.id)
    )


@router.post(
    "/disputes/{dispute_id}/evidence",
    response_model=APIResponse[list[AssetResponse]],
    responses={
        400: {"model": BadRequestResponse},
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("10/minute")
async def add_dispute_evidence(
    request: Request,
    dispute_id: str,
    evidence_data: DisputeEvidenceCreateRequest,
    current_user: ActiveUserDep,
    dispute_service: DisputeServiceDep,
    notification_service: NotificationServiceDep,
):
    """Attach further evidence to a live dispute. Either party may."""
    assets = dispute_service.add_evidence(dispute_id, current_user.id, evidence_data)

    dispute = dispute_service.get_dispute(dispute_id, current_user.id)
    other = (
        dispute.against_user
        if dispute.raised_by and dispute.raised_by.id == current_user.id
        else dispute.raised_by
    )
    if other:
        notify(
            notification_service,
            user_id=other.id,
            type=NotificationType.DISPUTE_EVIDENCE_ADDED,
            title="New Dispute Evidence",
            message=(
                f"{current_user.name} added evidence to the dispute on "
                f"'{dispute.agreement_title}'"
            ),
            metadata={
                "dispute_id": dispute.id,
                "agreement_id": dispute.agreement_id,
            },
        )

    return success_response(data=assets)
