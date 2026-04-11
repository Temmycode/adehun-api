import logging

from fastapi import APIRouter, HTTPException

from app.dependencies import ActiveUserDep, StatsServiceDep
from app.schemas.agreement_schema import AgreementStatistics

router = APIRouter(prefix="/stats", tags=["Stats"])

logger = logging.getLogger(__name__)


@router.get("/agreements/", response_model=AgreementStatistics)
async def get_user_agreement_stats(
    current_user: ActiveUserDep, stats_service: StatsServiceDep
):
    """
    Get agreement dashboard statistics for the current user.
    """

    try:
        logger.debug("fetching agreement stats", extra={"user_id": current_user.id})
        return stats_service.get_user_stats(current_user.id)
    except Exception as e:
        logger.exception(
            "failed to fetch agreement stats",
            extra={"user_id": current_user.id, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))
