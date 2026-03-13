from app.repository.stats_repository import StatsRepository
from app.schemas.stats_schema import UserStats


class StatsService:
    def __init__(self, stats_repo: StatsRepository):
        self.stats_repo = stats_repo

    def get_user_stats(self, user_id: int) -> UserStats:
        """Get user stats by user id."""
        user_stats = self.stats_repo.get_user_stats(user_id)
        return UserStats(
            active_agreements=user_stats[0],
            completed_agreements=user_stats[1],
            total_agreements=user_stats[2],
        )
