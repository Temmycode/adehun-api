from fastapi import APIRouter, Request

from app.common.enums import NotificationType
from app.core.response import (
    APIResponse,
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
    NotificationServiceDep,
)
from app.logging import get_logger
from app.rate_limiting import limiter
from app.schemas.conditions_schema import (
    BatchConditionResponse,
    ConditionCreate,
    ConditionReject,
    ConditionResponse,
)

logger = get_logger(__name__)

router = APIRouter(
    tags=["Conditions"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


def _notify_agreement_participants(
    notification_service,
    agreement_service,
    agreement_id: str,
    acting_user_id: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    metadata: dict,
) -> None:
    """Send a notification to every participant of an agreement except the acting user."""
    try:
        agreement = agreement_service.get_agreement(agreement_id)
    except Exception:
        logger.exception(
            "failed to fetch agreement for participant notifications",
            extra={"agreement_id": agreement_id},
        )
        return

    participants = [
        p for p in (agreement.depositor, agreement.beneficiary) if p is not None
    ]
    recipient_ids = [
        p.user.id for p in participants if p.user.id != acting_user_id
    ]

    for uid in recipient_ids:
        try:
            notification_service.create_notification(
                user_id=uid,
                type=notification_type,
                title=title,
                message=message,
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                "failed to create notification",
                extra={
                    "agreement_id": agreement_id,
                    "recipient_id": uid,
                    "type": notification_type.value,
                },
            )


@router.post(
    "/agreements/{agreement_id}/conditions",
    response_model=APIResponse[ConditionResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("5/minute")
async def add_condition_to_agreement(
    request: Request,
    agreement_id: str,
    condition_data: ConditionCreate,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
):
    """Add a condition to an agreement."""
    condition = condition_service.add_condition(
        agreement_id, current_user.id, condition_data
    )

    _notify_agreement_participants(
        notification_service,
        agreement_service,
        agreement_id=agreement_id,
        acting_user_id=current_user.id,
        notification_type=NotificationType.CONDITION_ADDED,
        title="New Condition Added",
        message=f"{current_user.name} added a new condition",
        metadata={"agreement_id": agreement_id, "condition_id": condition.id},
    )

    return success_response(data=condition)


@router.get(
    "/conditions/",
    response_model=APIResponse[list[BatchConditionResponse]],
)
@limiter.limit("10/minute")
async def get_users_conditions(
    request: Request,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
):
    """Get conditions for the authenticated user."""
    return success_response(
        data=condition_service.get_user_conditions(current_user.id)
    )


@router.get(
    "/conditions/{condition_id}",
    response_model=APIResponse[ConditionResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("10/minute")
async def get_condition_details(
    request: Request,
    condition_id: str,
    _: ActiveUserDep,
    condition_service: ConditionServiceDep,
):
    """Get a condition by id."""
    return success_response(data=condition_service.get_condition(condition_id))


@router.post(
    "/conditions/{condition_id}/approve",
    response_model=APIResponse[ConditionResponse],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("10/minute")
async def approve_condition(
    request: Request,
    condition_id: str,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
):
    """Approve a condition."""
    condition = condition_service.approve_condition(condition_id, current_user.id)

    _notify_agreement_participants(
        notification_service,
        agreement_service,
        agreement_id=condition.created_by_participant.agreement_id,
        acting_user_id=current_user.id,
        notification_type=NotificationType.CONDITION_UPDATED,
        title="Condition Approved",
        message=f"{current_user.name} approved a condition",
        metadata={
            "agreement_id": condition.created_by_participant.agreement_id,
            "condition_id": condition.id,
        },
    )

    return success_response(data=condition)


@router.post(
    "/conditions/{condition_id}/reject",
    response_model=APIResponse[ConditionResponse],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("10/minute")
async def reject_condition(
    request: Request,
    condition_id: str,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,
    reject_data: ConditionReject,
):
    """Reject a condition."""
    condition = condition_service.reject_condition(
        condition_id, current_user.id, reject_data.rejected_reason
    )

    _notify_agreement_participants(
        notification_service,
        agreement_service,
        agreement_id=condition.created_by_participant.agreement_id,
        acting_user_id=current_user.id,
        notification_type=NotificationType.CONDITION_UPDATED,
        title="Condition Rejected",
        message=f"{current_user.name} rejected a condition",
        metadata={
            "agreement_id": condition.created_by_participant.agreement_id,
            "condition_id": condition.id,
        },
    )

    return success_response(data=condition)
