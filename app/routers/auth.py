from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, AuthServiceDep
from app.exceptions import UserNotFound
from app.schemas.auth_schema import LoginRequest, LoginResponse, RefreshTokenRequest

from ..rate_limiting import limiter

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    responses={404: {"description": "Not found"}},
)


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
    _: ActiveUserDep,
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
