import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings

logger = logging.getLogger(__name__)

REDIS_URL = (
    f"redis://default:{settings.redis_database_password}"
    f"@{settings.redis_database_host}:{settings.redis_database_port}"
)
MEMORY_URL = "memory://"


def _resolve_storage_uri() -> str:
    """
    Try to reach Redis. If it is reachable, use it as the rate-limit
    storage backend. Otherwise fall back to an in-process memory store so
    that the application can still start and serve requests without Redis.
    """
    try:
        # Import here so a missing extras install doesn't break the module.
        from limits.storage import RedisStorage

        storage = RedisStorage(REDIS_URL)
        # check() sends a PING and raises if the server is unreachable.
        storage.check()
        logger.info("Rate limiter: connected to Redis — using Redis storage")
        return REDIS_URL
    except Exception:
        logger.warning(
            "Rate limiter: Redis is unreachable — falling back to in-memory storage. "
            "Rate limits will not be shared across multiple workers.",
        )
        return MEMORY_URL


limiter = Limiter(
    key_func=get_remote_address,
    # storage_uri=_resolve_storage_uri(),
    # # If Redis goes down *after* startup, swallow the storage error and let
    # # the request through rather than returning a 500 to the caller.
    swallow_errors=True,
)
