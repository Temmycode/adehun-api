from app.logging import get_logger

from fastapi import APIRouter

from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, StatsServiceDep
from app.schemas.agreement_schema import AgreementStatistics

router = APIRouter(
    prefix="/stats",
    tags=["Stats"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)

logger = get_logger(__name__)


@router.get("/agreements/", response_model=APIResponse[AgreementStatistics])
async def get_user_agreement_stats(
    current_user: ActiveUserDep, stats_service: StatsServiceDep
):
    """Get agreement dashboard statistics for the current user."""
    logger.debug("fetching agreement stats", extra={"user_id": current_user.id})
    return success_response(data=stats_service.get_user_stats(current_user.id))
