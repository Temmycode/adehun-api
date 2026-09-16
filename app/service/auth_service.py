from datetime import datetime, timezone
from uuid import uuid4

from firebase_admin import auth

from app.common.enums import NotificationType
from app.exceptions import (
    ForbiddenError,
    InvitationNotFoundError,
    UnauthorizedError,
    UserNotFoundError,
)
from app.logging import get_logger
from app.models import User
from app.repository.refresh_token_repository import RefreshTokenRepository
from app.repository.user_repository import UserRepository
from app.schemas.auth_schema import LoginResponse, UserCreateRequest
from app.schemas.user_schema import UserResponse
from app.service import token_service
from app.service.invitation_service import validate_token
from app.service.notification_service import NotificationService

logger = get_logger(__name__)


class AuthService:
    """Authentication: Firebase ID token exchange, JWT issue/refresh/revoke."""

    def __init__(
        self,
        user_repo: UserRepository,
        refresh_token_repo: RefreshTokenRepository,
        notification_service: NotificationService | None = None,
    ):
        self.user_repo = user_repo
        self.refresh_token_repo = refresh_token_repo
        self.notification_service = notification_service

    # ------------------------------------------------------------------ #
    #  Token pairs                                                        #
    # ------------------------------------------------------------------ #

    def _issue_token_pair(self, user_id: str) -> tuple[str, str]:
        """Mint an access + refresh token and persist the refresh jti."""
        jti = uuid4().hex
        expires_at = datetime.now(timezone.utc) + token_service.token_lifetime(
            "refresh"
        )
        self.refresh_token_repo.create(jti, user_id, expires_at)
        access_token = token_service.create_token(user_id, "access")
        refresh_token = token_service.create_token(user_id, "refresh", jti=jti)
        self.refresh_token_repo.commit()
        return access_token, refresh_token

    # ------------------------------------------------------------------ #
    #  Registration                                                       #
    # ------------------------------------------------------------------ #

    def _create_user(self, user_id: str) -> User:
        firebase_user = auth.get_user(user_id)
        user = User(
            id=user_id,
            email=firebase_user.email,
            name=firebase_user.display_name or "",
            profile_picture_url=firebase_user.photo_url,
            phone_number=None,
        )
        return self.user_repo.create_user(user)

    def register_user(
        self, current_user: User, register_data: UserCreateRequest
    ) -> UserResponse:
        """Complete the profile of the caller. Never touches another account."""
        if register_data.user_id and register_data.user_id != current_user.id:
            logger.warning(
                "register attempted for a different user",
                extra={"user_id": current_user.id},
            )
            raise ForbiddenError("You can only complete your own profile")

        user = self.user_repo.register_user(
            current_user.id, register_data.phone_number, register_data.name
        )
        if not user:
            raise UserNotFoundError()
        return UserResponse.model_validate(user)

    def verify_invitation(self, invitation_token: str) -> dict:
        """Verify the invitation token and return the stored invitation."""
        invitation = validate_token(
            self.user_repo.redis_client, invitation_token, self.user_repo.session
        )
        if not invitation:
            raise InvitationNotFoundError()
        return invitation

    # ------------------------------------------------------------------ #
    #  Login                                                              #
    # ------------------------------------------------------------------ #

    def verify_id_token(self, id_token: str) -> LoginResponse:
        """Exchange a Firebase ID token for our own token pair."""
        try:
            decoded_token = auth.verify_id_token(id_token)
        except (
            auth.InvalidIdTokenError,
            auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError,
            auth.CertificateFetchError,
            ValueError,
        ) as exc:
            logger.info(
                "firebase id token rejected", extra={"reason": type(exc).__name__}
            )
            raise UnauthorizedError("Invalid or expired credentials") from exc

        user_id = decoded_token["uid"]
        firebase_user = auth.get_user(user_id)
        user_email = firebase_user.email

        user = self.user_repo.get_by_email(user_email)
        is_signed_up = user is not None

        if user is None:
            user = self._create_user(user_id)
            self._notify_pending_invitations(user)
        elif user.active == 0:
            raise UnauthorizedError("This account has been deactivated")

        access_token, refresh_token = self._issue_token_pair(user.id)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            is_signed_up=is_signed_up,
            user=UserResponse.model_validate(user),
        )

    def _notify_pending_invitations(self, user: User) -> None:
        if not self.notification_service:
            return

        for invitation in self.user_repo.get_invitations_by_email(user.email):
            try:
                inviter = (
                    invitation.invited_by_user.name
                    if invitation.invited_by_user
                    else "a sender"
                )
                self.notification_service.create_notification(
                    user_id=user.id,
                    type=NotificationType.INVITATION_RECEIVED,
                    title="New Escrow Invitation",
                    message=f"You have been invited to an escrow agreement by {inviter}",
                    metadata={"agreement_id": invitation.agreement_id},
                )
            except Exception:
                logger.exception(
                    "failed to create pending invitation notification",
                    extra={"user_id": user.id, "agreement_id": invitation.agreement_id},
                )

    # ------------------------------------------------------------------ #
    #  Refresh / logout                                                   #
    # ------------------------------------------------------------------ #

    def refresh_token(self, refresh_token: str) -> LoginResponse:
        """Rotate a refresh token. Reuse of a consumed token kills the family."""
        payload = token_service.verify_token(refresh_token, "refresh")
        user_id = payload["sub"]

        row = self.refresh_token_repo.get(payload["jti"])
        if row is None or row.user_id != user_id:
            raise UnauthorizedError("Could not validate credentials")

        if row.revoked_at is not None:
            # A token we already rotated is being presented again: either the
            # client lost the response or someone copied the token. Both cases
            # are safest handled by forcing a fresh login everywhere.
            self.refresh_token_repo.revoke_all_for_user(user_id)
            self.refresh_token_repo.commit()
            logger.warning(
                "refresh token reuse detected; all sessions revoked",
                extra={"user_id": user_id},
            )
            raise UnauthorizedError("Session expired, please sign in again")

        if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise UnauthorizedError("Session expired, please sign in again")

        user = self.user_repo.get_by_id(user_id)
        if not user or user.active == 0:
            raise UnauthorizedError("Could not validate credentials")

        new_jti = uuid4().hex
        self.refresh_token_repo.revoke(row, replaced_by=new_jti)
        expires_at = datetime.now(timezone.utc) + token_service.token_lifetime(
            "refresh"
        )
        self.refresh_token_repo.create(new_jti, user_id, expires_at)
        access_token = token_service.create_token(user_id, "access")
        new_refresh = token_service.create_token(user_id, "refresh", jti=new_jti)
        self.refresh_token_repo.commit()

        return LoginResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            user=UserResponse.model_validate(user),
        )

    def logout(self, refresh_token: str) -> None:
        """Best-effort revoke. Invalid tokens are ignored: logout must not fail."""
        try:
            payload = token_service.verify_token(refresh_token, "refresh")
        except Exception:
            return
        row = self.refresh_token_repo.get(payload["jti"])
        if row is not None and row.revoked_at is None:
            self.refresh_token_repo.revoke(row)
            self.refresh_token_repo.commit()
