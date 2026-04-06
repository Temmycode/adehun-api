import logging

from app.exceptions import (
    AgreementNotFoundError,
    AssetRetrievalError,
    AssetUploadError,
    ConditionNotFoundError,
)
from app.models import Asset
from app.models.asset_file import AssetFile
from app.repository.asset_repository import AssetRepository
from app.schemas.asset_schema import AssetCreateRequest, AssetResponse
from app.schemas.image_upload_schema import SignedUploadResponse
from app.service.image_upload_service import create_upload_signature

logger = logging.getLogger(__name__)


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
            logger.exception("Failed to create asset signature: %s", str(e))
            raise AssetUploadError() from e

    def add_asset_to_condition(
        self, user_id: str, condition_id: str, asset_data: AssetCreateRequest
    ) -> list[AssetResponse]:
        """Add assets to a condition"""
        try:
            condition = self.asset_repo.get_condition(condition_id)
            if not condition:
                logger.exception(
                    "Condition not found for condition_id: %s", condition_id
                )
                raise ConditionNotFoundError()

            participant = self.asset_repo.get_participant(
                user_id, condition.agreement_id
            )
            if not participant:
                logger.exception(
                    "Participant not found for user_id: %s, agreement_id: %s",
                    user_id,
                    condition.agreement_id,
                )
                raise PermissionError("User is not a participant of this agreement")

            files = [
                AssetFile(url=data.url, type=data.type) for data in asset_data.files
            ]
            self.asset_repo.add_and_flush(*files)

            assets = [
                Asset(
                    condition_id=condition_id,
                    file_id=file.file_id,
                    uploaded_by=participant.participant_id,
                )
                for file in files
            ]

            self.asset_repo.add_and_flush(*assets)
            self.asset_repo.commit()

            # Invalidate the cache
            self.asset_repo.invalidate_cache(_condition_asset_key(condition_id))

            # fetch the data
            assets = self.asset_repo.get_assets_by_ids(
                [asset.asset_id for asset in assets]
            )
            return [AssetResponse.model_validate(asset) for asset in assets]
        except Exception as e:
            logger.exception("Failed to upload asset: %s", str(e))
            self.asset_repo.rollback()
            raise AssetUploadError() from e

    def get_assets_for_condition(self, condition_id: str) -> list[AssetResponse]:
        """Get assets for a condition"""
        try:
            # check if condition exists
            condition = self.asset_repo.get_condition(condition_id)
            if not condition:
                raise ConditionNotFoundError()

            assets = self.asset_repo.get_condition_assets(condition_id)
            return [AssetResponse.model_validate(asset) for asset in assets]
        except Exception as e:
            logger.exception("Failed to get assets for condition: %s", str(e))
            raise AssetRetrievalError() from e

    def get_assets_for_agreement(self, agreement_id: str) -> list[AssetResponse]:
        """Get assets for an agreement"""

        try:
            # check if agreement exists
            agreement = self.asset_repo.get_agreement(agreement_id)
            if not agreement:
                raise AgreementNotFoundError()

            assets = self.asset_repo.get_agreement_assets(agreement_id)
            return [AssetResponse.model_validate(asset) for asset in assets]
        except Exception as e:
            logger.exception("Failed to get assets for agreement: %s", str(e))
            raise AssetRetrievalError from e
