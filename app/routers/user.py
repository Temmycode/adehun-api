from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, UserServiceDep
from app.rate_limiting import limiter
from app.schemas.user_schema import UpdateUserRequest, UserResponse

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    responses={
        401: {"model": UnauthorizedResponse},
        404: {"model": NotFoundResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get("/current", response_model=APIResponse[UserResponse])
@limiter.limit("10/minute")
async def get_current_user(
    request: Request,
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
):
    """Get the current user."""
    return success_response(data=user_service.get_user(current_user.id))


@router.patch("/{user_id}", response_model=APIResponse[UserResponse])
@limiter.limit("10/hour")
async def update_user(
    request: Request,
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
    user_update: UpdateUserRequest,
):
    """Update the current user."""
    return success_response(
        data=user_service.update_user(current_user.id, user_update)
    )
