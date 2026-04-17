import json
from app.logging import get_logger
from typing import Annotated, Any, Generator

from fastapi import Depends
from redis import Redis

from app.config import settings

logger = get_logger(__name__)


_redis_client: Redis | None = None


def get_redis_client() -> Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = Redis(
                host=settings.redis_database_host,
                port=int(settings.redis_database_port),
                decode_responses=True,
                username="default",
                password=settings.redis_database_password,
            )
            _redis_client.ping()
            logger.info(
                "redis client initialized",
                extra={
                    "host": settings.redis_database_host,
                    "port": settings.redis_database_port,
                },
            )
        except Exception:
            _redis_client = None
            logger.exception(
                "failed to initialize redis client",
                extra={
                    "host": settings.redis_database_host,
                    "port": settings.redis_database_port,
                },
            )

    return _redis_client


def get_redis_dep() -> Generator[Redis | None, Any, None]:
    yield get_redis_client()


RedisDep = Annotated[Redis | None, Depends(get_redis_dep)]


class RedisClient:
    def __init__(self, client: Redis | None):
        self.redis_client = client

    def _serialize(self, obj: Any) -> str:
        """Serialize a SQLModel/dict to a JSON string."""
        if hasattr(obj, "model_dump"):
            return json.dumps(obj.model_dump(mode="json"))
        return json.dumps(obj)

    def _cache_get(self, key: str) -> Any | None:
        """Return parsed JSON value from Redis, or None on miss/error."""
        if self.redis_client is None:
            return None
        try:
            raw = self.redis_client.get(key)
            if raw is None:
                logger.debug("cache miss", extra={"key": key})
                return None
            logger.debug("cache hit", extra={"key": key})
            return json.loads(raw)  # pyright: ignore[reportArgumentType]
        except Exception:
            logger.warning(
                "redis GET failed, falling back to db",
                extra={"key": key},
                exc_info=True,
            )
            return None

    def _cache_set(self, key: str, value: Any, ttl: int):
        if self.redis_client is None:
            return None
        try:
            self.redis_client.setex(key, ttl, self._serialize(value))
        except Exception:
            logger.warning("redis SET failed", extra={"key": key}, exc_info=True)

    def _cache_delete(self, *keys: str):
        """Delete one or more cache keys (best-effort)."""
        if self.redis_client is None:
            return None
        try:
            self.redis_client.delete(*keys)
            logger.debug("cache delete", extra={"keys": keys})
        except Exception:
            logger.warning("redis DEL failed", extra={"keys": keys}, exc_info=True)
