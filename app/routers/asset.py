from fastapi import APIRouter, Request

from app.core.authz import require_participant, require_read_access
from app.core.response import (
    APIResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.database import SessionDep
from app.dependencies import ActiveUserDep, AssetServiceDep
from app.exceptions import ConditionNotFoundError
from app.models import Condition
from app.rate_limiting import limiter
from app.schemas.asset_schema import AssetCreateRequest, AssetResponse
from app.schemas.image_upload_schema import SignedUploadResponse

router = APIRouter(
    tags=["Assets"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


def _agreement_id_for_condition(session, condition_id: str) -> str:
    condition = session.get(Condition, condition_id)
    if condition is None:
        raise ConditionNotFoundError()
    return condition.agreement_id


@router.get(
    "/agreement/{agreement_id}/assets/",
    response_model=APIResponse[list[AssetResponse]],
    responses={403: {"model": ForbiddenResponse}, 404: {"model": NotFoundResponse}},
)
@limiter.limit("30/minute")
async def get_assets_for_agreement(
    request: Request,
    agreement_id: str,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
    session: SessionDep,
):
    """Get assets for an agreement."""
    require_read_access(session, agreement_id, current_user.id, current_user.email)
    return success_response(data=asset_service.get_assets_for_agreement(agreement_id))


@router.post(
    "/conditions/{condition_id}/assets",
    response_model=APIResponse[list[AssetResponse]],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("20/minute")
async def add_asset_to_condition(
    request: Request,
    condition_id: str,
    asset_data: AssetCreateRequest,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
    session: SessionDep,
):
    """Add assets to a condition. Participants only."""
    agreement_id = _agreement_id_for_condition(session, condition_id)
    require_participant(session, agreement_id, current_user.id)
    return success_response(
        data=asset_service.add_asset_to_condition(
            current_user.id, condition_id, asset_data
        )
    )


@router.post(
    "/conditions/{condition_id}/assets/{asset_id}/approve",
    response_model=APIResponse[AssetResponse],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("20/minute")
async def approve_asset(
    request: Request,
    condition_id: str,
    asset_id: str,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
):
    """Approve an asset. The depositor decides (checked in the service)."""
    return success_response(
        data=asset_service.approve_asset(condition_id, asset_id, current_user.id)
    )


@router.post(
    "/conditions/{condition_id}/assets/{asset_id}/reject",
    response_model=APIResponse[AssetResponse],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("20/minute")
async def reject_asset(
    request: Request,
    condition_id: str,
    asset_id: str,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
):
    """Reject an asset. The depositor decides (checked in the service)."""
    return success_response(
        data=asset_service.reject_asset(condition_id, asset_id, current_user.id)
    )


@router.get(
    "/conditions/{condition_id}/assets",
    response_model=APIResponse[list[AssetResponse]],
    responses={403: {"model": ForbiddenResponse}, 404: {"model": NotFoundResponse}},
)
@limiter.limit("30/minute")
async def get_assets_for_condition(
    request: Request,
    condition_id: str,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
    session: SessionDep,
):
    """Get assets for a condition."""
    agreement_id = _agreement_id_for_condition(session, condition_id)
    require_read_access(session, agreement_id, current_user.id, current_user.email)
    return success_response(data=asset_service.get_assets_for_condition(condition_id))


@router.get(
    "/conditions/{condition_id}/assets/upload-signature",
    response_model=APIResponse[SignedUploadResponse],
    responses={403: {"model": ForbiddenResponse}, 404: {"model": NotFoundResponse}},
)
@limiter.limit("20/minute")
async def get_upload_signature(
    request: Request,
    condition_id: str,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
    session: SessionDep,
):
    """Get a signed Cloudinary upload for this condition. Participants only."""
    agreement_id = _agreement_id_for_condition(session, condition_id)
    require_participant(session, agreement_id, current_user.id)
    return success_response(
        data=asset_service.create_asset_signature(condition_id, current_user.id)
    )
