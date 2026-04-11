import logging

from firebase_admin import auth

from app import token_service
from app.exceptions import InvitationNotFoundError, UserNotFound
from app.models import User
from app.repository.user_repository import UserRepository
from app.schemas.auth_schema import LoginResponse, UserCreateRequest
from app.schemas.user_schema import UserResponse

from ..service.invitation_service import validate_token

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling authentication and authorization."""

    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def _create_user(self, user_id: str):
        """Create a new user in the database."""
        firebase_user = auth.get_user(user_id)

        # Create internal user model
        user = User(
            id=user_id,
            email=firebase_user.email,
            name=firebase_user.display_name,
            profile_picture_url=firebase_user.photo_url,
            phone_number=None,
        )

        return self.user_repo.create_user(user)

    def register_user(self, register_data: UserCreateRequest) -> UserResponse:
        user = self.user_repo.register_user(
            register_data.user_id, register_data.phone_number, register_data.name
        )
        if not user:
            logger.error(
                "registration failed, user not found",
                extra={"user_id": register_data.user_id},
            )
            raise UserNotFound()
        return UserResponse.model_validate(user)

    def verify_invitation(self, invitation_token: str) -> dict:
        """Verify the invitation token and return the user email"""
        if not self.user_repo.redis_client:
            raise InvitationNotFoundError()

        return validate_token(self.user_repo.redis_client, invitation_token)

    def verify_id_token(self, id_token: str) -> LoginResponse:
        """Verify the ID token and return a LoginResponse object."""

        is_signed_up = False

        # Verify the ID token using Firebase Admin SDK
        decoded_token = auth.verify_id_token(id_token)

        # Get the user ID from the decoded token
        user_id = decoded_token["uid"]

        # check if the user exists in the database through invitation
        firebase_user = auth.get_user(user_id)
        user_email = firebase_user.email

        # Get the user from the database
        user = self.user_repo.get_by_email(user_email)

        if not user:
            # create a new user
            user = self._create_user(user_id)
        else:
            is_signed_up = True

        # Create tokens for user
        access_token = token_service.create_token(user_id, "access")
        refresh_token = token_service.create_token(user_id, "refresh")

        # Create a LoginResponse object with the user information
        response = LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            is_signed_up=is_signed_up,
            user=user,  # pyright: ignore[reportArgumentType]
        )

        return response

    def refresh_token(self, refresh_token: str) -> LoginResponse:
        """Refresh the access token using the refresh token."""

        # Verify the refresh token using Firebase Admin SDK
        user_id = token_service.verify_token(refresh_token, "refresh")["sub"]

        # Get the user from the database
        user = self.user_repo.get_by_id(user_id)

        if not user:
            raise UserNotFound("User not found")

        # Create tokens for user
        access_token = token_service.create_token(user_id, "access")
        refresh_token = token_service.create_token(user_id, "refresh")

        # Create a LoginResponse object with the user information
        response = LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user,  # pyright: ignore[reportArgumentType]
        )

        return response
