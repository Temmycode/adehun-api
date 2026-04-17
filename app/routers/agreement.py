from fastapi import APIRouter, BackgroundTasks, Request

from app.common.enums import NotificationType
from app.core.response import (
    APIResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import (
    ActiveUserDep,
    AgreementServiceDep,
    NotificationServiceDep,
    UserRepositoryDep,
)
from app.logging import get_logger
from app.rate_limiting import limiter
from app.schemas.agreement_schema import (
    AgreementCreate,
    AgreementCreateResponse,
    AgreementResponse,
)

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

    invited = user_repository.get_by_email(agreement_data.other_participant_email_or_phone)
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
    "/{agreement_id}/",
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

    participants = [
        p for p in (agreement.depositor, agreement.beneficiary) if p is not None
    ]
    other_user_ids = [
        p.user.id for p in participants if p.user.id != current_user.id
    ]

    for uid in other_user_ids:
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

    # Agreement is complete once both depositor and beneficiary are present
    if agreement.depositor and agreement.beneficiary:
        all_user_ids = [p.user.id for p in participants]
        for uid in all_user_ids:
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
