from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, UserServiceDep
from app.exceptions import UserNotFound
from app.rate_limiting import limiter
from app.schemas.user_schema import UpdateUserRequest, UserCreateRequest, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/", status_code=201, response_model=UserResponse)
@limiter.limit("6/hour")
async def register_user(
    request: Request,
    register_data: UserCreateRequest,
    user_service: UserServiceDep,
) -> UserResponse:
    """
    Register a new user.
    """
    try:
        return user_service.register_user(register_data)
    except UserNotFound as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/current", response_model=UserResponse)
@limiter.limit("10/minute")
async def get_current_user(
    request: Request,
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
) -> UserResponse:
    """
    Get the current user.
    """
    try:
        return user_service.get_user(current_user.user_id)
    except UserNotFound as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch("/{user_id}", response_model=UserResponse)
@limiter.limit("10/hour")
async def update_user(
    request: Request,
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
    user_update: UpdateUserRequest,
) -> UserResponse:
    """
    Update the current user.
    """
    try:
        return user_service.update_user(current_user.user_id, user_update)
    except UserNotFound as e:
        raise HTTPException(status_code=404, detail=e.message)
