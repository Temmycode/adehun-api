from limits.storage import RedisStorage
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings

REDIS_URL = f"redis://{settings.redis_database_host}:{settings.redis_database_port}"

storage = RedisStorage(REDIS_URL)


limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)
