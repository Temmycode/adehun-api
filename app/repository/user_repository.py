from redis import Redis
from sqlmodel import Session, select

from app.logging import get_logger
from app.models import Invitation, User
from app.redis import RedisClient
from app.schemas.user_schema import UpdateUserRequest

logger = get_logger(__name__)

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
        user = self.get_attached(user_id)
        if not user:
            return None
        user.phone_number = phone_number
        user.name = name
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self._cache_delete(_user_key(user_id))
        return user

    def get_attached(self, user_id: str) -> User | None:
        """Always read from the DB; use this on every write path.

        `get_by_id` may return a cached snapshot that is up to 15 minutes old.
        Merging that back into the session and committing would overwrite
        fresher columns (including `active` and `is_admin`) with stale values.
        """
        return self.session.get(User, user_id)

    def get_by_id(self, user_id: str) -> User | None:
        """
        Fetch a user by PK for READ purposes.
        Tries Redis first; falls back to DB and caches the result. The cached
        object is detached — never mutate and commit it.
        """
        key = _user_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("cache hit for user", extra={"user_id": user_id})
            return User.model_validate(cached)

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

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user's account."""
        user = self.get_attached(user_id)
        if not user:
            return False

        user.active = 0
        self.session.add(user)
        self.session.commit()
        self._cache_delete(_user_key(user_id))
        return True

    def update_user(self, user_id: str, updated_user: UpdateUserRequest) -> User | None:
        """Apply the provided fields. A no-op update still returns the user."""
        user = self.get_attached(user_id)
        if not user:
            return None

        changed = False
        if updated_user.name is not None:
            user.name = updated_user.name
            changed = True
        if updated_user.phone_number is not None:
            user.phone_number = updated_user.phone_number
            changed = True
        if updated_user.profile_picture_url is not None:
            user.profile_picture_url = updated_user.profile_picture_url
            changed = True

        if changed:
            self.session.add(user)
            self.session.commit()
            self.session.refresh(user)
            self._cache_delete(_user_key(user_id))
        return user

    def rollback(self):
        self.session.rollback()

    def flush(self, *kwargs):
        self.session.add_all(kwargs)
        self.session.flush()
        return

    def commit(self):
        self.session.commit()
