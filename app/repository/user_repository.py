import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import Condition, Invitation, User
from app.redis import RedisClient
from app.schemas.user_schema import UpdateUserRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_USER = 60 * 15  # 15 min  – single user record
_TTL_LIST = 60 * 5  # 5 min   – list/collection keys
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_key(user_id: str) -> str:
    return f"user:{user_id}"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class UserRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  User Operations                                                    #
    # ------------------------------------------------------------------ #

    def create_user(self, user: User) -> User:
        """Create User"""
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def register_user(self, user_id: str, phone_number: str, name: str) -> User | None:
        user = self.get_by_id(user_id)
        if not user:
            return None
        user.phone_number = phone_number
        user.name = name
        self.session.commit()
        self.session.refresh(user)
        return user

    def get_by_id(self, user_id: str) -> User | None:
        """
        Fetch a user by PK.
        Tries Redis first; falls back to DB and caches the result.
        """
        key = _user_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("cache hit for user", extra={"user_id": user_id})
            return self.session.merge(User.model_validate(cached))

        logger.debug("fetching user from db", extra={"user_id": user_id})
        db_user = self.session.exec(select(User).where(User.id == user_id)).first()
        if db_user:
            self._cache_set(key, db_user, _TTL_USER)
        else:
            logger.info("user not found", extra={"user_id": user_id})
        return db_user

    def get_by_email(self, email: str) -> User | None:
        """
        Fetch a user by email.
        """
        db_user = self.session.exec(select(User).where(User.email == email)).first()
        return db_user

    def get_invitations_by_email(self, email: str) -> list[Invitation]:
        """
        Fetch all invitations for a user by email.
        """
        db_invitations = self.session.exec(
            select(Invitation).where(Invitation.email == email)
        ).all()
        return list(db_invitations)

    def get_conditions_with_invitations(
        self, invitations: list[str]
    ) -> list[Condition]:
        """
        Fetch all conditions for a list of invitation IDs.
        """
        db_conditions = self.session.exec(
            select(Condition).where(Condition.invitation_id.in_(invitations))  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
        ).all()
        return list(db_conditions)

    def deactive_user(self, user_id: str) -> bool:
        """
        Deactives a users account
        """
        key = _user_key(user_id)
        user = self.get_by_id(user_id)

        if not user:
            return False

        # Delete cache
        self._cache_delete(key)

        # Deactive user account
        user.active = 0
        self.create_user(user)
        return True

    def update_user(self, user_id: str, updated_user: UpdateUserRequest) -> User | None:
        user = self.get_by_id(user_id)

        if not user:
            return None

        updated_fields = []

        if updated_user.name:
            user.name = updated_user.name
            updated_fields.append("name")

        if updated_user.profile_picture_url:
            # user.profile_picture_url = updated_user.profile_picture_url
            updated_fields.append("profile_picture_url")

        if updated_fields:
            self.session.add(user)
            self.session.commit()
            return user

        return None

    def rollback(self):
        self.session.rollback()

    def flush(self, *kwargs):
        self.session.add_all(kwargs)
        self.session.flush()
        return

    def commit(self):
        self.session.commit()
