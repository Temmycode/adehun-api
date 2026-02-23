import logging

from fastapi import HTTPException
from firebase_admin import auth

from app import token_service
from app.models import User
from app.repository.user_repository import UserRepository
from app.schemas.auth_schema import LoginResponse

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
            user_id=firebase_user.uid,
            email=firebase_user.email,
            name=firebase_user.display_name,
        )

        return self.user_repo.create_user(user)

    def verify_id_token(self, id_token: str) -> LoginResponse:
        """Verify the ID token and return a LoginResponse object."""

        # Verify the ID token using Firebase Admin SDK
        decoded_token = auth.verify_id_token(id_token)

        # Get the user ID from the decoded token
        user_id = decoded_token["uid"]

        # Get the user from the database
        user = self.user_repo.get_by_id(user_id)

        if not user:
            # create a new user
            user = self._create_user(user_id)

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

    def refresh_token(self, refresh_token: str) -> LoginResponse:
        """Refresh the access token using the refresh token."""

        # Verify the refresh token using Firebase Admin SDK
        user_id = token_service.verify_token(refresh_token, "refresh")["sub"]

        # Get the user from the database
        user = self.user_repo.get_by_id(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

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
