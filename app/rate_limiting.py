from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.logging import get_logger

from .config import settings

logger = get_logger(__name__)

REDIS_URL = (
    f"redis://default:{settings.redis_database_password}"
    f"@{settings.redis_database_host}:{settings.redis_database_port}"
)
MEMORY_URL = "memory://"


def _resolve_storage_uri() -> str:
    """Use Redis when reachable so limits are shared across workers.

    In-memory storage is per process: with N uvicorn workers every limit is
    silently N times more generous and resets on deploy. Falling back keeps
    the app bootable when Redis is down, but that is logged loudly.
    """
    if settings.environment == "test":
        return MEMORY_URL
    try:
        from limits.storage import RedisStorage

        storage = RedisStorage(REDIS_URL)
        storage.check()
        logger.info("rate limiter connected to redis")
        return REDIS_URL
    except Exception:
        logger.warning(
            "rate limiter falling back to in-memory storage; limits are per worker"
        )
        return MEMORY_URL


def client_ip(request: Request) -> str:
    """Rate-limit key.

    Behind a reverse proxy the socket peer is the proxy, so every user would
    share one bucket. Only trust X-Forwarded-For when configured to, and then
    only its first hop (the client), never a value the client can append.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_ip,
    storage_uri=_resolve_storage_uri(),
    # If Redis goes down after startup, let the request through rather than
    # returning a 500 to the caller.
    swallow_errors=True,
)
