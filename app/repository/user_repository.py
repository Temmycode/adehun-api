import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import User
from app.redis import RedisClient

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
    def __init__(self, session: Session, redis_client: Redis):
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

    def get_by_id(self, user_id: str) -> User | None:
        """
        Fetch a user by PK.
        Tries Redis first; falls back to DB and caches the result.
        """
        key = _user_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning cached user id=%d", user_id)
            return User.model_validate(cached)

        logger.debug("DB fetch user id=%d", user_id)
        db_user = self.session.exec(select(User).where(User.user_id == user_id)).first()
        if db_user:
            self._cache_set(key, db_user, _TTL_USER)
        return db_user

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
