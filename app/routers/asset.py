from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, AssetServiceDep
from app.schemas.asset_schema import AssetCreateRequest, AssetResponse
from app.schemas.image_upload_schema import SignedUploadResponse

router = APIRouter(
    tags=["Assets"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get(
    "/agreement/{agreement_id}/assets/",
    response_model=APIResponse[list[AssetResponse]],
    responses={404: {"model": NotFoundResponse}},
)
async def get_assets_for_agreement(
    request: Request,
    agreement_id: str,
    asset_service: AssetServiceDep,
    _: ActiveUserDep,
):
    """Get assets for an agreement."""
    return success_response(
        data=asset_service.get_assets_for_agreement(agreement_id)
    )


@router.post(
    "/conditions/{condition_id}/assets",
    response_model=APIResponse[list[AssetResponse]],
    responses={
        403: {"model": ForbiddenResponse},
        404: {"model": NotFoundResponse},
    },
)
async def add_asset_to_condition(
    request: Request,
    condition_id: str,
    asset_data: AssetCreateRequest,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
):
    """Add assets to a condition."""
    return success_response(
        data=asset_service.add_asset_to_condition(
            current_user.id, condition_id, asset_data
        )
    )


@router.get(
    "/conditions/{condition_id}/assets",
    response_model=APIResponse[list[AssetResponse]],
    responses={404: {"model": NotFoundResponse}},
)
async def get_assets_for_condition(
    request: Request,
    condition_id: str,
    asset_service: AssetServiceDep,
    _: ActiveUserDep,
):
    """Get assets for a condition."""
    return success_response(
        data=asset_service.get_assets_for_condition(condition_id)
    )


@router.get(
    "/conditions/{condition_id}/assets/upload-signature",
    response_model=APIResponse[SignedUploadResponse],
)
async def get_upload_signature(
    request: Request,
    condition_id: str,
    asset_service: AssetServiceDep,
    _: ActiveUserDep,
):
    """Get upload signature for assets."""
    return success_response(
        data=asset_service.create_asset_signature(condition_id)
    )
