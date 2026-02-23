from fastapi import APIRouter

from app.dependencies import ActiveUserDep, UserServiceDep
from app.schemas.user_schema import UpdateUserRequest, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/current")
async def get_current_user(
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
) -> UserResponse:
    return user_service.get_user(current_user.user_id)


@router.patch("/{user_id}")
async def update_user(
    current_user: ActiveUserDep,
    user_service: UserServiceDep,
    user_update: UpdateUserRequest,
) -> UserResponse:
    return user_service.update_user(current_user.user_id, user_update)
