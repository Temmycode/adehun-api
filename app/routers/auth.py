from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, AuthServiceDep
from app.exceptions import InvitationNotFoundError, UserNotFound
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
    responses={404: {"description": "Not found"}},
)


@router.post("/register", status_code=201, response_model=UserResponse)
@limiter.limit("6/hour")
async def register_user(
    request: Request,
    register_data: UserCreateRequest,
    auth_service: AuthServiceDep,
) -> UserResponse:
    """
    Register a new user.
    """
    try:
        return auth_service.register_user(register_data)
    except UserNotFound as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.post("/register-from-invite", status_code=200, response_model=LoginResponse)
@limiter.limit("5/minute")
async def invite_register(
    request: Request,
    register_data: InviteRegisterRequest,
    auth_service: AuthServiceDep,
):
    """
    Login a user and return a JWT token.
    """
    try:
        auth_service.verify_invitation(register_data.invitation_token)

    except InvitationNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)

    return auth_service.verify_id_token(register_data.id_token)


@router.post("/login", status_code=200, response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthServiceDep,
):
    """
    Login a user and return a JWT token.
    """

    return auth_service.verify_id_token(login_data.id_token)


@router.post("/refresh", status_code=200, response_model=LoginResponse)
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    auth_service: AuthServiceDep,
):
    """
    Refresh a user's JWT token.
    """
    try:
        return auth_service.refresh_token(refresh_data.refresh_token)
    except UserNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
