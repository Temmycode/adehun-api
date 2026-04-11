import logging
from typing import Any

from redis import Redis
from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant, Asset, Condition
from app.redis import RedisClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_AGREEMENT_ASSETS = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_ASSETS = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_CONDITION_ASSETS = 60 * 60 * 24  # 24 hours – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_key(asset_id: str) -> str:
    return f"asset:{asset_id}"


def _agreement_asset_key(agreement_id: str) -> str:
    return f"agreement:{agreement_id}:asset"


def _condition_asset_key(condition_id: str) -> str:
    return f"condition:{condition_id}:asset"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class AssetRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  Helper Functions                                                  #
    # ------------------------------------------------------------------ #

    def invalidate_cache(self, key: str) -> None:
        if self.redis_client is not None:
            self.redis_client.delete(key)

    # ------------------------------------------------------------------ #
    #  Asset Operations                                                  #
    # ------------------------------------------------------------------ #

    def add_and_flush(self, *args: Any):
        """Flush an asset to the database to retrieve the id"""
        self.session.add_all(args)
        self.session.flush()

    def get_by_id(self, asset_id: str) -> Asset | None:
        """Get an asset by id"""
        key = _asset_key(asset_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("cache hit for asset", extra={"asset_id": asset_id})
            return Asset.model_validate(cached)

        logger.debug("fetching asset from db", extra={"asset_id": asset_id})
        asset = self.session.exec(
            select(Asset).where(Asset.id == asset_id)
        ).first()
        if asset:
            self._cache_set(key, asset, _TTL_ASSETS)
        else:
            logger.info("asset not found", extra={"asset_id": asset_id})
        return asset

    def get_assets_by_ids(self, asset_ids: list[str]) -> list[Asset]:
        """Get assets by ids"""
        return list(
            self.session.exec(select(Asset).where(Asset.id.in_(asset_ids))).all()  # pyright: ignore[reportAttributeAccessIssue]
        )

    def get_condition(self, condition_id: str) -> Condition | None:
        """Get a condition by id"""
        return self.session.get(Condition, condition_id)

    def get_agreement(self, agreement_id: str) -> Agreement | None:
        """Get an agreement by id"""
        return self.session.get(Agreement, agreement_id)

    def get_participant(
        self, user_id: str, agreement_id: str
    ) -> AgreementParticipant | None:
        """Get a participant by user_id and agreement_id"""
        return self.session.exec(
            select(AgreementParticipant).where(
                AgreementParticipant.user_id == user_id,
                AgreementParticipant.agreement_id == agreement_id,
            )
        ).first()

    def get_agreement_assets(self, agreement_id: str) -> list[Asset]:
        """Get all assets assigned to an agreement"""
        key = _agreement_asset_key(agreement_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("cache hit for agreement assets", extra={"agreement_id": agreement_id})
            return [Asset.model_validate(asset) for asset in cached]

        logger.debug("fetching agreement assets from db", extra={"agreement_id": agreement_id})
        assets = list(
            self.session.exec(
                select(Asset)
                .join(Condition)
                .where(Condition.agreement_id == agreement_id)
            ).all()
        )
        if assets:
            self._cache_set(
                key,
                [asset.model_dump(mode="json") for asset in assets],
                _TTL_AGREEMENT_ASSETS,
            )
        return assets

    def get_condition_assets(self, condition_id: str) -> list[Asset]:
        """Get all assets assigned to a condition"""
        key = _condition_asset_key(condition_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("cache hit for condition assets", extra={"condition_id": condition_id})
            return [Asset.model_validate(asset) for asset in cached]

        logger.debug("fetching condition assets from db", extra={"condition_id": condition_id})
        assets = list(
            self.session.exec(
                select(Asset)
                .join(Condition)
                .where(Condition.id == condition_id)
            ).all()
        )
        if assets:
            self._cache_set(
                key,
                [asset.model_dump(mode="json") for asset in assets],
                _TTL_CONDITION_ASSETS,
            )
        return assets

    def delete_asset(self, asset_id: str) -> None:
        asset = self.get_by_id(asset_id)
        if asset:
            self.session.delete(asset)
            self.session.commit()
            self._cache_delete(_asset_key(asset_id))

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_asset(self, asset: Asset, *, commit: bool = True) -> Asset:
        """Save an asset to the database"""
        self.session.add(asset)
        if commit:
            self.session.commit()
            self.session.refresh(asset)
        return asset

    def commit(self) -> None:
        """Commit the session"""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the session"""
        self.session.rollback()

    def refresh(self, asset: Asset) -> None:
        """Refresh an asset from the database"""
        self.session.refresh(asset)
