from app.repository.stats_repository import StatsRepository
from app.schemas.agreement_schema import AgreementStatistics


class StatsService:
    def __init__(self, stats_repo: StatsRepository):
        self.stats_repo = stats_repo

    def get_user_stats(self, user_id: str) -> AgreementStatistics:
        """Get dashboard statistics for the given user's agreements"""

        active, completed, total = self.stats_repo.get_user_stats(user_id)
        return AgreementStatistics(
            active_agreements=active,
            completed_agreements=completed,
            total_agreements=total,
        )
