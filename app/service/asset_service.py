from app.logging import get_logger

from app.exceptions import (
    AgreementNotFoundError,
    AssetRetrievalError,
    AssetUploadError,
    ConditionNotFoundError,
    ForbiddenError,
)
from app.models import Asset
from app.models.asset_file import AssetFile
from app.repository.asset_repository import AssetRepository
from app.schemas.asset_schema import AssetCreateRequest, AssetResponse
from app.schemas.image_upload_schema import SignedUploadResponse
from app.service.image_upload_service import create_upload_signature

logger = get_logger(__name__)


def _condition_asset_key(condition_id: str) -> str:
    return f"condition:{condition_id}:asset"


class AssetService:
    def __init__(self, asset_repo: AssetRepository):
        self.asset_repo = asset_repo

    def create_asset_signature(self, condition_id: str) -> SignedUploadResponse:
        """Create a signature for uploading assets"""
        try:
            return create_upload_signature("adehun/assets")
        except Exception as e:
            logger.exception(
                "failed to create asset upload signature",
                extra={"condition_id": condition_id, "error": str(e)},
            )
            raise AssetUploadError() from e

    def add_asset_to_condition(
        self, user_id: str, condition_id: str, asset_data: AssetCreateRequest
    ) -> list[AssetResponse]:
        """Add assets to a condition"""
        try:
            condition = self.asset_repo.get_condition(condition_id)
            if not condition:
                logger.error(
                    "condition not found for asset upload",
                    extra={"condition_id": condition_id, "user_id": user_id},
                )
                raise ConditionNotFoundError()

            participant = self.asset_repo.get_participant(
                user_id, condition.agreement_id
            )
            if not participant:
                logger.error(
                    "participant not found for asset upload",
                    extra={
                        "user_id": user_id,
                        "agreement_id": condition.agreement_id,
                        "condition_id": condition_id,
                    },
                )
                raise ForbiddenError("User is not a participant of this agreement")

            files = [
                AssetFile(url=data.url, type=data.type) for data in asset_data.files
            ]
            self.asset_repo.add_and_flush(*files)

            assets = [
                Asset(
                    condition_id=condition_id,
                    file_id=file.id,
                    uploaded_by=participant.id,
                )
                for file in files
            ]

            self.asset_repo.add_and_flush(*assets)
            self.asset_repo.commit()

            # Invalidate the cache
            self.asset_repo.invalidate_cache(_condition_asset_key(condition_id))

            # fetch the data
            assets = self.asset_repo.get_assets_by_ids(
                [asset.id for asset in assets]
            )
            logger.info(
                "assets uploaded",
                extra={
                    "condition_id": condition_id,
                    "user_id": user_id,
                    "count": len(assets),
                },
            )
            return [AssetResponse.model_validate(asset) for asset in assets]
        except (ConditionNotFoundError, ForbiddenError):
            raise
        except Exception as e:
            logger.exception(
                "failed to upload assets",
                extra={
                    "condition_id": condition_id,
                    "user_id": user_id,
                    "error": str(e),
                },
            )
            self.asset_repo.rollback()
            raise AssetUploadError() from e

    def get_assets_for_condition(self, condition_id: str) -> list[AssetResponse]:
        """Get assets for a condition"""
        try:
            condition = self.asset_repo.get_condition(condition_id)
            if not condition:
                logger.error(
                    "condition not found when fetching assets",
                    extra={"condition_id": condition_id},
                )
                raise ConditionNotFoundError()

            assets = self.asset_repo.get_condition_assets(condition_id)
            return [AssetResponse.model_validate(asset) for asset in assets]
        except ConditionNotFoundError:
            raise
        except Exception as e:
            logger.exception(
                "failed to fetch condition assets",
                extra={"condition_id": condition_id, "error": str(e)},
            )
            raise AssetRetrievalError() from e

    def get_assets_for_agreement(self, agreement_id: str) -> list[AssetResponse]:
        """Get assets for an agreement"""
        try:
            agreement = self.asset_repo.get_agreement(agreement_id)
            if not agreement:
                logger.error(
                    "agreement not found when fetching assets",
                    extra={"agreement_id": agreement_id},
                )
                raise AgreementNotFoundError()

            assets = self.asset_repo.get_agreement_assets(agreement_id)
            return [AssetResponse.model_validate(asset) for asset in assets]
        except AgreementNotFoundError:
            raise
        except Exception as e:
            logger.exception(
                "failed to fetch agreement assets",
                extra={"agreement_id": agreement_id, "error": str(e)},
            )
            raise AssetRetrievalError from e
