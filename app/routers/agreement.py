from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, AgreementServiceDep
from app.exceptions import AgreementCreationError
from app.models import Agreement
from app.rate_limiting import limiter
from app.schemas.agreement_schema import AgreementCreate

router = APIRouter(
    prefix="/agreements",
    tags=["Agreements"],
)


@router.post("/", status_code=201, response_model=Agreement)
@limiter.limit("10/minute")
async def create_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_data: AgreementCreate,
    agreement_service: AgreementServiceDep,
) -> Agreement:
    """
    Create a new agreement.

    The authenticated user is automatically assigned as the depositor.
    All user IDs provided in `user_ids` are added as beneficiaries.
    """
    try:
        return agreement_service.create_agreement(current_user.user_id, agreement_data)
    except AgreementCreationError as e:
        raise HTTPException(status_code=500, detail=e.message)
