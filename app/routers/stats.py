from fastapi import APIRouter

from app.dependencies import ActiveUserDep, StatsServiceDep
from app.schemas.stats_schema import UserStats

router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("/user/", response_model=UserStats)
async def get_user_stats(current_user: ActiveUserDep, stats_service: StatsServiceDep):
    """
    Get user statistics.
    """

    return await stats_service.get_user_stats(current_user.user_id)
