from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    success_response,
)
from app.dependencies import AuthServiceDep
from app.schemas.auth_schema import (
    InviteRegisterRequest,
    LoginRequest,
    LoginResponse,
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


@router.post("/register", status_code=201, response_model=APIResponse[UserResponse])
@limiter.limit("6/hour")
async def register_user(
    request: Request,
    register_data: UserCreateRequest,
    auth_service: AuthServiceDep,
):
    """
    Register a new user.
    """
    return success_response(data=auth_service.register_user(register_data))


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
    """
    Login a user and return a JWT token.
    """
    auth_service.verify_invitation(register_data.invitation_token)

    return success_response(data=auth_service.verify_id_token(register_data.id_token))


@router.post("/login", status_code=200, response_model=APIResponse[LoginResponse])
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthServiceDep,
):
    """
    Login a user and return a JWT token.
    """

    return success_response(data=auth_service.verify_id_token(login_data.id_token))


@router.post("/refresh", status_code=200, response_model=APIResponse[LoginResponse])
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    auth_service: AuthServiceDep,
):
    """
    Refresh a user's JWT token.
    """

    return success_response(data=auth_service.refresh_token(refresh_data.refresh_token))
