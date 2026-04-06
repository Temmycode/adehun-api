from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, ConditionServiceDep
from app.exceptions import (
    ConditionNotFoundError,
    ConditionSaveError,
    ParticipantNotFoundError,
)
from app.rate_limiting import limiter
from app.schemas.conditions_schema import (
    ConditionCreate,
    ConditionReject,
    ConditionResponse,
)

router = APIRouter(tags=["Conditions"])


@router.post("/agreements/{agreement_id}/conditions", response_model=ConditionResponse)
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
    except ConditionSaveError as e:
        raise HTTPException(status_code=500, detail=e.message)


@router.get(
    "/agreements/{agreement_id}/conditions", response_model=list[ConditionResponse]
)
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
    "/conditions/{condition_id}",
    response_model=ConditionResponse,
)
@limiter.limit("10/minute")
async def get_condition_details(
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


@router.post("/conditions/{condition_id}/approve", response_model=ConditionResponse)
@limiter.limit("10/minute")
async def approve_condition(
    request: Request,
    agreement_id: str,
    condition_id: str,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
):
    """
    Approve a condition for a given agreement.

    Returns:
        A condition response.
    """

    try:
        return condition_service.approve_condition(
            agreement_id, condition_id, current_user.user_id
        )
    except ConditionNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post(
    "/conditions/{condition_id}/reject",
    response_model=ConditionResponse,
)
@limiter.limit("10/minute")
async def reject_condition(
    request: Request,
    agreement_id: str,
    condition_id: str,
    current_user: ActiveUserDep,
    condition_service: ConditionServiceDep,
    reject_data: ConditionReject,
):
    """
    Reject a condition for a given agreement.

    Returns:
        A condition response.
    """

    try:
        return condition_service.reject_condition(
            agreement_id,
            condition_id,
            current_user.user_id,
            reject_data.rejected_reason,
        )
    except ConditionNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
