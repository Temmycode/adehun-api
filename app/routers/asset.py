from fastapi import APIRouter, HTTPException, Request

from app.dependencies import ActiveUserDep, AssetServiceDep
from app.exceptions import (
    AgreementNotFoundError,
    AssetRetrievalError,
    AssetUploadError,
    ConditionNotFoundError,
)
from app.schemas.asset_schema import AssetCreateRequest, AssetResponse
from app.schemas.image_upload_schema import SignedUploadResponse

router = APIRouter(tags=["Assets"])


@router.get("/agreement/{agreement_id}/assets/", response_model=list[AssetResponse])
async def get_assets_for_agreement(
    request: Request,
    agreement_id: str,
    asset_service: AssetServiceDep,
    _: ActiveUserDep,
):
    """
    Get assets for an agreement
    """

    try:
        assets = asset_service.get_assets_for_agreement(agreement_id)
        return [AssetResponse.model_validate(asset) for asset in assets]
    except AgreementNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
    except AssetRetrievalError as e:
        raise HTTPException(status_code=500, detail=e.message)


@router.post("/conditions/{condition_id}/assets", response_model=AssetResponse)
async def add_asset_to_condition(
    request: Request,
    condition_id: str,
    asset_data: AssetCreateRequest,
    asset_service: AssetServiceDep,
    current_user: ActiveUserDep,
):
    """
    Add assets to a condition
    """

    try:
        return asset_service.add_asset_to_condition(
            current_user.user_id, condition_id, asset_data
        )
    except ConditionNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AssetUploadError as e:
        raise HTTPException(status_code=500, detail=e.message)


@router.get("/conditions/{condition_id}/assets", response_model=list[AssetResponse])
async def get_assets_for_condition(
    request: Request,
    condition_id: str,
    asset_service: AssetServiceDep,
    _: ActiveUserDep,
):
    """
    Get assets for a condition
    """

    try:
        return asset_service.get_assets_for_condition(condition_id)
    except ConditionNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
    except AssetRetrievalError as e:
        raise HTTPException(status_code=500, detail=e.message)


@router.get(
    "/conditions/{condition_id}/assets/upload-signature",
    response_model=SignedUploadResponse,
)
async def get_upload_signature(
    request: Request,
    condition_id: str,
    asset_service: AssetServiceDep,
    _: ActiveUserDep,
):
    """
    Get upload signature for assets
    """

    try:
        return asset_service.create_asset_signature(condition_id)
    except AssetUploadError as e:
        raise HTTPException(status_code=500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
