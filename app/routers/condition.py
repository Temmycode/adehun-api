from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, ConditionServiceDep
from app.exceptions import ConditionNotFoundError, ParticipantNotFoundError
from app.rate_limiting import limiter
from app.schemas.conditions_schema import ConditionCreate, ConditionResponse

router = APIRouter(prefix="/agreements/", tags=["Conditions"])


@router.post("/{agreement_id}/conditions")
@limiter.limit("5/minute")
async def add_condition_to_agreement(
    request: Request,
    agreement_id: str,
    condition_data: ConditionCreate,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
):
    """
    Add a condition to an agreement.

    Args:
        request: The incoming request.
        agreement_id: The ID of the agreement.
        current_user: The active user.
        condition_service: The condition service.

    Returns:
        The created condition response.
    """

    try:
        return condition_service.add_condition(
            agreement_id,
            current_user.user_id,
            condition_data,
        )
    except ParticipantNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/{agreement_id}/conditions", response_model=list[ConditionResponse])
@limiter.limit("10/minute")
async def get_conditions_for_agreement(
    request: Request,
    agreement_id: str,
    _: ActiveUserDep,
    condition_service: ConditionServiceDep,
):
    """
    Get conditions for a given agreement.

    Returns:
        A list of condition responses.
    """

    try:
        return condition_service.get_agreement_conditions(agreement_id)
    except ConditionNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get(
    "/{agreement_id}/conditions/{condition_id}", response_model=ConditionResponse
)
@limiter.limit("10/minute")
async def get_condition_for_agreement(
    request: Request,
    agreement_id: str,
    condition_id: str,
    _: ActiveUserDep,
    condition_service: ConditionServiceDep,
):
    """
    Get a condition for a given agreement.

    Returns:
        A condition response.
    """

    try:
        return condition_service.get_condition(agreement_id, condition_id)
    except ConditionNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
