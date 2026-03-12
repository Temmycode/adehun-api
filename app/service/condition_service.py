from redis import Redis

from app.redis import RedisClient
from app.repository.condition_repository import ConditionRepository


class ConditionService(RedisClient):
    def __init__(self, condition_repo: ConditionRepository, redis_client: Redis):
        super().__init__(redis_client)
        self.condition_repo = condition_repo
        
        

    def get_condition(self, condition_id: str):
        return self.condition_repo.get_by_id(condition_id)
