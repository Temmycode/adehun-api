import logging

from firebase_admin import auth

from app.exceptions import UserNotFound
from app.repository.user_repository import UserRepository
from app.schemas.user_schema import UpdateUserRequest, UserResponse

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def update_user(
        self, user_id: str, updated_user: UpdateUserRequest
    ) -> UserResponse:
        user = self.repository.update_user(user_id, updated_user)

        if not user:
            logger.exception("Update failed: user not found id=%s", user_id)
            raise UserNotFound()

        return UserResponse.model_validate(user)

    def get_user(self, user_id: str) -> UserResponse:
        user = self.repository.get_by_id(user_id)

        if not user:
            logger.exception("User not found id=%s", user_id)
            raise UserNotFound()

        return UserResponse.model_validate(user)
