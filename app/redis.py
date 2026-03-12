import json
import logging
from typing import Annotated, Any, Generator

from fastapi import Depends
from redis import Redis

from app.config import settings

logger = logging.getLogger(__name__)


_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis(
            host=settings.redis_database_host,
            port=int(settings.redis_database_port),
            decode_responses=True,
            username="default",
            password=settings.redis_database_password,
        )
        _redis_client.ping()
        logger.info("Redis client initialized")

    return _redis_client


def get_redis_dep() -> Generator[Redis, Any, None]:
    yield get_redis_client()


RedisDep = Annotated[Redis, Depends(get_redis_dep)]


class RedisClient:
    def __init__(self, client: Redis):
        self.redis_client = client

    def _serialize(self, obj: Any) -> str:
        """Serialize a SQLModel/dict to a JSON string."""
        if hasattr(obj, "model_dump"):
            return json.dumps(obj.model_dump(mode="json"))
        return json.dumps(obj)

    def _cache_get(self, key: str) -> Any | None:
        """Return parsed JSON value from Redis, or None on miss/error."""
        try:
            raw = self.redis_client.get(key)
            if raw is None:
                logger.debug("Cache MISS  key=%s", key)
                return None
            logger.debug("Cache HIT   key=%s", key)
            return json.loads(raw)  # pyright: ignore[reportArgumentType]
        except Exception:
            logger.warning(
                "Redis GET failed for key=%s — falling back to DB", key, exc_info=True
            )
            return None

    def _cache_set(self, key: str, value: Any, ttl: int):
        try:
            self.redis_client.setex(key, ttl, self._serialize(value))
        except Exception:
            logger.warning("Redis SET failed for key=%s", key, exc_info=True)

    def _cache_delete(self, *keys: str):
        """Delete one or more cache keys (best-effort)."""
        try:
            self.redis_client.delete(*keys)
            logger.debug("Cache DEL   keys=%s", keys)
        except Exception:
            logger.warning("Redis DEL failed for keys=%s", keys, exc_info=True)
