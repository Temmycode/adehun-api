from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.dependencies import ActiveUserDep, AgreementServiceDep
from app.exceptions import (
    AgreementAcceptanceError,
    AgreementCreationError,
    AgreementNotFoundError,
)
from app.models import Agreement
from app.rate_limiting import limiter
from app.schemas.agreement_schema import AgreementCreate, AgreementResponse

router = APIRouter(prefix="/agreements", tags=["Agreements"])


@router.post("/", status_code=201, response_model=AgreementResponse)
@limiter.limit("10/minute")
async def create_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_data: AgreementCreate,
    agreement_service: AgreementServiceDep,
    background_tasks: BackgroundTasks,
) -> AgreementResponse:
    """
    Create a new agreement.

    The authenticated user is automatically assigned as the depositor.
    All user IDs provided in `user_ids` are added as beneficiaries.
    """
    try:
        return agreement_service.create_agreement(
            current_user.user_id,
            agreement_data,
            background_tasks,
        )
    except AgreementCreationError as e:
        raise HTTPException(status_code=500, detail=e.message)


@router.get("/", response_model=list[AgreementResponse])
@limiter.limit("10/minute")
async def get_all_user_agreements(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
) -> list[AgreementResponse]:
    """
    Get all agreements for the authenticated user.
    """
    try:
        return agreement_service.get_all_user_agreements(current_user.user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{agreement_id}/", response_model=AgreementResponse)
@limiter.limit("10/minute")
async def accept_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    agreement_id: str,
) -> AgreementResponse:
    """
    Accept an agreement.
    """
    try:
        return agreement_service.accept_agreement(
            agreement_id, current_user.user_id, current_user.email
        )
    except AgreementAcceptanceError as e:
        raise HTTPException(status_code=500, detail=e.message)


@router.get("/{agreement_id}", response_model=AgreementResponse)
@limiter.limit("10/minute")
async def get_agreement(
    request: Request,
    _: ActiveUserDep,
    agreement_service: AgreementServiceDep,
    agreement_id: str,
) -> AgreementResponse:
    """
    Get an agreement by its ID.
    """
    try:
        return agreement_service.get_agreement(agreement_id)
    except AgreementNotFoundError as e:
        raise HTTPException(status_code=500, detail=e.message)
