from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, NotificationServiceDep
from app.rate_limiting import limiter
from app.schemas.notification_schema import (
    MarkReadRequest,
    MarkReadResponse,
    NotificationListResponse,
    UnreadCountResponse,
)

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get(
    "",
    response_model=APIResponse[NotificationListResponse],
)
@limiter.limit("30/minute")
async def get_notifications(
    request: Request,
    current_user: ActiveUserDep,
    notification_service: NotificationServiceDep,
    skip: int = 0,
    limit: int = 20,
):
    """Get paginated notifications for the authenticated user."""
    return success_response(
        data=notification_service.get_user_notifications(
            current_user.id, skip=skip, limit=limit
        )
    )


@router.get(
    "/unread-count",
    response_model=APIResponse[UnreadCountResponse],
)
@limiter.limit("60/minute")
async def get_unread_count(
    request: Request,
    current_user: ActiveUserDep,
    notification_service: NotificationServiceDep,
):
    """Get the count of unread notifications for the authenticated user."""
    unread_count = notification_service.get_unread_count(current_user.id)
    return success_response(data=UnreadCountResponse(unread_count=unread_count))


@router.patch(
    "/read",
    response_model=APIResponse[MarkReadResponse],
)
@limiter.limit("30/minute")
async def mark_notifications_read(
    request: Request,
    current_user: ActiveUserDep,
    notification_service: NotificationServiceDep,
    payload: MarkReadRequest,
):
    """Mark a list of notifications as read. Silently ignores IDs that don't belong to the user."""
    updated = notification_service.mark_as_read(
        payload.notification_ids, current_user.id
    )
    return success_response(data=MarkReadResponse(updated_count=updated))


@router.patch(
    "/read-all",
    response_model=APIResponse[MarkReadResponse],
)
@limiter.limit("10/minute")
async def mark_all_notifications_read(
    request: Request,
    current_user: ActiveUserDep,
    notification_service: NotificationServiceDep,
):
    """Mark all notifications as read for the authenticated user."""
    updated = notification_service.mark_all_as_read(current_user.id)
    return success_response(data=MarkReadResponse(updated_count=updated))
