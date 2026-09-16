from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, UserServiceDep
from app.exceptions import ForbiddenError
from app.rate_limiting import limiter
from app.schemas.image_upload_schema import SignedUploadResponse
from app.schemas.user_schema import UpdateUserRequest, UserResponse
from app.service.image_upload_service import create_upload_signature

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
@limiter.limit("30/minute")
async def get_current_user(
    request: Request,
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
):
    """Get the current user."""
    return success_response(data=user_service.get_user(current_user.id))


@router.get("/upload-signature", response_model=APIResponse[SignedUploadResponse])
@limiter.limit("10/minute")
async def get_profile_upload_signature(
    request: Request,
    current_user: ActiveUserDep,
):
    """Signed Cloudinary upload for the caller's profile picture."""
    return success_response(
        data=create_upload_signature(f"profiles/{current_user.id}")
    )


@router.patch(
    "/{user_id}",
    response_model=APIResponse[UserResponse],
    responses={403: {"model": ForbiddenResponse}},
)
@limiter.limit("10/hour")
async def update_user(
    request: Request,
    user_id: str,
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
    user_update: UpdateUserRequest,
):
    """Update the caller's own profile. Any other id is refused."""
    if user_id != current_user.id:
        raise ForbiddenError("You can only update your own profile")
    return success_response(
        data=user_service.update_user(current_user.id, user_update)
    )
