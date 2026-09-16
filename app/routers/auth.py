from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import AuthServiceDep, CurrentUserDep
from app.schemas.auth_schema import (
    InviteRegisterRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshTokenRequest,
    UserCreateRequest,
)
from app.schemas.user_schema import UserResponse

from ..rate_limiting import limiter

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    responses={
        404: {"model": NotFoundResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.post(
    "/register",
    status_code=201,
    response_model=APIResponse[UserResponse],
    responses={401: {"model": UnauthorizedResponse}, 403: {"model": ForbiddenResponse}},
)
@limiter.limit("6/hour")
async def register_user(
    request: Request,
    register_data: UserCreateRequest,
    current_user: CurrentUserDep,
    auth_service: AuthServiceDep,
):
    """Complete the signed-in user's profile (name and phone number)."""
    return success_response(
        data=auth_service.register_user(current_user, register_data), status_code=201
    )


@router.post(
    "/register-from-invite",
    status_code=200,
    response_model=APIResponse[LoginResponse],
)
@limiter.limit("5/minute")
async def invite_register(
    request: Request,
    register_data: InviteRegisterRequest,
    auth_service: AuthServiceDep,
):
    """Sign in (or up) via an invitation link. Works without Redis."""
    auth_service.verify_invitation(register_data.invitation_token)
    return success_response(data=auth_service.verify_id_token(register_data.id_token))


@router.post(
    "/login",
    status_code=200,
    response_model=APIResponse[LoginResponse],
    responses={401: {"model": UnauthorizedResponse}},
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthServiceDep,
):
    """Exchange a Firebase ID token for an access/refresh pair."""
    return success_response(data=auth_service.verify_id_token(login_data.id_token))


@router.post(
    "/refresh",
    status_code=200,
    response_model=APIResponse[LoginResponse],
    responses={401: {"model": UnauthorizedResponse}},
)
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    auth_service: AuthServiceDep,
):
    """Rotate the refresh token. The presented token is invalidated."""
    return success_response(data=auth_service.refresh_token(refresh_data.refresh_token))


@router.post("/logout", status_code=200, response_model=APIResponse[None])
@limiter.limit("10/minute")
async def logout(
    request: Request,
    logout_data: LogoutRequest,
    auth_service: AuthServiceDep,
):
    """Revoke a refresh token. Always succeeds."""
    auth_service.logout(logout_data.refresh_token)
    return success_response(message="Logged out")
